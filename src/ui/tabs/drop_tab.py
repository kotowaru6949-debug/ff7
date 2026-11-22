"""Drop rate 100% & EXP/AP/Gil multiplier patcher tab UI."""

from __future__ import annotations

import math
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from core.paths import (
    LANG_LABELS,
    SUPPORTED_LANGS,
    get_kernel_bin_path,
    get_scene_bin_path,
    is_game_running,
)
from core.scene_patcher import (
    MAX_MULTIPLIER,
    MAX_SAFE_AP,
    MAX_SAFE_EXP,
    MAX_SAFE_GIL,
    MIN_MULTIPLIER,
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
    "PATCHED": ("パッチ適用中", PALETTE["accent_green"]),
    "UNKNOWN_MODIFIED": ("外部変更あり（またはバックアップ未作成の改変状態）", PALETTE["accent_warn"]),
    "MISSING": ("scene.bin 未検出", PALETTE["accent_red"]),
}

QUICK_MULTIPLIERS: tuple[tuple[str, float], ...] = (
    ("0x", 0.0),
    ("0.5x", 0.5),
    ("1x", 1.0),
    ("2x", 2.0),
    ("3x", 3.0),
    ("5x", 5.0),
    ("10x", 10.0),
)

ALL_PRESETS: tuple[tuple[str, float], ...] = (
    ("すべて 1x", 1.0),
    ("快適 2x", 2.0),
    ("サクサク 3x", 3.0),
    ("高速 5x", 5.0),
    ("爆速 10x", 10.0),
)


def _fmt_mult(val: float) -> str:
    if abs(val - round(val)) < 1e-6:
        return str(int(round(val)))
    return f"{val:.2f}".rstrip("0").rstrip(".")


def _summarize_config(cfg: DropPatchConfig) -> str:
    parts: list[str] = []
    if cfg.drop_100:
        parts.append("ドロップ100%[レア優先]" if cfg.rare_first else "ドロップ100%[通常順]")
    if cfg.steal_100:
        parts.append("ぬすむ100%")
    if abs(cfg.exp_multiplier - 1.0) >= 1e-9:
        parts.append(f"EXP x{_fmt_mult(cfg.exp_multiplier)}")
    if abs(cfg.ap_multiplier - 1.0) >= 1e-9:
        parts.append(f"AP x{_fmt_mult(cfg.ap_multiplier)}")
    if abs(cfg.gil_multiplier - 1.0) >= 1e-9:
        parts.append(f"ギル x{_fmt_mult(cfg.gil_multiplier)}")
    return " / ".join(parts) if parts else "標準設定"


class DropTab(ttk.Frame):
    """Tab for managing 100% drops, steal rates, and EXP/AP/Gil multipliers."""

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
        super().__init__(parent, padding=10)
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

        initial_label = self._code_to_label.get(state.selected_lang, LANG_LABELS["ja"])
        self.lang_var = tk.StringVar(value=initial_label)
        self.drop_100_var = tk.BooleanVar(value=state.patch_drop_100)
        self.rare_first_var = tk.BooleanVar(value=state.patch_rare_first)
        self.steal_100_var = tk.BooleanVar(value=state.patch_steal_100)
        self.exp_mult_var = tk.StringVar(value=_fmt_mult(state.patch_exp_mult))
        self.ap_mult_var = tk.StringVar(value=_fmt_mult(state.patch_ap_mult))
        self.gil_mult_var = tk.StringVar(value=_fmt_mult(state.patch_gil_mult))

        self._rare_radios: list[ttk.Radiobutton] = []

        self._build_ui()
        self._on_drop_toggle()
        self._update_preview()
        self.refresh_status()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        # 1. Target Language + Current Status Card
        status_card = ttk.LabelFrame(self, text="対象ファイル & 現在のステータス", padding=8)
        status_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        status_card.columnconfigure(1, weight=1)

        ttk.Label(status_card, text="対象言語:", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=2
        )
        lang_combo = ttk.Combobox(
            status_card,
            textvariable=self.lang_var,
            values=[label for _, label in self._lang_options],
            state="readonly",
            width=36,
        )
        lang_combo.grid(row=0, column=1, sticky="w", pady=2)
        lang_combo.bind("<<ComboboxSelected>>", self._on_lang_changed)

        ttk.Label(status_card, text="状態:", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=2
        )
        self.badge_label = tk.Label(
            status_card,
            text="確認中...",
            bg=PALETTE["bg_surface"],
            fg=PALETTE["fg_text"],
            font=get_ui_font(10, True),
            padx=10,
            pady=2,
        )
        self.badge_label.grid(row=1, column=1, sticky="w", pady=2)

        self.stats_label = ttk.Label(
            status_card,
            text="",
            style="Panel.TLabel",
            justify="left",
        )
        self.stats_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.backup_label = ttk.Label(
            status_card,
            text=f"バックアップ保存先: {self._backup_dir}",
            style="Muted.TLabel",
            justify="left",
        )
        self.backup_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # 2. Drop & Steal Options Card
        drop_card = ttk.LabelFrame(self, text="ドロップ率・ぬすむ設定", padding=8)
        drop_card.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        drop_card.columnconfigure(0, weight=1)

        ttk.Checkbutton(
            drop_card,
            text="アイテムドロップ率を100%にする",
            variable=self.drop_100_var,
            command=self._on_drop_toggle,
        ).grid(row=0, column=0, sticky="w", pady=2)

        radio_rare = ttk.Radiobutton(
            drop_card,
            text="レア優先 100%（推奨） — 複数ドロップ枠がある敵は低確率レア枠を先頭に配置して100%化",
            variable=self.rare_first_var,
            value=True,
        )
        radio_rare.grid(row=1, column=0, sticky="w", padx=(18, 0), pady=2)

        radio_normal = ttk.Radiobutton(
            drop_card,
            text="通常順 100% — スロット順を変えず全ドロップ枠を100%化（従来先頭枠が確定ドロップ）",
            variable=self.rare_first_var,
            value=False,
        )
        radio_normal.grid(row=2, column=0, sticky="w", padx=(18, 0), pady=2)
        self._rare_radios = [radio_rare, radio_normal]

        ttk.Checkbutton(
            drop_card,
            text="「ぬすむ」成功率も100%にする（任意：盗める敵から1回で必ず盗めます）",
            variable=self.steal_100_var,
        ).grid(row=3, column=0, sticky="w", pady=(4, 0))

        # 3. EXP / AP / Gil Multiplier Card + Action Buttons
        mult_card = ttk.LabelFrame(self, text="経験値 (EXP)・AP・ギル倍率設定 & 操作", padding=8)
        mult_card.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        mult_card.columnconfigure(1, weight=1)

        preset_row = ttk.Frame(mult_card, style="Panel.TFrame")
        preset_row.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(preset_row, text="一括プリセット:", style="Panel.TLabel").pack(
            side="left", padx=(0, 8)
        )
        for label, mult_val in ALL_PRESETS:
            ttk.Button(
                preset_row,
                text=label,
                command=lambda v=mult_val: self._set_all_multipliers(v),
            ).pack(side="left", padx=(0, 6))

        rows = (
            ("経験値 (EXP) 倍率:", self.exp_mult_var),
            ("AP 倍率:", self.ap_mult_var),
            ("ギル倍率:", self.gil_mult_var),
        )
        for r_idx, (title, var) in enumerate(rows, start=1):
            ttk.Label(mult_card, text=title, style="Panel.TLabel").grid(
                row=r_idx, column=0, sticky="w", padx=(0, 8), pady=3
            )
            spin = ttk.Spinbox(
                mult_card,
                from_=MIN_MULTIPLIER,
                to=MAX_MULTIPLIER,
                increment=0.5,
                textvariable=var,
                width=8,
            )
            spin.grid(row=r_idx, column=1, sticky="w", pady=3)
            var.trace_add("write", lambda *_args: self._update_preview())

            q_frame = ttk.Frame(mult_card, style="Panel.TFrame")
            q_frame.grid(row=r_idx, column=2, sticky="w", padx=(10, 0), pady=3)
            for q_label, q_val in QUICK_MULTIPLIERS:
                ttk.Button(
                    q_frame,
                    text=q_label,
                    width=5,
                    command=lambda target_var=var, v=q_val: target_var.set(_fmt_mult(v)),
                ).pack(side="left", padx=(0, 4))

        self.preview_label = ttk.Label(
            mult_card,
            text="",
            style="Success.TLabel",
            justify="left",
        )
        self.preview_label.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 8))

        btn_row = ttk.Frame(mult_card, style="Panel.TFrame")
        btn_row.grid(row=5, column=0, columnspan=3, sticky="w")

        self.apply_btn = ttk.Button(
            btn_row,
            text="設定を適用",
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

        # 4. Important FF7 Mechanics Notice
        note_card = ttk.LabelFrame(self, text="FF7 仕様・安全上の注意", padding=8)
        note_card.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        note_text = (
            "• 初回適用時にオリジナルの scene.bin を自動バックアップし、設定変更時も常にオリジナル基準で再計算するため倍率が重複しません。\n"
            f"• 安全上限は EXP/ギル {MAX_SAFE_EXP:,}・AP {MAX_SAFE_AP:,} です（元が0の敵は0のまま、倍率 0 指定で獲得なし・低レベル縛り対応）。\n"
            "• 他言語(en/de/es)の高倍率時にブロック再配置が必要な場合は、kernel.bin も自動バックアップ＆同期し、復元時に両方バニラへ戻します。\n"
            "• 原作仕様上、「ぬすむ」済み／「へんか」撃破時はドロップしません。適用・復元は FFVII.exe 終了後に行ってください。"
        )
        ttk.Label(note_card, text=note_text, style="Muted.TLabel", justify="left").pack(
            anchor="w"
        )

        # 5. Operation Log
        log_card = ttk.LabelFrame(self, text="操作ログ", padding=6)
        log_card.grid(row=4, column=0, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_card,
            height=4,
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

    def _on_drop_toggle(self) -> None:
        radio_state = "normal" if self.drop_100_var.get() else "disabled"
        for rb in self._rare_radios:
            rb.configure(state=radio_state)

    def _set_all_multipliers(self, value: float) -> None:
        text = _fmt_mult(value)
        self.exp_mult_var.set(text)
        self.ap_mult_var.set(text)
        self.gil_mult_var.set(text)

    @staticmethod
    def _parse_multiplier_text(raw: str, label: str) -> float:
        text = raw.strip()
        if not text:
            raise ScenePatchError(f"{label} 倍率を入力してください。")
        try:
            val = float(text)
        except ValueError as exc:
            raise ScenePatchError(f"{label} 倍率の数値が不正です: {raw!r}") from exc
        if not math.isfinite(val) or val < MIN_MULTIPLIER or val > MAX_MULTIPLIER:
            raise ScenePatchError(
                f"{label} 倍率は {MIN_MULTIPLIER:g} 〜 {MAX_MULTIPLIER:g} の範囲で指定してください。"
            )
        return val

    def _update_preview(self) -> None:
        try:
            exp_m = self._parse_multiplier_text(self.exp_mult_var.get(), "EXP")
            ap_m = self._parse_multiplier_text(self.ap_mult_var.get(), "AP")
            gil_m = self._parse_multiplier_text(self.gil_mult_var.get(), "ギル")
        except ScenePatchError as exc:
            self.preview_label.configure(
                text=f"プレビュー: 入力値エラー ({exc})",
                foreground=PALETTE["accent_red"],
            )
            return

        def calc(base: int, mult: float, cap: int) -> int:
            if mult <= 0.0:
                return 0
            return max(1, min(cap, int(round(base * mult))))

        p_exp = calc(100, exp_m, MAX_SAFE_EXP)
        p_ap = calc(10, ap_m, MAX_SAFE_AP)
        p_gil = calc(100, gil_m, MAX_SAFE_GIL)
        self.preview_label.configure(
            text=f"プレビュー（元値 EXP 100 / AP 10 / ギル 100）→ EXP {p_exp:,} / AP {p_ap:,} / ギル {p_gil:,}",
            foreground=PALETTE["accent_green"],
        )

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
            kernel_path = get_kernel_bin_path(game_dir, lang)
            try:
                st = get_patch_status(
                    scene_path, self._backup_dir, lang, kernel_path=kernel_path
                )
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
                summary_str = _summarize_config(st.applied_config)
                k_str = "・kernel同期済" if st.kernel_modified else ""
                label_text = f"適用中（{summary_str}{k_str}）"

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
                        f"盗み枠: {st.stats.steal_slot_count}（100%未満: {st.stats.non_max_steal_slot_count}）\n"
                        f"最大報酬(実敵): EXP {st.stats.max_exp:,} / AP {st.stats.max_ap:,} / ギル {st.stats.max_gil:,} ｜ "
                        f"バックアップ: {backup_info}"
                    )
                )
            else:
                self.stats_label.configure(text=f"ファイルが見つかりません: {st.scene_path}")

            self.apply_btn.configure(state="normal" if st.exists else "disabled")
            self.restore_btn.configure(
                state="normal" if (st.exists and st.has_backup) else "disabled"
            )
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
                badge_text, color = (
                    f"混在状態（適用:{patched_cnt} / バニラ:{vanilla_cnt}）",
                    PALETTE["accent_warn"],
                )

            self.badge_label.configure(text=badge_text, bg=color, fg="#FFFFFF")
            lines = []
            for lang, st in statuses:
                st_label = STATE_DISPLAY.get(st.state, (st.state, ""))[0]
                if st.state == "PATCHED" and st.applied_config:
                    st_label = _summarize_config(st.applied_config)
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

    def _build_config_from_ui(self) -> DropPatchConfig:
        exp_m = self._parse_multiplier_text(self.exp_mult_var.get(), "経験値 (EXP)")
        ap_m = self._parse_multiplier_text(self.ap_mult_var.get(), "AP")
        gil_m = self._parse_multiplier_text(self.gil_mult_var.get(), "ギル")
        cfg = DropPatchConfig(
            drop_100=bool(self.drop_100_var.get()),
            rare_first=bool(self.rare_first_var.get()),
            steal_100=bool(self.steal_100_var.get()),
            exp_multiplier=exp_m,
            ap_multiplier=ap_m,
            gil_multiplier=gil_m,
        )
        cfg.validate()
        return cfg

    def _save_ui_config_to_state(self, config: DropPatchConfig) -> None:
        self._state.patch_drop_100 = config.drop_100
        self._state.patch_rare_first = config.rare_first
        self._state.patch_steal_100 = config.steal_100
        self._state.patch_exp_mult = config.exp_multiplier
        self._state.patch_ap_mult = config.ap_multiplier
        self._state.patch_gil_mult = config.gil_multiplier
        self._save_state()

    def _on_apply(self) -> None:
        game_dir = self._get_game_dir()
        if game_dir is None:
            messagebox.showerror("エラー", "ゲームフォルダが設定されていません。", parent=self)
            return

        try:
            config = self._build_config_from_ui()
        except ScenePatchError as exc:
            messagebox.showerror("入力エラー", str(exc), parent=self)
            return

        if config.is_noop():
            self._save_ui_config_to_state(config)
            langs = self._selected_langs()
            has_any_backup = any(
                (self._backup_dir / f"lang-{lang}_scene.bin.orig").is_file()
                for lang in langs
            )
            if has_any_backup:
                if messagebox.askyesno(
                    "標準設定への復元",
                    "すべての設定が標準（ドロップ100% OFF・ぬすむ OFF・各倍率 1x）です。\n"
                    "バックアップからバニラ（元の状態）に復元しますか？",
                    parent=self,
                ):
                    self._perform_restore(confirm=False)
            else:
                messagebox.showinfo(
                    "変更なし",
                    "すべての設定が標準（ドロップ100% OFF・各倍率 1x）のため、適用する変更はありません。",
                    parent=self,
                )
            return

        if not self._guard_game_not_running():
            return

        self._save_ui_config_to_state(config)
        langs = self._selected_langs()
        succeeded: list[str] = []
        errors: list[str] = []
        summary_desc = _summarize_config(config)

        for lang in langs:
            scene_path = get_scene_bin_path(game_dir, lang)
            kernel_path = get_kernel_bin_path(game_dir, lang)
            if not scene_path.is_file():
                errors.append(f"lang-{lang}: ファイル未検出")
                continue
            try:
                st = apply_drop_patch(
                    scene_path, self._backup_dir, lang, config, kernel_path=kernel_path
                )
                succeeded.append(lang)
                k_note = "（ブロック再配置のため kernel.bin 同期済み）" if st.kernel_modified else ""
                self._append_log(f"lang-{lang} に適用しました（{summary_desc}）{k_note}")
            except Exception as exc:
                errors.append(f"lang-{lang}: {exc}")
                self._append_log(f"[ERROR] lang-{lang} 適用失敗: {exc}")

        self.refresh_status()
        if errors:
            messagebox.showerror("一部またはすべて失敗", "\n".join(errors), parent=self)
        elif succeeded:
            self._set_status(f"パッチを適用しました ({', '.join(succeeded)}): {summary_desc}")
            messagebox.showinfo(
                "適用完了",
                f"パッチの適用が完了しました。\n対象: {', '.join(succeeded)}\n設定: {summary_desc}\n"
                "オリジナルバックアップは安全に保持されています。",
                parent=self,
            )

    def _on_restore(self) -> None:
        self._perform_restore(confirm=True)

    def _perform_restore(self, *, confirm: bool) -> None:
        game_dir = self._get_game_dir()
        if game_dir is None:
            return
        if not self._guard_game_not_running():
            return

        langs = self._selected_langs()
        if confirm and not messagebox.askyesno(
            "バニラへ復元",
            "バックアップ済みのオリジナル scene.bin（および kernel.bin）へ復元しますか？",
            parent=self,
        ):
            return

        restored: list[str] = []
        errors: list[str] = []
        for lang in langs:
            scene_path = get_scene_bin_path(game_dir, lang)
            kernel_path = get_kernel_bin_path(game_dir, lang)
            orig_path = self._backup_dir / f"lang-{lang}_scene.bin.orig"
            if not orig_path.is_file():
                if len(langs) == 1:
                    errors.append(f"lang-{lang}: バックアップが見つかりません。")
                continue
            try:
                restore_vanilla(scene_path, self._backup_dir, lang, kernel_path=kernel_path)
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
