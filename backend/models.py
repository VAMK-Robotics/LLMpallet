"""Pydantic models shared by the API, the engine and the config store."""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

PatternName = Literal["column", "interlocked", "pinwheel", "optimized"]
Rotation = Literal[-90, 0, 90, 180]

_RAPID_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_FILENAME = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
_HOST = re.compile(r"^[A-Za-z0-9.\-:\[\]]{1,255}$")


def normalize_filename(name: str) -> str:
    """Validate a CSV file name and make sure it ends with .csv."""
    name = (name or "").strip()
    if not name:
        name = "pallet.csv"
    if not name.lower().endswith(".csv"):
        name += ".csv"
    if not _FILENAME.match(name) or name.startswith("."):
        raise ValueError("File name may only contain letters, digits, '_', '-' and '.'")
    return name


class LayerConfig(BaseModel):
    pattern: PatternName = "column"
    # column / interlocked: rotation of all boxes (interlocked adds 90 deg on odd layers)
    # pinwheel: rotation of the first block, the following blocks get +90, +180, +270
    rotation: Rotation = 0
    # optimized: rotation used for lengthwise boxes (length along X) and crosswise boxes
    rot_long: Literal[0, 180] = 0
    rot_cross: Literal[-90, 90] = 90


class PalletParams(BaseModel):
    box_length: float = Field(400.0, gt=0, le=1200, description="Box dimension along X at 0 deg (nBoxX)")
    box_width: float = Field(300.0, gt=0, le=1200, description="Box dimension along Y at 0 deg (nBoxY)")
    box_height: float = Field(200.0, gt=0, le=3000, description="Box height (nBoxZ)")
    total_boxes: int = Field(18, ge=1, le=10000)
    layer_count: int = Field(3, ge=1, le=100)
    gap: float = Field(0.0, ge=0, le=500)
    border_x: float = Field(0.0, ge=0, lt=600)
    border_y: float = Field(0.0, ge=0, lt=400)
    interlayer_thickness: float = Field(0.0, ge=0, le=100)
    interlayer_bottom: bool = False
    partial_layer_mode: Literal["centered", "start_corner"] = "centered"
    primary_axis: Literal["x", "y"] = "x"
    layers: list[LayerConfig] = Field(default_factory=list)
    filename: str = "pallet.csv"

    def layer_config(self, index: int) -> LayerConfig:
        if index < len(self.layers):
            return self.layers[index]
        return self.layers[-1] if self.layers else LayerConfig()


class RobotSettings(BaseModel):
    protocol: Literal["https", "http"] = "https"
    ip_address: str = "192.168.125.1"
    http_port: int = Field(80, ge=1, le=65535)
    https_port: int = Field(443, ge=1, le=65535)
    username: str = "Default User"
    password: str = "robotics"
    verify_cert: bool = False
    timeout_s: float = Field(10.0, gt=0, le=120)
    csv_directory: str = "HOME:/CSV/"
    task: str = "T_ROB1"
    module: str = "MainModule"
    var_x: str = "nBoxX"
    var_y: str = "nBoxY"
    var_z: str = "nBoxZ"
    default_filename: str = "pallet.csv"

    @field_validator("ip_address")
    @classmethod
    def _check_host(cls, v: str) -> str:
        v = v.strip()
        if not _HOST.match(v):
            raise ValueError("Invalid IP address or host name")
        return v

    @field_validator("task", "module", "var_x", "var_y", "var_z")
    @classmethod
    def _check_rapid_name(cls, v: str) -> str:
        v = v.strip()
        if not _RAPID_NAME.match(v):
            raise ValueError("Must be a valid RAPID name (letter first, then letters, digits or '_', max 32)")
        return v

    @field_validator("csv_directory")
    @classmethod
    def _check_dir(cls, v: str) -> str:
        v = v.strip()
        if not v or ".." in v or any(c in v for c in '<>"|?*\\'):
            raise ValueError("Invalid directory, use e.g. HOME:/CSV/")
        return v

    @field_validator("default_filename")
    @classmethod
    def _check_filename(cls, v: str) -> str:
        return normalize_filename(v)

    @property
    def port(self) -> int:
        return self.https_port if self.protocol == "https" else self.http_port

    @property
    def base_url(self) -> str:
        host = self.ip_address
        if ":" in host and not host.startswith("["):  # IPv6 literal
            host = f"[{host}]"
        return f"{self.protocol}://{host}:{self.port}"


class RobotSettingsUpdate(RobotSettings):
    """Same as RobotSettings, but password None means 'keep the stored password'."""

    password: Optional[str] = None  # type: ignore[assignment]


class GenerateRequest(BaseModel):
    params: PalletParams
    filename: Optional[str] = None
