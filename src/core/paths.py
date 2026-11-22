"""Path discovery and process detection helpers for FF7 Steam Edition."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SUPPORTED_LANGS: tuple[str, ...] = ("ja", "en", "de", "es", "fr")

LANG_LABELS: dict[str, str] = {
    "ja": "日本語 (lang-ja)",
    "en": "English (lang-en)",
    "de": "Deutsch (lang-de)",
    "es": "Español (lang-es)",
    "fr": "Français (lang-fr)",
}

GAME_FOLDER_NAME = "FINAL FANTASY VII Steam Edition"


def get_project_root() -> Path:
    """Return the root directory of the ff7 tool project."""
    return Path(__file__).resolve().parents[2]


def get_user_data_dir(project_root: Path | None = None) -> Path:
    """Return (and ensure) the user_data directory under project_root."""
    root = project_root if project_root is not None else get_project_root()
    data_dir = root / "user_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_backup_dir(project_root: Path | None = None) -> Path:
    """Return (and ensure) the directory storing original scene.bin backups."""
    backup_dir = get_user_data_dir(project_root) / "backups" / "scene"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def validate_game_dir(path: Path) -> bool:
    """Return True if path looks like an FF7 Steam Edition (2026) install folder."""
    if not path.is_dir():
        return False
    return (path / "FFVII.exe").is_file() and (path / "ff7" / "workingdir" / "data").is_dir()


def _steam_library_candidates() -> list[Path]:
    """Collect Steam library root paths from standard locations and libraryfolders.vdf."""
    steam_roots: list[Path] = []
    for env_key in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env_key)
        if base:
            steam_roots.append(Path(base) / "Steam")

    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
                if steam_path:
                    steam_roots.append(Path(steam_path))
        except OSError:
            pass

    libraries: list[Path] = [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
        Path(r"D:\SteamLibrary"),
        Path(r"E:\SteamLibrary"),
    ]

    for steam_root in steam_roots:
        if steam_root not in libraries:
            libraries.append(steam_root)
        vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf_path.is_file():
            try:
                content = vdf_path.read_text(encoding="utf-8", errors="ignore")
                for raw_path in re.findall(r'"path"\s+"([^"]+)"', content):
                    normalized = Path(raw_path.replace("\\\\", "\\"))
                    if normalized not in libraries:
                        libraries.append(normalized)
            except OSError:
                pass

    return libraries


def detect_game_dir() -> Path | None:
    """Auto-detect the FINAL FANTASY VII Steam Edition installation directory."""
    for lib_root in _steam_library_candidates():
        candidate = lib_root / "steamapps" / "common" / GAME_FOLDER_NAME
        if validate_game_dir(candidate):
            return candidate
    return None


def get_scene_bin_path(game_dir: Path, lang: str = "ja") -> Path:
    """Return the scene.bin path for the given language code."""
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"Unsupported language code: {lang!r}")
    return game_dir / "ff7" / "workingdir" / "data" / f"lang-{lang}" / "battle" / "scene.bin"


def get_kernel_bin_path(game_dir: Path, lang: str = "ja") -> Path:
    """Return the kernel.bin path for the given language code."""
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"Unsupported language code: {lang!r}")
    return game_dir / "ff7" / "workingdir" / "data" / f"lang-{lang}" / "kernel" / "kernel.bin"


def get_executable_paths(game_dir: Path) -> tuple[Path, Path]:
    """Return (FFVII.exe, FFVII_LAUNCHER.exe) paths under game_dir."""
    return game_dir / "FFVII.exe", game_dir / "FFVII_LAUNCHER.exe"


def is_game_running() -> bool:
    """Return True if FFVII.exe is currently running on Windows."""
    if sys.platform != "win32":
        return False
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq FFVII.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        return "ffvii.exe" in proc.stdout.lower()
    except Exception:
        return False
