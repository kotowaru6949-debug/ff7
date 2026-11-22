"""Main Tkinter application window for FF7 Steam Edition comfort tool."""

from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from companion.repository import CompanionRepository
from core.paths import (
    detect_game_dir,
    get_backup_dir,
    get_executable_paths,
    get_project_root,
    get_user_data_dir,
    is_game_running,
    validate_game_dir,
)
from core.state_store import StateStore
from ui.tabs.drop_tab import DropTab
from ui.tabs.enemy_skills_tab import EnemySkillsTab
from ui.tabs.missables_tab import MissablesTab
from ui.theme import PALETTE, apply_theme, get_ui_font


class FF7ComfortApp(tk.Tk):
    """Main desktop GUI shell combining drop patcher, missables, and enemy skills."""

    def __init__(self, project_root: Path | None = None, *, withdraw: bool = False) -> None:
        super().__init__()
        if withdraw:
            self.withdraw()

        self.project_root = project_root if project_root is not None else get_project_root()
        self.user_data_dir = get_user_data_dir(self.project_root)
        self.backup_dir = get_backup_dir(self.project_root)
        self.state_store = StateStore(self.user_data_dir / "state.json")
        self.state = self.state_store.load()
        self.repo = CompanionRepository()

        self.game_dir: Path | None = self._resolve_initial_game_dir()

        self.title("FF7 Steam Edition 快適化ツール")
        self.geometry("1080x740")
        self.minsize(880, 620)
        apply_theme(self)

        self.status_var = tk.StringVar(value="準備完了")
        self._build_layout()
        self._refresh_header()

    def _resolve_initial_game_dir(self) -> Path | None:
        if self.state.game_dir:
            candidate = Path(self.state.game_dir)
            if validate_game_dir(candidate):
                return candidate
        detected = detect_game_dir()
        if detected is not None:
            self.state.game_dir = str(detected)
            self.state_store.save(self.state)
        return detected

    def save_state(self) -> None:
        self.state_store.save(self.state)

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header Bar
        header = ttk.Frame(self, style="Header.TFrame", padding=(12, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        left_header = ttk.Frame(header, style="Header.TFrame")
        left_header.grid(row=0, column=0, sticky="ew")

        ttk.Label(
            left_header,
            text="FINAL FANTASY VII Steam Edition 快適化ツール",
            style="HeaderTitle.TLabel",
        ).pack(anchor="w")

        path_row = ttk.Frame(left_header, style="Header.TFrame")
        path_row.pack(anchor="w", fill="x", pady=(4, 0))

        self.game_status_badge = tk.Label(
            path_row,
            text="",
            font=get_ui_font(9, True),
            padx=6,
            pady=1,
        )
        self.game_status_badge.pack(side="left", padx=(0, 8))

        self.game_path_label = ttk.Label(path_row, text="", style="Header.TLabel")
        self.game_path_label.pack(side="left")

        right_header = ttk.Frame(header, style="Header.TFrame")
        right_header.grid(row=0, column=1, sticky="e", padx=(12, 0))

        ttk.Button(
            right_header,
            text="フォルダ選択...",
            command=self._choose_game_dir,
        ).pack(side="left", padx=(0, 6))

        self.direct_launch_btn = ttk.Button(
            right_header,
            text="FFVII 直接起動",
            style="Success.TButton",
            command=lambda: self._launch_game(use_launcher=False),
        )
        self.direct_launch_btn.pack(side="left", padx=(0, 6))

        self.launcher_btn = ttk.Button(
            right_header,
            text="公式ランチャー起動",
            command=lambda: self._launch_game(use_launcher=True),
        )
        self.launcher_btn.pack(side="left")

        # Main Notebook
        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=8, pady=(8, 4))

        self.drop_tab = DropTab(
            notebook,
            get_game_dir=lambda: self.game_dir,
            backup_dir=self.backup_dir,
            state=self.state,
            save_state=self.save_state,
            set_status=self.set_status,
        )
        self.missables_tab = MissablesTab(
            notebook,
            repo=self.repo,
            state=self.state,
            save_state=self.save_state,
            set_status=self.set_status,
        )
        self.enemy_skills_tab = EnemySkillsTab(
            notebook,
            repo=self.repo,
            state=self.state,
            save_state=self.save_state,
            set_status=self.set_status,
        )

        notebook.add(self.drop_tab, text=" ドロップ率100% ")
        notebook.add(self.missables_tab, text=" 取り逃し防止 ")
        notebook.add(self.enemy_skills_tab, text=" てきのわざ (24種) ")

        # Bottom Status Bar
        status_bar = ttk.Frame(self, style="Header.TFrame", padding=(10, 4))
        status_bar.grid(row=2, column=0, sticky="ew")
        ttk.Label(status_bar, textvariable=self.status_var, style="Header.TLabel").pack(anchor="w")

    def _refresh_header(self) -> None:
        if self.game_dir is not None and validate_game_dir(self.game_dir):
            self.game_status_badge.configure(
                text="ゲーム検出OK",
                bg=PALETTE["accent_green_dark"],
                fg="#FFFFFF",
            )
            self.game_path_label.configure(text=str(self.game_dir))
            self.direct_launch_btn.configure(state="normal")
            self.launcher_btn.configure(state="normal")
        else:
            self.game_status_badge.configure(
                text="未検出",
                bg=PALETTE["accent_red_dark"],
                fg="#FFFFFF",
            )
            self.game_path_label.configure(
                text="FINAL FANTASY VII Steam Edition フォルダを選択してください"
            )
            self.direct_launch_btn.configure(state="disabled")
            self.launcher_btn.configure(state="disabled")

    def _choose_game_dir(self) -> None:
        chosen = filedialog.askdirectory(
            title="FINAL FANTASY VII Steam Edition フォルダを選択",
            initialdir=str(self.game_dir) if self.game_dir else None,
            parent=self,
        )
        if not chosen:
            return
        candidate = Path(chosen)
        if not validate_game_dir(candidate):
            messagebox.showerror(
                "無効なフォルダ",
                "選択したフォルダ内に FFVII.exe および ff7/workingdir/data が見つかりませんでした。",
                parent=self,
            )
            return
        self.game_dir = candidate
        self.state.game_dir = str(candidate)
        self.save_state()
        self._refresh_header()
        self.drop_tab.refresh_status()
        self.set_status(f"ゲームフォルダを変更しました: {candidate}")

    def _launch_game(self, *, use_launcher: bool) -> None:
        if self.game_dir is None:
            return
        if is_game_running():
            messagebox.showinfo(
                "起動済み",
                "FFVII.exe はすでに起動しています。",
                parent=self,
            )
            return
        ffvii_exe, launcher_exe = get_executable_paths(self.game_dir)
        target = launcher_exe if use_launcher else ffvii_exe
        if not target.is_file():
            messagebox.showerror(
                "実行ファイル未検出",
                f"実行ファイルが見つかりません:\n{target}",
                parent=self,
            )
            return
        try:
            subprocess.Popen([str(target)], cwd=str(self.game_dir))
            label = "公式ランチャー" if use_launcher else "FFVII.exe（直接起動）"
            self.set_status(f"{label} を起動しました。")
        except OSError as exc:
            messagebox.showerror("起動エラー", f"起動に失敗しました:\n{exc}", parent=self)


def create_app(project_root: Path | None = None, *, withdraw: bool = False) -> FF7ComfortApp:
    """Create and return the main FF7ComfortApp instance."""
    return FF7ComfortApp(project_root=project_root, withdraw=withdraw)
