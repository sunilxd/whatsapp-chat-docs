"""Thin wrapper around the `adb` command-line tool."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AdbError(RuntimeError):
    pass


@dataclass
class Device:
    serial: str
    state: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.model or 'Android'} ({self.serial}) - {self.state}"


@dataclass
class RemoteFile:
    path: str
    size: int
    mtime: int

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def find_adb(custom: str | None = None) -> str | None:
    candidates = [
        custom,
        shutil.which("adb"),
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
        os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
        os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


def shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


class Adb:
    def __init__(self, adb_path: str, serial: str | None = None):
        self.adb_path = adb_path
        self.serial = serial

    def _cmd(self, *args: str) -> list[str]:
        base = [self.adb_path]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def run(self, *args: str, check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            self._cmd(*args), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise AdbError((proc.stderr or proc.stdout).strip() or f"adb {' '.join(args)} failed")
        return proc

    def shell(self, command: str, check: bool = False) -> str:
        return self.run("shell", command, check=check).stdout

    def devices(self) -> list[Device]:
        out = Adb(self.adb_path).run("devices", "-l").stdout
        devices = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
            devices.append(Device(parts[0], parts[1], model.replace("_", " ")))
        return devices

    def list_files(self, remote_dir: str) -> list[RemoteFile]:
        """Recursively list files under remote_dir with size and mtime."""
        out = self.shell(
            f"find {shell_quote(remote_dir)} -type f -exec stat -c '%s|%Y|%n' {{}} + 2>/dev/null"
        )
        files = []
        for line in out.splitlines():
            parts = line.rstrip("\r").split("|", 2)
            if len(parts) == 3 and parts[0].isdigit():
                files.append(RemoteFile(parts[2], int(parts[0]), int(parts[1])))
        return files

    def pull(self, remote: str, local: str | Path) -> None:
        self.run("pull", "-a", remote, str(local))

    def remove(self, remote: str) -> None:
        self.shell(f"rm -f {shell_quote(remote)}")
