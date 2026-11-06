"""Minimal ABB Robot Web Services 2.0 client (OmniCore, RobotWare 7).

Reference: https://developercenter.robotstudio.com/api/RWS

Used requests:
  GET  /rw/system                                        login (HTTP Basic) and check access
  GET  /fileservice/{dir}                                does the directory exist
  POST /fileservice/{parent}   fs-newname, fs-action=create   create a directory
  PUT  /fileservice/{dir}/{file}                         upload (overwrite) a file
  POST /rw/mastership/edit/request | release             edit mastership
  POST /rw/rapid/symbol/RAPID/{task}/{module}/{var}/data value=<num>   write a RAPID symbol
  GET  /rw/rapid/symbol/RAPID/{task}/{module}/{var}/data               read it back
  GET  /logout                                           end the session
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from urllib.parse import quote

import httpx

from .models import RobotSettings

ACCEPT = "application/hal+json;v=2.0"
FORM = "application/x-www-form-urlencoded;v=2.0"
UPLOAD_CONTENT_TYPES = ("text/plain;v=2.0", "application/octet-stream;v=2.0", "application/octet-stream")


class RwsError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Step:
    name: str
    ok: bool
    message: str = ""


def to_rws_path(path: str) -> str:
    """'HOME:/CSV/' -> '$HOME/CSV'.  Paths that already start with '$' are kept."""
    path = path.strip().replace("\\", "/")
    m = re.match(r"^([A-Za-z_]+):/*(.*)$", path)
    if m:
        device, rest = m.group(1).upper(), m.group(2)
        path = f"${device}/{rest}"
    return path.strip("/")


def _encode(path: str) -> str:
    return quote(path, safe="/$")


def format_num(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _find_key(obj, keys: tuple[str, ...]):
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and isinstance(obj[k], (str, int, float)):
                return obj[k]
        for v in obj.values():
            found = _find_key(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_key(v, keys)
            if found is not None:
                return found
    return None


def _error_text(resp: httpx.Response) -> str:
    detail = None
    try:
        detail = _find_key(resp.json(), ("msg", "message", "detail"))
    except (json.JSONDecodeError, ValueError):
        pass
    if detail is None:
        detail = re.sub(r"<[^>]+>", " ", resp.text or "").strip()[:300]
    hints = {
        401: "wrong user name or password",
        403: "access denied – check the user's UAS grants and the operating mode",
        404: "not found – check the path / task / module / variable name",
        409: "conflict – mastership is held by another client (e.g. FlexPendant or RobotStudio)",
        415: "unsupported content type",
        503: "controller busy or too many sessions",
    }
    hint = hints.get(resp.status_code, "")
    parts = [f"HTTP {resp.status_code}"] + [s for s in (hint, str(detail) if detail else "") if s]
    return " – ".join(parts)


class RwsClient:
    def __init__(self, settings: RobotSettings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self._auth = httpx.BasicAuth(settings.username, settings.password or "")
        self._logged_in = False
        self.http = httpx.Client(
            base_url=settings.base_url,
            headers={"Accept": ACCEPT},
            verify=settings.verify_cert,
            timeout=settings.timeout_s,
            transport=transport,
        )

    # ------------------------------------------------------------------ plumbing
    def __enter__(self) -> "RwsClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._logged_in:
                self.logout()
        finally:
            self.http.close()

    def _request(self, method: str, path: str, ok: tuple[int, ...] = (200, 201, 204), **kw) -> httpx.Response:
        try:
            resp = self.http.request(method, path, auth=None if self._logged_in else self._auth, **kw)
            if resp.status_code == 401 and self._logged_in:  # session expired -> retry with credentials
                resp = self.http.request(method, path, auth=self._auth, **kw)
        except httpx.ConnectError as e:
            raise RwsError(f"Cannot connect to {self.s.base_url}: {e}") from e
        except httpx.TimeoutException as e:
            raise RwsError(f"Timeout connecting to {self.s.base_url}") from e
        except httpx.HTTPError as e:
            raise RwsError(f"Connection error: {e}") from e
        if resp.status_code not in ok:
            raise RwsError(_error_text(resp), resp.status_code)
        return resp

    # ------------------------------------------------------------------ API
    def login(self) -> dict:
        resp = self._request("GET", "/rw/system")
        self._logged_in = True
        try:
            return resp.json()
        except ValueError:
            return {}

    def logout(self) -> None:
        try:
            self.http.get("/logout")
        except httpx.HTTPError:
            pass
        self._logged_in = False

    def system_summary(self, info: dict) -> str:
        name = _find_key(info, ("name", "sysname"))
        rw = _find_key(info, ("rwversion", "rwversionname"))
        return ", ".join(x for x in (f"system {name}" if name else "", f"RobotWare {rw}" if rw else "") if x)

    def ensure_directory(self, directory: str) -> list[str]:
        """Create every missing segment of directory. Returns the created paths."""
        rws_dir = to_rws_path(directory)
        segments = rws_dir.split("/")
        created = []
        current = segments[0]
        for seg in segments[1:]:
            target = f"{current}/{seg}"
            resp = self._request("GET", f"/fileservice/{_encode(target)}", ok=(200, 204, 404))
            if resp.status_code == 404:
                self._request("POST", f"/fileservice/{_encode(current)}",
                              data={"fs-newname": seg, "fs-action": "create"},
                              headers={"Content-Type": FORM}, ok=(200, 201, 204))
                created.append(target)
            current = target
        return created

    def upload_file(self, directory: str, filename: str, content: bytes) -> str:
        path = f"{to_rws_path(directory)}/{filename}"
        last: RwsError | None = None
        for ctype in UPLOAD_CONTENT_TYPES:
            try:
                self._request("PUT", f"/fileservice/{_encode(path)}", content=content,
                              headers={"Content-Type": ctype}, ok=(200, 201, 204))
                return path
            except RwsError as e:
                if e.status != 415:
                    raise
                last = e
        raise last or RwsError("Upload failed")

    def request_mastership(self) -> None:
        self._request("POST", "/rw/mastership/edit/request", headers={"Content-Type": FORM}, content=b"")

    def release_mastership(self) -> None:
        self._request("POST", "/rw/mastership/edit/release", headers={"Content-Type": FORM}, content=b"")

    def _symbol_path(self, task: str, module: str, var: str) -> str:
        return f"/rw/rapid/symbol/RAPID/{_encode(task)}/{_encode(module)}/{_encode(var)}/data"

    def write_num(self, task: str, module: str, var: str, value: float) -> None:
        self._request("POST", self._symbol_path(task, module, var),
                      data={"value": format_num(value)}, headers={"Content-Type": FORM})

    def read_symbol(self, task: str, module: str, var: str) -> str | None:
        resp = self._request("GET", self._symbol_path(task, module, var))
        try:
            v = _find_key(resp.json(), ("value",))
        except ValueError:
            return None
        return None if v is None else str(v)


# ---------------------------------------------------------------------- high level operations

def _run(steps: list[Step], name: str, fn: Callable[[], str | None]) -> bool:
    try:
        msg = fn() or ""
        steps.append(Step(name, True, msg))
        return True
    except RwsError as e:
        steps.append(Step(name, False, str(e)))
        return False


def check_connection(settings: RobotSettings, transport: httpx.BaseTransport | None = None) -> dict:
    steps: list[Step] = []
    client = RwsClient(settings, transport)
    try:
        _run(steps, f"Login to {settings.base_url}", lambda: client.system_summary(client.login()))
    finally:
        client.close()
    if steps and steps[-1].ok:
        steps.append(Step("Logout", True))
    return {"ok": all(s.ok for s in steps), "steps": [asdict(s) for s in steps]}


def send_job(settings: RobotSettings, filename: str, csv_text: str, dims: tuple[float, float, float],
             transport: httpx.BaseTransport | None = None) -> dict:
    """Upload the CSV and write the box dimensions. Every step is reported."""
    steps: list[Step] = []
    client = RwsClient(settings, transport)
    try:
        if not _run(steps, f"Login to {settings.base_url}", lambda: client.system_summary(client.login())):
            return {"ok": False, "steps": [asdict(s) for s in steps]}

        def ensure() -> str:
            created = client.ensure_directory(settings.csv_directory)
            return f"created {', '.join(created)}" if created else "exists"

        if _run(steps, f"Directory {settings.csv_directory}", ensure):
            _run(steps, f"Upload {filename}",
                 lambda: f"{len(csv_text.splitlines())} rows -> {client.upload_file(settings.csv_directory, filename, csv_text.encode('ascii'))}")

        have_master = False
        try:
            client.request_mastership()
            have_master = True
            steps.append(Step("Request edit mastership", True))
        except RwsError as e:
            # Not fatal: if the controller rejects the request, the writes below report the real error.
            steps.append(Step("Request edit mastership", e.status in (404, 405),
                              f"{e} – trying to write without explicit mastership"))
        try:
            for var, value in zip((settings.var_x, settings.var_y, settings.var_z), dims):
                label = f"Write {settings.task}/{settings.module}/{var} := {format_num(value)}"

                def write(var=var, value=value) -> str:
                    client.write_num(settings.task, settings.module, var, value)
                    try:
                        back = client.read_symbol(settings.task, settings.module, var)
                    except RwsError as e:
                        return f"written (read back failed: {e})"
                    if back is None:
                        return "written"
                    try:
                        if abs(float(back) - value) > 1e-3:
                            raise RwsError(f"read back {back}, expected {format_num(value)}")
                    except ValueError:
                        return f"written, read back '{back}'"
                    return f"verified ({back})"

                _run(steps, label, write)
        finally:
            if have_master:
                _run(steps, "Release edit mastership", lambda: client.release_mastership())
    finally:
        client.close()
    steps.append(Step("Logout", True))
    return {"ok": all(s.ok for s in steps), "steps": [asdict(s) for s in steps]}
