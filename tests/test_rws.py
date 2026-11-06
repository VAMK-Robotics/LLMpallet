import json

import httpx

from backend.models import RobotSettings
from backend.rws_client import check_connection, format_num, send_job, to_rws_path


class FakeController:
    def __init__(self, fail_write=False, has_dir=False, mastership_status=204):
        self.calls = []
        self.files = {}
        self.dirs = {"$HOME"} | ({"$HOME/CSV"} if has_dir else set())
        self.symbols = {}
        self.fail_write = fail_write
        self.mastership_status = mastership_status
        self.master = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        self.calls.append((req.method, path))
        assert req.headers["accept"] == "application/hal+json;v=2.0"
        if path == "/rw/system":
            if "authorization" not in req.headers:
                return httpx.Response(401)
            return httpx.Response(200, json={"state": [{"name": "OmniCore_1", "rwversion": "7.21.5"}]},
                                  headers={"set-cookie": "-http-session-=abc; path=/"})
        if path == "/logout":
            return httpx.Response(204)
        if path.startswith("/fileservice/"):
            target = path[len("/fileservice/"):]
            if req.method == "GET":
                return httpx.Response(200 if target in self.dirs else 404)
            if req.method == "POST":
                form = dict(x.split("=") for x in req.content.decode().split("&"))
                assert form["fs-action"] == "create"
                self.dirs.add(f"{target}/{form['fs-newname']}")
                return httpx.Response(201)
            if req.method == "PUT":
                self.files[target] = req.content
                return httpx.Response(201)
        if path.startswith("/rw/mastership/edit/"):
            if path.endswith("request"):
                self.master = self.mastership_status < 300
            else:
                self.master = False
            return httpx.Response(self.mastership_status if path.endswith("request") else 204)
        if path.startswith("/rw/rapid/symbol/"):
            name = path.split("/")[-2]
            if req.method == "POST":
                if self.fail_write:
                    return httpx.Response(403, json={"status": {"code": -1, "msg": "Write access denied"}})
                assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
                self.symbols[name] = req.content.decode().split("=")[1]
                return httpx.Response(204)
            return httpx.Response(200, json={"state": [{"value": self.symbols.get(name, "0")}]})
        return httpx.Response(404)


def settings(**kw):
    return RobotSettings(protocol="http", ip_address="127.0.0.1", http_port=8080, **kw)


def test_paths_and_numbers():
    assert to_rws_path("HOME:/CSV/") == "$HOME/CSV"
    assert to_rws_path("home:CSV/sub") == "$HOME/CSV/sub"
    assert to_rws_path("$HOME/CSV") == "$HOME/CSV"
    assert format_num(400.0) == "400"
    assert format_num(312.5) == "312.5"
    assert settings().base_url == "http://127.0.0.1:8080"
    assert RobotSettings(ip_address="10.0.0.5").base_url == "https://10.0.0.5:443"


def test_send_job_happy_path():
    fake = FakeController()
    res = send_job(settings(), "pallet.csv", "1.0,2.0,3.0,0.0\n", (400, 300, 200.5), httpx.MockTransport(fake))
    assert res["ok"], res
    assert fake.files == {"$HOME/CSV/pallet.csv": b"1.0,2.0,3.0,0.0\n"}
    assert fake.symbols == {"nBoxX": "400", "nBoxY": "300", "nBoxZ": "200.5"}
    assert "$HOME/CSV" in fake.dirs
    methods = [c for c in fake.calls]
    assert methods[0] == ("GET", "/rw/system")
    assert ("POST", "/rw/mastership/edit/release") in methods
    assert methods[-1] == ("GET", "/logout")
    assert fake.master is False


def test_custom_names():
    fake = FakeController(has_dir=True)
    s = settings(task="T_ROB2", module="Data", var_x="a", var_y="b", var_z="c")
    res = send_job(s, "x.csv", "", (1, 2, 3), httpx.MockTransport(fake))
    assert res["ok"]
    assert fake.symbols == {"a": "1", "b": "2", "c": "3"}
    assert ("POST", "/rw/rapid/symbol/RAPID/T_ROB2/Data/a/data") in fake.calls
    assert not any(c[0] == "POST" and c[1].startswith("/fileservice") for c in fake.calls)


def test_write_failure_releases_mastership_and_logs_out():
    fake = FakeController(fail_write=True)
    res = send_job(settings(), "pallet.csv", "x\n", (1, 2, 3), httpx.MockTransport(fake))
    assert not res["ok"]
    failed = [s for s in res["steps"] if not s["ok"]]
    assert len(failed) == 3 and "Write access denied" in failed[0]["message"]
    assert ("POST", "/rw/mastership/edit/release") in fake.calls
    assert fake.calls[-1] == ("GET", "/logout")


def test_mastership_not_available_is_not_fatal():
    fake = FakeController(mastership_status=404)
    res = send_job(settings(), "pallet.csv", "x\n", (1, 2, 3), httpx.MockTransport(fake))
    assert res["ok"], json.dumps(res, indent=1)
    assert ("POST", "/rw/mastership/edit/release") not in fake.calls


def test_bad_login():
    def handler(req):
        return httpx.Response(401)
    res = send_job(settings(), "pallet.csv", "x\n", (1, 2, 3), httpx.MockTransport(handler))
    assert not res["ok"]
    assert len(res["steps"]) == 1 and "wrong user name or password" in res["steps"][0]["message"]


def test_connection_ok():
    res = check_connection(settings(), httpx.MockTransport(FakeController()))
    assert res["ok"]
    assert "RobotWare 7.21.5" in res["steps"][0]["message"]
