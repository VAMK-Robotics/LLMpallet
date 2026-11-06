"""Persistent configuration in config/config.json (robot settings + last palletizing job)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from pydantic import ValidationError

from .models import PalletParams, RobotSettings, RobotSettingsUpdate

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = Path(os.environ.get("LLMPALLET_CONFIG", ROOT / "config" / "config.json"))


class ConfigStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.robot = RobotSettings()
        self.job = PalletParams()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # keep defaults, do not overwrite a file we cannot read
        try:
            self.robot = RobotSettings(**data.get("robot", {}))
        except ValidationError:
            pass
        try:
            self.job = PalletParams(**data.get("job", {}))
        except ValidationError:
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"robot": self.robot.model_dump(), "job": self.job.model_dump()},
                                  indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def public_robot(self) -> dict:
        data = self.robot.model_dump()
        data.pop("password")
        data["password_set"] = bool(self.robot.password)
        return data

    def update_robot(self, update: RobotSettingsUpdate) -> None:
        with self._lock:
            data = update.model_dump()
            if data.get("password") is None:
                data["password"] = self.robot.password
            self.robot = RobotSettings(**data)
            self._save()

    def update_job(self, job: PalletParams) -> None:
        with self._lock:
            self.job = job
            self._save()
