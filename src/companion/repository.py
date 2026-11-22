"""Repository for loading, filtering, and summarizing FF7 companion guide data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.state_store import ToolState

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class MissableItem:
    id: str
    disc: str
    order: int
    area: str
    category: str
    priority: str
    name: str
    how_to_get: str
    deadline: str


@dataclass(frozen=True)
class EnemySkillMateriaInfo:
    slot: int
    label: str
    location: str


@dataclass(frozen=True)
class EnemySkillItem:
    id: int
    name: str
    mp: int
    category: str
    effect: str
    enemies: str
    manipulate_required: bool
    manipulate_note: str
    missable: bool
    missable_note: str


class CompanionRepository:
    """Loads bundled FF7 guide JSON data and provides query/aggregation helpers."""

    def __init__(self, data_dir: Path | None = None) -> None:
        base = data_dir if data_dir is not None else DATA_DIR
        self._missables = self._load_missables(base / "missables.json")
        self._materias, self._enemy_skills = self._load_enemy_skills(base / "enemy_skills.json")

    @staticmethod
    def _load_missables(path: Path) -> list[MissableItem]:
        raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        items = [
            MissableItem(
                id=str(entry["id"]),
                disc=str(entry["disc"]),
                order=int(entry["order"]),
                area=str(entry["area"]),
                category=str(entry["category"]),
                priority=str(entry["priority"]),
                name=str(entry["name"]),
                how_to_get=str(entry["how_to_get"]),
                deadline=str(entry["deadline"]),
            )
            for entry in raw
        ]
        return sorted(items, key=lambda item: item.order)

    @staticmethod
    def _load_enemy_skills(
        path: Path,
    ) -> tuple[list[EnemySkillMateriaInfo], list[EnemySkillItem]]:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        materias = [
            EnemySkillMateriaInfo(
                slot=int(m["slot"]),
                label=str(m["label"]),
                location=str(m["location"]),
            )
            for m in raw["materias"]
        ]
        skills = [
            EnemySkillItem(
                id=int(s["id"]),
                name=str(s["name"]),
                mp=int(s["mp"]),
                category=str(s["category"]),
                effect=str(s["effect"]),
                enemies=str(s["enemies"]),
                manipulate_required=bool(s["manipulate_required"]),
                manipulate_note=str(s["manipulate_note"]),
                missable=bool(s["missable"]),
                missable_note=str(s["missable_note"]),
            )
            for s in raw["skills"]
        ]
        skills.sort(key=lambda item: item.id)
        return materias, skills

    @property
    def missables(self) -> list[MissableItem]:
        return list(self._missables)

    @property
    def materias(self) -> list[EnemySkillMateriaInfo]:
        return list(self._materias)

    @property
    def enemy_skills(self) -> list[EnemySkillItem]:
        return list(self._enemy_skills)

    def get_missable_categories(self) -> list[str]:
        seen: list[str] = []
        for item in self._missables:
            if item.category not in seen:
                seen.append(item.category)
        return seen

    def filter_missables(
        self,
        state: ToolState,
        *,
        disc: str = "すべて",
        category: str = "すべて",
        only_unchecked: bool = False,
        query: str = "",
    ) -> list[MissableItem]:
        q = query.strip().lower()
        results: list[MissableItem] = []
        for item in self._missables:
            if disc != "すべて" and item.disc != disc:
                continue
            if category != "すべて" and item.category != category:
                continue
            if only_unchecked and state.missables_checked.get(item.id, False):
                continue
            if q:
                haystack = " ".join(
                    (item.name, item.area, item.category, item.how_to_get, item.deadline)
                ).lower()
                if q not in haystack:
                    continue
            results.append(item)
        return results

    def summarize_missables(self, state: ToolState) -> dict[str, Any]:
        total = len(self._missables)
        completed = sum(1 for m in self._missables if state.missables_checked.get(m.id, False))
        pct = (completed / total * 100.0) if total else 0.0
        return {
            "completed": completed,
            "total": total,
            "percent": pct,
        }

    def filter_enemy_skills(
        self,
        state: ToolState,
        *,
        mode: str = "すべて",  # "すべて" | "未習得あり" | "期間限定のみ"
        query: str = "",
    ) -> list[EnemySkillItem]:
        q = query.strip().lower()
        results: list[EnemySkillItem] = []
        for skill in self._enemy_skills:
            if mode == "期間限定のみ" and not skill.missable:
                continue
            if mode == "未習得あり":
                learned = state.enemy_skills_checked.get(str(skill.id), [False] * 4)
                if all(learned[:4]):
                    continue
            if q:
                haystack = " ".join(
                    (skill.name, skill.category, skill.effect, skill.enemies, skill.manipulate_note)
                ).lower()
                if q not in haystack:
                    continue
            results.append(skill)
        return results

    def summarize_enemy_skills(self, state: ToolState) -> dict[str, Any]:
        total_skills = len(self._enemy_skills)
        per_materia = [0, 0, 0, 0]
        any_learned = 0
        all_four_learned = 0
        for skill in self._enemy_skills:
            row = state.enemy_skills_checked.get(str(skill.id), [False, False, False, False])
            flags = [bool(row[i]) if i < len(row) else False for i in range(4)]
            for i in range(4):
                if flags[i]:
                    per_materia[i] += 1
            if any(flags):
                any_learned += 1
            if all(flags):
                all_four_learned += 1
        return {
            "total_skills": total_skills,
            "any_learned": any_learned,
            "all_four_learned": all_four_learned,
            "per_materia": per_materia,
            "materias_obtained": sum(1 for x in state.enemy_skill_materias_obtained[:4] if x),
        }
