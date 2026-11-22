"""Missable items and events companion tab."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from companion.repository import CompanionRepository, MissableItem
from core.state_store import ToolState
from ui.theme import PALETTE, get_ui_font


class MissablesTab(ttk.Frame):
    """Tab displaying FF7 missable items/events checklist with detail view and notes."""

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

        self._items_by_id: dict[str, MissableItem] = {m.id: m for m in repo.missables}
        self._selected_id: str | None = None
        self._suppress_note_save = False

        self.disc_var = tk.StringVar(value="すべて")
        self.cat_var = tk.StringVar(value="すべて")
        self.only_unchecked_var = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar(value="")
        self.checked_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.refresh_list()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # 1. Filter Bar
        filter_frame = ttk.LabelFrame(self, text="絞り込み・検索", padding=8)
        filter_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(filter_frame, text="Disc:", style="Panel.TLabel").pack(side="left", padx=(0, 4))
        disc_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.disc_var,
            values=["すべて", "Disc 1", "Disc 2", "Disc 3"],
            state="readonly",
            width=10,
        )
        disc_combo.pack(side="left", padx=(0, 12))
        disc_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_list())

        ttk.Label(filter_frame, text="カテゴリ:", style="Panel.TLabel").pack(side="left", padx=(0, 4))
        cat_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.cat_var,
            values=["すべて"] + self._repo.get_missable_categories(),
            state="readonly",
            width=14,
        )
        cat_combo.pack(side="left", padx=(0, 12))
        cat_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_list())

        ttk.Label(filter_frame, text="検索:", style="Panel.TLabel").pack(side="left", padx=(0, 4))
        search_entry = ttk.Entry(filter_frame, textvariable=self.search_var, width=26)
        search_entry.pack(side="left", padx=(0, 12))
        search_entry.bind("<KeyRelease>", lambda _e: self.refresh_list())

        ttk.Checkbutton(
            filter_frame,
            text="未取得のみ表示",
            variable=self.only_unchecked_var,
            command=self.refresh_list,
        ).pack(side="left")

        # 2. Progress Summary
        prog_frame = ttk.Frame(self)
        prog_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        prog_frame.columnconfigure(1, weight=1)

        self.progress_label = ttk.Label(prog_frame, text="達成状況: 0 / 0 (0.0%)", font=get_ui_font(10, True))
        self.progress_label.grid(row=0, column=0, sticky="w", padx=(0, 12))

        self.progress_bar = ttk.Progressbar(prog_frame, mode="determinate", maximum=100)
        self.progress_bar.grid(row=0, column=1, sticky="ew")

        # 3. Main Paned Split (Treeview left, Details right)
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.grid(row=2, column=0, sticky="nsew")

        left_frame = ttk.Frame(paned, padding=(0, 0, 6, 0))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)
        paned.add(left_frame, weight=3)

        columns = ("done", "disc", "priority", "name", "area")
        self.tree = ttk.Treeview(left_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("done", text="済")
        self.tree.heading("disc", text="Disc")
        self.tree.heading("priority", text="重要度")
        self.tree.heading("name", text="名称")
        self.tree.heading("area", text="場所・エリア")

        self.tree.column("done", width=40, anchor="center", stretch=False)
        self.tree.column("disc", width=65, anchor="center", stretch=False)
        self.tree.column("priority", width=70, anchor="center", stretch=False)
        self.tree.column("name", width=270, anchor="w")
        self.tree.column("area", width=180, anchor="w")

        self.tree.tag_configure("checked", foreground=PALETTE["fg_muted"])
        self.tree.tag_configure("top_priority", foreground="#FDE68A")
        self.tree.tag_configure("normal", foreground=PALETTE["fg_text"])

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self._toggle_selected())
        self.tree.bind("<space>", lambda _e: self._toggle_selected())
        self.tree.bind("<Return>", lambda _e: self._toggle_selected())

        # Right Detail Panel
        right_frame = ttk.LabelFrame(paned, text="詳細・取り逃し期限", padding=10)
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(5, weight=1)
        paned.add(right_frame, weight=2)

        self.detail_title = ttk.Label(
            right_frame,
            text="左のリストから項目を選択してください",
            style="Panel.TLabel",
            font=get_ui_font(11, True),
            wraplength=360,
        )
        self.detail_title.grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.detail_meta = ttk.Label(
            right_frame,
            text="",
            style="Muted.TLabel",
            wraplength=360,
        )
        self.detail_meta.grid(row=1, column=0, sticky="w", pady=(0, 8))

        self.detail_how = ttk.Label(
            right_frame,
            text="",
            style="Panel.TLabel",
            wraplength=360,
            justify="left",
        )
        self.detail_how.grid(row=2, column=0, sticky="w", pady=(0, 10))

        self.detail_deadline = ttk.Label(
            right_frame,
            text="",
            style="Warn.TLabel",
            wraplength=360,
            justify="left",
        )
        self.detail_deadline.grid(row=3, column=0, sticky="w", pady=(0, 12))

        toggle_row = ttk.Frame(right_frame, style="Panel.TFrame")
        toggle_row.grid(row=4, column=0, sticky="ew", pady=(0, 10))

        self.check_btn = ttk.Checkbutton(
            toggle_row,
            text="取得・達成済みとしてチェックする（ダブルクリック/Spaceでも切替可）",
            variable=self.checked_var,
            command=self._on_check_clicked,
        )
        self.check_btn.pack(anchor="w")

        note_box = ttk.LabelFrame(right_frame, text="自分用メモ（自動保存）", padding=6)
        note_box.grid(row=5, column=0, sticky="nsew")
        note_box.columnconfigure(0, weight=1)
        note_box.rowconfigure(0, weight=1)

        self.note_text = tk.Text(
            note_box,
            height=5,
            bg=PALETTE["bg_input"],
            fg=PALETTE["fg_text"],
            insertbackground=PALETTE["fg_text"],
            relief="flat",
            font=get_ui_font(9),
            wrap="word",
        )
        self.note_text.grid(row=0, column=0, sticky="nsew")
        self.note_text.bind("<FocusOut>", lambda _e: self._save_current_note())

        ttk.Button(
            right_frame,
            text="メモを保存",
            command=self._save_current_note,
        ).grid(row=6, column=0, sticky="e", pady=(6, 0))

    def refresh_list(self, preserve_selection: str | None = None) -> None:
        target_id = preserve_selection or self._selected_id
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        items = self._repo.filter_missables(
            self._state,
            disc=self.disc_var.get(),
            category=self.cat_var.get(),
            only_unchecked=bool(self.only_unchecked_var.get()),
            query=self.search_var.get(),
        )

        for item in items:
            checked = self._state.missables_checked.get(item.id, False)
            mark = "☑" if checked else "☐"
            if checked:
                tag = "checked"
            elif item.priority == "最重要":
                tag = "top_priority"
            else:
                tag = "normal"
            self.tree.insert(
                "",
                "end",
                iid=item.id,
                values=(mark, item.disc, item.priority, item.name, item.area),
                tags=(tag,),
            )

        summary = self._repo.summarize_missables(self._state)
        self.progress_label.configure(
            text=f"達成状況: {summary['completed']} / {summary['total']} ({summary['percent']:.1f}%)"
        )
        self.progress_bar["value"] = summary["percent"]

        children = self.tree.get_children()
        if target_id and target_id in children:
            self.tree.selection_set(target_id)
            self.tree.see(target_id)
            self._render_detail(target_id)
        elif children:
            self.tree.selection_set(children[0])
            self._render_detail(children[0])
        else:
            self._selected_id = None
            self.detail_title.configure(text="条件に一致する項目はありません")
            self.detail_meta.configure(text="")
            self.detail_how.configure(text="")
            self.detail_deadline.configure(text="")
            self.checked_var.set(False)
            self._set_note_content("")

    def _set_note_content(self, text: str) -> None:
        self._suppress_note_save = True
        self.note_text.delete("1.0", "end")
        if text:
            self.note_text.insert("1.0", text)
        self._suppress_note_save = False

    def _save_current_note(self) -> None:
        if self._suppress_note_save or not self._selected_id:
            return
        content = self.note_text.get("1.0", "end-1c").strip()
        if content:
            self._state.missables_notes[self._selected_id] = content
        else:
            self._state.missables_notes.pop(self._selected_id, None)
        self._save_state()
        self._set_status("取り逃しメモを保存しました。")

    def _render_detail(self, item_id: str) -> None:
        item = self._items_by_id.get(item_id)
        if item is None:
            return
        self._selected_id = item_id
        self.detail_title.configure(text=item.name)
        self.detail_meta.configure(
            text=f"[{item.disc}] {item.area} ｜ カテゴリ: {item.category} ｜ 重要度: {item.priority}"
        )
        self.detail_how.configure(text=f"【入手・達成方法】\n{item.how_to_get}")
        self.detail_deadline.configure(text=f"【取り返し期限】\n{item.deadline}")
        self.checked_var.set(self._state.missables_checked.get(item.id, False))
        self._set_note_content(self._state.missables_notes.get(item.id, ""))

    def _on_select(self, _event: tk.Event | None = None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        new_id = sel[0]
        if self._selected_id and self._selected_id != new_id:
            self._save_current_note()
        self._render_detail(new_id)

    def _on_check_clicked(self) -> None:
        if not self._selected_id:
            return
        self._state.missables_checked[self._selected_id] = bool(self.checked_var.get())
        self._save_state()
        self.refresh_list(preserve_selection=self._selected_id)
        self._set_status("取り逃しチェックを更新しました。")

    def _toggle_selected(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        item_id = sel[0]
        current = self._state.missables_checked.get(item_id, False)
        self._state.missables_checked[item_id] = not current
        self._save_state()
        self.refresh_list(preserve_selection=item_id)
        self._set_status("取り逃しチェックを更新しました。")
        return "break"
