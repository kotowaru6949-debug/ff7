"""Drop rate 100% patcher tab UI."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from core.paths import LANG_LABELS, SUPPORTED_LANGS, get_scene_bin_path, is_game_running
from core.scene_patcher import (
    DropPatchConfig,
    PatchStatus,
    ScenePatchError,
    apply_drop_patch,
    get_patch_status,
    restore_vanilla,
)
from core.state_store import ToolState
from ui.theme import PALETTE, get_ui_font

ALL_LANGS_LABEL = "全言語一括 (ja / en / de / es / fr)"

STATE_DISPLAY: dict[str, tuple[str, str]] = {
    "VANILLA": ("バニラ（オリジナル）", PALETTE["accent_blue"]),
    "PATCHED": ("ドロップ率100% 適用中", PALETTE["accent_green"]),
    "UNKNOWN_MODIFIED": ("外部変更あり（またはバックアップ未作成の改変状態）", PALETTE["accent_warn"]),
    "MISSING": ("scene.bin 未検出", PALETTE["accent_red"]),
}


class DropTab(ttk.Frame):
    """Tab for managing 100% drop rate patches on scene.bin."""

    def __init__(
        self,
        parent: ttk.Notebook,
        *,
        get_game_dir: Callable[[], Path | None],
        backup_dir: Path,
        state: ToolState,
        save_state: Callable[[], None],
        set_status: Callable[[str], None],
    ) -> None:
        super().__init__(parent, padding=12)
        self._get_game_dir = get_game_dir
        self._backup_dir = backup_dir
        self._state = state
        self._save_state = save_state
        self._set_status = set_status

        self._lang_options: list[tuple[str, str]] = [
            (code, LANG_LABELS[code]) for code in SUPPORTED_LANGS
        ] + [("__ALL__", ALL_LANGS_LABEL)]
        self._label_to_code = {label: code for code, label in self._lang_options}
        self._code_to_label = {code: label for code, label in self._lang_options}

        initial_label = self._code_to_label.get(
            state.selected_lang, LANG_LABELS["ja"]
        )
        self.lang_var = tk.StringVar(value=initial_label)
        self.rare_first_var = tk.BooleanVar(value=True)
        self.steal_100_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.refresh_status()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # 1. Target Language + Current Status Card
        status_card = ttk.LabelFrame(self, text="対象ファイル & 現在のステータス", padding=10)
        status_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        status_card.columnconfigure(1, weight=1)

        ttk.Label(status_card, text="対象言語:", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        lang_combo = ttk.Combobox(
            status_card,
            textvariable=self.lang_var,
            values=[label for _, label in self._lang_options],
            state="readonly",
            width=36,
        )
        lang_combo.grid(row=0, column=1, sticky="w", pady=4)
        lang_combo.bind("<<ComboboxSelected>>", self._on_lang_changed)

        ttk.Label(status_card, text="状態:", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.badge_label = tk.Label(
            status_card,
            text="確認中...",
            bg=PALETTE["bg_surface"],
            fg=PALETTE["fg_text"],
            font=get_ui_font(10, True),
            padx=10,
            pady=3,
        )
        self.badge_label.grid(row=1, column=1, sticky="w", pady=4)

        self.stats_label = ttk.Label(
            status_card,
            text="",
            style="Panel.TLabel",
            justify="left",
        )
        self.stats_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.backup_label = ttk.Label(
            status_card,
            text=f"バックアップ保存先: {self._backup_dir}",
            style="Muted.TLabel",
            justify="left",
        )
        self.backup_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # 2. Patch Options & Action Buttons
        config_card = ttk.LabelFrame(self, text="パッチ設定 & 操作", padding=10)
        config_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        config_card.columnconfigure(0, weight=1)

        ttk.Radiobutton(
            config_card,
            text="レア優先 100%（推奨） — 複数ドロップ枠がある敵は元の確率が低いレア枠を先頭に配置して100%化",
            variable=self.rare_first_var,
            value=True,
        ).grid(row=0, column=0, sticky="w", pady=3)

        ttk.Radiobutton(
            config_card,
            text="通常順 100% — スロット順を変えず全ドロップ枠を100%化（従来先頭枠が確定ドロップ）",
            variable=self.rare_first_var,
            value=False,
        ).grid(row=1, column=0, sticky="w", pady=3)

        ttk.Checkbutton(
            config_card,
            text="「ぬすむ」成功率も100%にする（任意：盗める敵から1回で必ず盗めます）",
            variable=self.steal_100_var,
        ).grid(row=2, column=0, sticky="w", pady=(6, 10))

        btn_row = ttk.Frame(config_card, style="Panel.TFrame")
        btn_row.grid(row=3, column=0, sticky="w")

        self.apply_btn = ttk.Button(
            btn_row,
            text="ドロップ率100%を適用",
            style="Primary.TButton",
            command=self._on_apply,
        )
        self.apply_btn.pack(side="left", padx=(0, 8))

        self.restore_btn = ttk.Button(
            btn_row,
            text="バニラ（元の状態）に復元",
            style="Danger.TButton",
            command=self._on_restore,
        )
        self.restore_btn.pack(side="left", padx=(0, 8))

        ttk.Button(
            btn_row,
            text="状態を再読み込み",
            command=self.refresh_status,
        ).pack(side="left")

        # 3. Important FF7 Mechanics Notice
        note_card = ttk.LabelFrame(self, text="FF7 仕様上の注意", padding=10)
        note_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        note_text = (
            "• 初回適用時にオリジナルの scene.bin を自動バックアップします。設定変更時も必ずオリジナルから再生成するため安全です。\n"
            "• 敵1体が複数種類のドロップアイテムを持つ場合、FF7では先頭スロットから順に判定して最初に当選した1個だけ落とします。\n"
            "• 原作仕様上、「ぬすむ」で既に盗んだ敵や「へんか」で倒した敵は戦闘終了時にアイテムをドロップしません。\n"
            "• 適用・復元は必ずゲーム（FFVII.exe）を終了した状態で行ってください。"
        )
        ttk.Label(note_card, text=note_text, style="Muted.TLabel", justify="left").pack(
            anchor="w"
        )

        # 4. Operation Log
        log_card = ttk.LabelFrame(self, text="操作ログ", padding=8)
        log_card.grid(row=3, column=0, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_card,
            height=6,
            bg=PALETTE["bg_input"],
            fg=PALETTE["fg_text"],
            insertbackground=PALETTE["fg_text"],
            relief="flat",
            font=get_ui_font(9),
            wrap="word",
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_card, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def _selected_langs(self) -> list[str]:
        code = self._label_to_code.get(self.lang_var.get(), "ja")
        if code == "__ALL__":
            return list(SUPPORTED_LANGS)
        return [code]

    def _on_lang_changed(self, _event: tk.Event | None = None) -> None:
        code = self._label_to_code.get(self.lang_var.get(), "ja")
        if code in SUPPORTED_LANGS:
            self._state.selected_lang = code
            self._save_state()
        self.refresh_status()

    def _append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def refresh_status(self) -> None:
        game_dir = self._get_game_dir()
        if game_dir is None:
            self.badge_label.configure(
                text="ゲームフォルダ未検出",
                bg=PALETTE["accent_red_dark"],
                fg="#FFFFFF",
            )
            self.stats_label.configure(
                text="上部の「フォルダ選択...」から FINAL FANTASY VII Steam Edition のフォルダを指定してください。"
            )
            self.apply_btn.configure(state="disabled")
            self.restore_btn.configure(state="disabled")
            return

        langs = self._selected_langs()
        statuses: list[tuple[str, PatchStatus]] = []
        for lang in langs:
            scene_path = get_scene_bin_path(game_dir, lang)
            try:
                st = get_patch_status(scene_path, self._backup_dir, lang)
            except ScenePatchError as exc:
                self.badge_label.configure(
                    text="読み込みエラー",
                    bg=PALETTE["accent_red_dark"],
                    fg="#FFFFFF",
                )
                self.stats_label.configure(text=str(exc))
                self.apply_btn.configure(state="disabled")
                self.restore_btn.configure(state="disabled")
                return
            statuses.append((lang, st))

        if len(statuses) == 1:
            lang, st = statuses[0]
            label_text, color = STATE_DISPLAY.get(st.state, (st.state, PALETTE["bg_surface"]))
            if st.state == "PATCHED" and st.applied_config:
                mode_str = "レア優先" if st.applied_config.rare_first else "通常順"
                steal_str = " + ぬすむ100%" if st.applied_config.steal_100 else ""
                label_text = f"{label_text}（{mode_str}{steal_str}）"

            self.badge_label.configure(text=label_text, bg=color, fg="#FFFFFF")

            if st.stats:
                backup_info = (
                    f"あり (orig SHA-256: {st.backup_sha256[:12]}...)"
                    if st.has_backup and st.backup_sha256
                    else "未作成（初回適用時に自動作成）"
                )
                self.stats_label.configure(
                    text=(
                        f"対象: {st.scene_path}\n"
                        f"構造: {st.stats.block_count} ブロック / {st.stats.scene_count} シーン / 敵枠 {st.stats.enemy_slot_count}\n"
                        f"ドロップ枠: {st.stats.drop_slot_count}（100%未満: {st.stats.non_max_drop_slot_count}） / "
                        f"複数ドロップ持ち敵: {st.stats.multi_drop_enemy_count} / 盗み枠: {st.stats.steal_slot_count}（100%未満: {st.stats.non_max_steal_slot_count}）\n"
                        f"バックアップ: {backup_info}"
                    )
                )
            else:
                self.stats_label.configure(text=f"ファイルが見つかりません: {st.scene_path}")

            self.apply_btn.configure(state="normal" if st.exists else "disabled")
            self.restore_btn.configure(state="normal" if (st.exists and st.has_backup) else "disabled")
        else:
            existing = [(lang, st) for lang, st in statuses if st.exists]
            patched_cnt = sum(1 for _, st in existing if st.state == "PATCHED")
            vanilla_cnt = sum(1 for _, st in existing if st.state == "VANILLA")
            backup_cnt = sum(1 for _, st in existing if st.has_backup)
            if patched_cnt == len(existing) and existing:
                badge_text, color = f"全{len(existing)}言語 適用中", PALETTE["accent_green"]
            elif vanilla_cnt == len(existing) and existing:
                badge_text, color = f"全{len(existing)}言語 バニラ状態", PALETTE["accent_blue"]
            else:
                badge_text, color = f"混在状態（適用:{patched_cnt} / バニラ:{vanilla_cnt}）", PALETTE["accent_warn"]

            self.badge_label.configure(text=badge_text, bg=color, fg="#FFFFFF")
            lines = []
            for lang, st in statuses:
                st_label = STATE_DISPLAY.get(st.state, (st.state, ""))[0]
                bk = "BK有" if st.has_backup else "BK無"
                lines.append(f"lang-{lang}: {st_label} [{bk}]")
            self.stats_label.configure(text=" / ".join(lines))
            self.apply_btn.configure(state="normal" if existing else "disabled")
            self.restore_btn.configure(state="normal" if backup_cnt > 0 else "disabled")

    def _guard_game_not_running(self) -> bool:
        if is_game_running():
            messagebox.showwarning(
                "FFVII 起動中",
                "現在 FFVII.exe が起動中です。\n安全のためゲームを完全に終了してから再実行してください。",
                parent=self,
            )
            return False
        return True

    def _on_apply(self) -> None:
        game_dir = self._get_game_dir()
        if game_dir is None:
            messagebox.showerror("エラー", "ゲームフォルダが設定されていません。", parent=self)
            return
        if not self._guard_game_not_running():
            return

        config = DropPatchConfig(
            drop_100=True,
            rare_first=bool(self.rare_first_var.get()),
            steal_100=bool(self.steal_100_var.get()),
        )

        langs = self._selected_langs()
        succeeded: list[str] = []
        errors: list[str] = []
        for lang in langs:
            scene_path = get_scene_bin_path(game_dir, lang)
            if not scene_path.is_file():
                errors.append(f"lang-{lang}: ファイル未検出")
                continue
            try:
                apply_drop_patch(scene_path, self._backup_dir, lang, config)
                succeeded.append(lang)
                mode_desc = "レア優先100%" if config.rare_first else "通常順100%"
                steal_desc = "・ぬすむ100%" if config.steal_100 else ""
                self._append_log(f"lang-{lang} にパッチを適用しました（{mode_desc}{steal_desc}）。")
            except Exception as exc:
                errors.append(f"lang-{lang}: {exc}")
                self._append_log(f"[ERROR] lang-{lang} 適用失敗: {exc}")

        self.refresh_status()
        if errors:
            messagebox.showerror(
                "一部またはすべて失敗",
                "\n".join(errors),
                parent=self,
            )
        elif succeeded:
            self._set_status(f"ドロップ率100%を適用しました: {', '.join(succeeded)}")
            messagebox.showinfo(
                "適用完了",
                f"ドロップ率100%パッチの適用が完了しました（対象: {', '.join(succeeded)}）。\n"
                "オリジナルバックアップも安全に保存されています。",
                parent=self,
            )

    def _on_restore(self) -> None:
        game_dir = self._get_game_dir()
        if game_dir is None:
            return
        if not self._guard_game_not_running():
            return

        langs = self._selected_langs()
        if not messagebox.askyesno(
            "バニラへ復元",
            "バックアップ済みのオリジナル scene.bin へ復元しますか？",
            parent=self,
        ):
            return

        restored: list[str] = []
        errors: list[str] = []
        for lang in langs:
            scene_path = get_scene_bin_path(game_dir, lang)
            orig_path = self._backup_dir / f"lang-{lang}_scene.bin.orig"
            if not orig_path.is_file():
                if len(langs) == 1:
                    errors.append(f"lang-{lang}: バックアップが見つかりません。")
                continue
            try:
                restore_vanilla(scene_path, self._backup_dir, lang)
                restored.append(lang)
                self._append_log(f"lang-{lang} をバニラ状態に復元しました（SHA-256検証OK）。")
            except Exception as exc:
                errors.append(f"lang-{lang}: {exc}")
                self._append_log(f"[ERROR] lang-{lang} 復元失敗: {exc}")

        self.refresh_status()
        if errors:
            messagebox.showerror("復元エラー", "\n".join(errors), parent=self)
        elif restored:
            self._set_status(f"バニラに復元しました: {', '.join(restored)}")
            messagebox.showinfo(
                "復元完了",
                f"オリジナルの状態に復元しました（対象: {', '.join(restored)}）。",
                parent=self,
            )
