"""Persistent local state store for user settings and companion progress."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.paths import SUPPORTED_LANGS


def _clamp_multiplier(value: Any, default: float = 1.0) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(num):
        return default
    return max(0.0, min(100.0, round(num, 2)))


@dataclass
class ToolState:
    """In-memory representation of user_data/state.json."""

    game_dir: str | None = None
    selected_lang: str = "ja"
    patch_drop_100: bool = True
    patch_rare_first: bool = True
    patch_steal_100: bool = False
    patch_exp_mult: float = 1.0
    patch_ap_mult: float = 1.0
    patch_gil_mult: float = 1.0
    missables_checked: dict[str, bool] = field(default_factory=dict)
    missables_notes: dict[str, str] = field(default_factory=dict)
    enemy_skills_checked: dict[str, list[bool]] = field(default_factory=dict)
    enemy_skill_materias_obtained: list[bool] = field(
        default_factory=lambda: [False, False, False, False]
    )

    def normalize(self) -> None:
        """Sanitize loaded fields to valid shapes and types."""
        if self.selected_lang not in SUPPORTED_LANGS:
            self.selected_lang = "ja"

        self.patch_drop_100 = bool(self.patch_drop_100)
        self.patch_rare_first = bool(self.patch_rare_first)
        self.patch_steal_100 = bool(self.patch_steal_100)
        self.patch_exp_mult = _clamp_multiplier(self.patch_exp_mult)
        self.patch_ap_mult = _clamp_multiplier(self.patch_ap_mult)
        self.patch_gil_mult = _clamp_multiplier(self.patch_gil_mult)

        self.missables_checked = {
            str(k): bool(v) for k, v in self.missables_checked.items()
        }
        self.missables_notes = {
            str(k): str(v) for k, v in self.missables_notes.items() if str(v)
        }

        normalized_skills: dict[str, list[bool]] = {}
        for k, vals in self.enemy_skills_checked.items():
            row = [bool(x) for x in list(vals)[:4]]
            while len(row) < 4:
                row.append(False)
            normalized_skills[str(k)] = row
        self.enemy_skills_checked = normalized_skills

        materias = [bool(x) for x in list(self.enemy_skill_materias_obtained)[:4]]
        while len(materias) < 4:
            materias.append(False)
        self.enemy_skill_materias_obtained = materias

    def to_dict(self) -> dict[str, Any]:
        self.normalize()
        return {
            "game_dir": self.game_dir,
            "selected_lang": self.selected_lang,
            "patch_drop_100": self.patch_drop_100,
            "patch_rare_first": self.patch_rare_first,
            "patch_steal_100": self.patch_steal_100,
            "patch_exp_mult": self.patch_exp_mult,
            "patch_ap_mult": self.patch_ap_mult,
            "patch_gil_mult": self.patch_gil_mult,
            "missables_checked": self.missables_checked,
            "missables_notes": self.missables_notes,
            "enemy_skills_checked": self.enemy_skills_checked,
            "enemy_skill_materias_obtained": self.enemy_skill_materias_obtained,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ToolState:
        state = cls(
            game_dir=raw.get("game_dir") if isinstance(raw.get("game_dir"), str) else None,
            selected_lang=str(raw.get("selected_lang", "ja")),
            patch_drop_100=bool(raw.get("patch_drop_100", True)),
            patch_rare_first=bool(raw.get("patch_rare_first", True)),
            patch_steal_100=bool(raw.get("patch_steal_100", False)),
            patch_exp_mult=raw.get("patch_exp_mult", 1.0),
            patch_ap_mult=raw.get("patch_ap_mult", 1.0),
            patch_gil_mult=raw.get("patch_gil_mult", 1.0),
            missables_checked=dict(raw.get("missables_checked", {}))
            if isinstance(raw.get("missables_checked"), dict)
            else {},
            missables_notes=dict(raw.get("missables_notes", {}))
            if isinstance(raw.get("missables_notes"), dict)
            else {},
            enemy_skills_checked=dict(raw.get("enemy_skills_checked", {}))
            if isinstance(raw.get("enemy_skills_checked"), dict)
            else {},
            enemy_skill_materias_obtained=list(
                raw.get("enemy_skill_materias_obtained", [False, False, False, False])
            )
            if isinstance(raw.get("enemy_skill_materias_obtained"), list)
            else [False, False, False, False],
        )
        state.normalize()
        return state


class StateStore:
    """Loads and atomically saves ToolState to a JSON file."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def load(self) -> ToolState:
        if not self.state_path.is_file():
            return ToolState()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return ToolState.from_dict(data)
        except (OSError, json.JSONDecodeError):
            pass
        return ToolState()

    def save(self, state: ToolState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_name(f"{self.state_path.name}.{os.getpid()}.tmp")
        payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n"
        try:
            with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise
