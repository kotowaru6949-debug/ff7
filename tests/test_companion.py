"""Unit tests for FF7 companion data, repository filtering, and state persistence."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from companion.repository import CompanionRepository  # noqa: E402
from core.state_store import StateStore, ToolState  # noqa: E402


class TestCompanionDataAndRepo(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = CompanionRepository()

    def test_missables_schema_and_integrity(self) -> None:
        items = self.repo.missables
        self.assertGreaterEqual(len(items), 35)
        ids = [item.id for item in items]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate missable IDs found")
        orders = [item.order for item in items]
        self.assertEqual(orders, sorted(orders))
        for item in items:
            self.assertIn(item.disc, ("Disc 1", "Disc 2", "Disc 3"))
            self.assertTrue(item.name.strip())
            self.assertTrue(item.area.strip())
            self.assertTrue(item.how_to_get.strip())
            self.assertTrue(item.deadline.strip())

    def test_enemy_skills_schema_and_missables(self) -> None:
        self.assertEqual(len(self.repo.materias), 4)
        self.assertEqual([m.slot for m in self.repo.materias], [1, 2, 3, 4])

        skills = self.repo.enemy_skills
        self.assertEqual(len(skills), 24)
        self.assertEqual([s.id for s in skills], list(range(1, 25)))

        missables_by_id = {s.id: s for s in skills if s.missable}
        self.assertIn(15, missables_by_id)  # トライン
        self.assertIn(24, missables_by_id)  # パンドラボックス / なんとか？？？？
        for s in missables_by_id.values():
            self.assertTrue(s.missable_note.strip())

    def test_filtering_and_summaries(self) -> None:
        state = ToolState()
        first_id = self.repo.missables[0].id
        state.missables_checked[first_id] = True
        state.enemy_skills_checked["1"] = [True, True, False, False]
        state.enemy_skills_checked["15"] = [True, True, True, True]
        state.enemy_skill_materias_obtained = [True, True, False, False]

        disc1 = self.repo.filter_missables(state, disc="Disc 1")
        self.assertTrue(all(m.disc == "Disc 1" for m in disc1))

        unchecked = self.repo.filter_missables(state, only_unchecked=True)
        self.assertNotIn(first_id, [m.id for m in unchecked])

        witem = self.repo.filter_missables(state, query="Wアイテム")
        self.assertEqual(len(witem), 1)

        m_summary = self.repo.summarize_missables(state)
        self.assertEqual(m_summary["completed"], 1)
        self.assertEqual(m_summary["total"], len(self.repo.missables))

        missable_skills = self.repo.filter_enemy_skills(state, mode="期間限定のみ")
        self.assertEqual([s.id for s in missable_skills], [15, 24])

        unlearned = self.repo.filter_enemy_skills(state, mode="未習得あり")
        self.assertNotIn(15, [s.id for s in unlearned])
        self.assertIn(1, [s.id for s in unlearned])

        e_summary = self.repo.summarize_enemy_skills(state)
        self.assertEqual(e_summary["any_learned"], 2)
        self.assertEqual(e_summary["all_four_learned"], 1)
        self.assertEqual(e_summary["per_materia"], [2, 2, 1, 1])
        self.assertEqual(e_summary["materias_obtained"], 2)


class TestStateStore(unittest.TestCase):
    def test_save_and_reload_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "user_data" / "state.json")
            state = store.load()
            self.assertEqual(state.selected_lang, "ja")
            self.assertEqual(state.enemy_skill_materias_obtained, [False, False, False, False])

            state.game_dir = r"C:\Games\FF7"
            state.selected_lang = "en"
            state.missables_checked["d1_shinra_68f_enemy_skill_1"] = True
            state.missables_notes["d1_shinra_68f_enemy_skill_1"] = "取得メモ"
            state.enemy_skills_checked["24"] = [True, True, True, True]
            state.enemy_skill_materias_obtained = [True, False, True, False]
            store.save(state)

            reloaded = store.load()
            self.assertEqual(reloaded.game_dir, r"C:\Games\FF7")
            self.assertEqual(reloaded.selected_lang, "en")
            self.assertTrue(reloaded.missables_checked["d1_shinra_68f_enemy_skill_1"])
            self.assertEqual(reloaded.missables_notes["d1_shinra_68f_enemy_skill_1"], "取得メモ")
            self.assertEqual(reloaded.enemy_skills_checked["24"], [True, True, True, True])
            self.assertEqual(reloaded.enemy_skill_materias_obtained, [True, False, True, False])


if __name__ == "__main__":
    unittest.main()
