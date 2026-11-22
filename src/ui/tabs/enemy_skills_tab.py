"""Enemy Skill (24 skills x 4 materias) tracker tab."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from companion.repository import CompanionRepository, EnemySkillItem
from core.state_store import ToolState
from ui.theme import PALETTE, get_ui_font


class EnemySkillsTab(ttk.Frame):
    """Tab for tracking all 24 Enemy Skills across all 4 Enemy Skill Materias."""

    def __init__(
        self,
        parent: ttk.Notebook,
        *,
        repo: CompanionRepository,
        state: ToolState,
        save_state: Callable[[], None],
        set_status: Callable[[str], None],
    ) -> None:
        super().__init__(parent, padding=12)
        self._repo = repo
        self._state = state
        self._save_state = save_state
        self._set_status = set_status

        self._skills_by_id: dict[str, EnemySkillItem] = {
            str(skill.id): skill for skill in repo.enemy_skills
        }
        self._selected_skill_id: str | None = None

        self.materia_vars = [
            tk.BooleanVar(
                value=state.enemy_skill_materias_obtained[i]
                if i < len(state.enemy_skill_materias_obtained)
                else False
            )
            for i in range(4)
        ]
        self.skill_slot_vars = [tk.BooleanVar(value=False) for _ in range(4)]

        self.mode_var = tk.StringVar(value="すべて")
        self.search_var = tk.StringVar(value="")

        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # 1. Obtained Enemy Skill Materias Bar
        mat_frame = ttk.LabelFrame(self, text="「てきのわざ」マテリア 4個の入手状況", padding=8)
        mat_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        for idx, info in enumerate(self._repo.materias):
            cb = ttk.Checkbutton(
                mat_frame,
                text=info.label,
                variable=self.materia_vars[idx],
                command=lambda i=idx: self._on_materia_toggled(i),
            )
            cb.grid(row=0, column=idx, sticky="w", padx=(0, 14))

        loc_hint = " ／ ".join(f"{m.label}: {m.location}" for m in self._repo.materias)
        ttk.Label(mat_frame, text=loc_hint, style="Muted.TLabel", wraplength=980).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )

        # 2. Filter & Summary Row
        filter_frame = ttk.Frame(self)
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        filter_frame.columnconfigure(4, weight=1)

        ttk.Label(filter_frame, text="表示:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        mode_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.mode_var,
            values=["すべて", "未習得あり", "期間限定のみ"],
            state="readonly",
            width=14,
        )
        mode_combo.grid(row=0, column=1, sticky="w", padx=(0, 12))
        mode_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())

        ttk.Label(filter_frame, text="検索:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        search_entry = ttk.Entry(filter_frame, textvariable=self.search_var, width=24)
        search_entry.grid(row=0, column=3, sticky="w", padx=(0, 12))
        search_entry.bind("<KeyRelease>", lambda _e: self.refresh_table())

        self.summary_label = ttk.Label(
            filter_frame,
            text="",
            font=get_ui_font(9, True),
            foreground=PALETTE["accent_green"],
        )
        self.summary_label.grid(row=0, column=4, sticky="e")

        # 3. 24-Skill Treeview
        table_frame = ttk.Frame(self)
        table_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        cols = ("no", "name", "mp", "cat", "missable", "m1", "m2", "m3", "m4", "enemies")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        headings = [
            ("no", "No.", 42, "center"),
            ("name", "技名", 190, "w"),
            ("mp", "MP", 46, "center"),
            ("cat", "分類", 105, "w"),
            ("missable", "限定", 54, "center"),
            ("m1", "①", 36, "center"),
            ("m2", "②", 36, "center"),
            ("m3", "③", 36, "center"),
            ("m4", "④", 36, "center"),
            ("enemies", "主な習得敵・場所", 320, "w"),
        ]
        for col, text, width, anchor in headings:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "enemies"))

        self.tree.tag_configure("missable", background=PALETTE["row_missable"], foreground="#FCA5A5")
        self.tree.tag_configure("complete", foreground=PALETTE["accent_green"])
        self.tree.tag_configure("normal", foreground=PALETTE["fg_text"])

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # 4. Selected Skill Details & Per-Materia Checkboxes
        detail_card = ttk.LabelFrame(self, text="選択中の「てきのわざ」詳細 & マテリア別習得チェック", padding=10)
        detail_card.grid(row=3, column=0, sticky="ew")
        detail_card.columnconfigure(0, weight=1)

        self.skill_title_label = ttk.Label(
            detail_card,
            text="上の表から技を選択してください",
            style="Panel.TLabel",
            font=get_ui_font(11, True),
        )
        self.skill_title_label.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.skill_info_label = ttk.Label(
            detail_card,
            text="",
            style="Panel.TLabel",
            wraplength=960,
            justify="left",
        )
        self.skill_info_label.grid(row=1, column=0, sticky="w", pady=(0, 4))

        self.skill_warn_label = ttk.Label(
            detail_card,
            text="",
            style="Warn.TLabel",
            wraplength=960,
            justify="left",
        )
        self.skill_warn_label.grid(row=2, column=0, sticky="w", pady=(0, 8))

        check_row = ttk.Frame(detail_card, style="Panel.TFrame")
        check_row.grid(row=3, column=0, sticky="w")

        for idx in range(4):
            ttk.Checkbutton(
                check_row,
                text=f"マテリア{['①','②','③','④'][idx]}",
                variable=self.skill_slot_vars[idx],
                command=self._on_skill_slot_changed,
            ).pack(side="left", padx=(0, 12))

        ttk.Button(
            check_row,
            text="4つすべてON",
            style="Success.TButton",
            command=lambda: self._set_all_slots(True),
        ).pack(side="left", padx=(8, 6))

        ttk.Button(
            check_row,
            text="4つすべてOFF",
            command=lambda: self._set_all_slots(False),
        ).pack(side="left")

    def refresh_table(self, preserve_id: str | None = None) -> None:
        target_id = preserve_id or self._selected_skill_id
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        skills = self._repo.filter_enemy_skills(
            self._state,
            mode=self.mode_var.get(),
            query=self.search_var.get(),
        )

        for skill in skills:
            sid = str(skill.id)
            row = self._state.enemy_skills_checked.get(sid, [False, False, False, False])
            marks = ["●" if (i < len(row) and row[i]) else "・" for i in range(4)]
            miss_label = "限定!" if skill.missable else "-"
            if skill.missable and not all(row[:4]):
                tag = "missable"
            elif all(row[:4]):
                tag = "complete"
            else:
                tag = "normal"

            self.tree.insert(
                "",
                "end",
                iid=sid,
                values=(
                    f"{skill.id:02d}",
                    skill.name,
                    skill.mp,
                    skill.category,
                    miss_label,
                    marks[0],
                    marks[1],
                    marks[2],
                    marks[3],
                    skill.enemies,
                ),
                tags=(tag,),
            )

        summary = self._repo.summarize_enemy_skills(self._state)
        pm = summary["per_materia"]
        self.summary_label.configure(
            text=(
                f"いずれか習得: {summary['any_learned']}/{summary['total_skills']} ｜ "
                f"全4個コンプ: {summary['all_four_learned']}/{summary['total_skills']} ｜ "
                f"①:{pm[0]} ②:{pm[1]} ③:{pm[2]} ④:{pm[3]}"
            )
        )

        children = self.tree.get_children()
        if target_id and target_id in children:
            self.tree.selection_set(target_id)
            self.tree.see(target_id)
            self._render_skill_detail(target_id)
        elif children:
            self.tree.selection_set(children[0])
            self._render_skill_detail(children[0])

    def _render_skill_detail(self, sid: str) -> None:
        skill = self._skills_by_id.get(sid)
        if skill is None:
            return
        self._selected_skill_id = sid

        manip_tag = "【あやつる必須】" if skill.manipulate_required else "【自発／あやつる可】"
        self.skill_title_label.configure(
            text=f"No.{skill.id:02d} {skill.name}  (MP {skill.mp} / {skill.category})  {manip_tag}"
        )
        self.skill_info_label.configure(
            text=(
                f"効果: {skill.effect}\n"
                f"習得敵: {skill.enemies}\n"
                f"ラーニング解説: {skill.manipulate_note}"
            )
        )
        if skill.missable:
            self.skill_warn_label.configure(text=skill.missable_note)
        else:
            self.skill_warn_label.configure(text="")

        row = self._state.enemy_skills_checked.get(sid, [False, False, False, False])
        for i in range(4):
            self.skill_slot_vars[i].set(bool(row[i]) if i < len(row) else False)

    def _on_select(self, _event: tk.Event | None = None) -> None:
        sel = self.tree.selection()
        if sel:
            self._render_skill_detail(sel[0])

    def _on_materia_toggled(self, idx: int) -> None:
        self._state.enemy_skill_materias_obtained[idx] = bool(self.materia_vars[idx].get())
        self._save_state()
        self._set_status(f"てきのわざマテリア {idx + 1}個目の入手状況を保存しました。")

    def _on_skill_slot_changed(self) -> None:
        if not self._selected_skill_id:
            return
        self._state.enemy_skills_checked[self._selected_skill_id] = [
            bool(var.get()) for var in self.skill_slot_vars
        ]
        self._save_state()
        self.refresh_table(preserve_id=self._selected_skill_id)
        self._set_status("てきのわざ習得状況を保存しました。")

    def _set_all_slots(self, value: bool) -> None:
        if not self._selected_skill_id:
            return
        for var in self.skill_slot_vars:
            var.set(value)
        self._on_skill_slot_changed()
