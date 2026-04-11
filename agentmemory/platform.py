from __future__ import annotations

import os
import shutil
from pathlib import Path


def is_windows() -> bool:
    return os.name == "nt"


def shell_command() -> str:
    if is_windows():
        return shutil.which("pwsh") or "pwsh"
    return shutil.which("sh") or "sh"


def launcher_path(base_dir: Path, stem: str) -> Path:
    suffix = ".ps1" if is_windows() else ".sh"
    return base_dir / f"{stem}{suffix}"


def launcher_command(script_path: Path) -> list[str]:
    if is_windows():
        return [shell_command(), "-NoLogo", "-NoProfile", "-File", str(script_path)]
    return [shell_command(), str(script_path)]


def venv_python_path(base_dir: Path) -> Path:
    if is_windows():
        return base_dir / ".venv" / "Scripts" / "python.exe"
    return base_dir / ".venv" / "bin" / "python"
