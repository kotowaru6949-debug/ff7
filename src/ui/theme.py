"""FF7-inspired dark navy theme and ttk styling helpers."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

PALETTE = {
    "bg_main": "#101828",
    "bg_panel": "#182338",
    "bg_surface": "#1F2E49",
    "bg_input": "#121B2D",
    "border": "#31476E",
    "fg_text": "#F0F4F8",
    "fg_muted": "#9FB3C8",
    "accent_green": "#2ECC71",
    "accent_green_dark": "#239B56",
    "accent_blue": "#3B82F6",
    "accent_blue_hover": "#2563EB",
    "accent_warn": "#F59E0B",
    "accent_red": "#FF6B6B",
    "accent_red_dark": "#C0392B",
    "select_bg": "#244775",
    "row_alt": "#152035",
    "row_missable": "#3A1F2B",
}


def get_ui_font(size: int = 10, bold: bool = False) -> tuple[str, int, str] | tuple[str, int]:
    """Return a clean Japanese-capable UI font tuple for Windows/cross-platform."""
    family = "Meiryo UI" if sys.platform == "win32" else "TkDefaultFont"
    return (family, size, "bold") if bold else (family, size)


def apply_theme(root: tk.Tk) -> ttk.Style:
    """Apply dark FF7-styled theme to root and ttk widgets."""
    root.configure(bg=PALETTE["bg_main"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    base_font = get_ui_font(10)
    bold_font = get_ui_font(10, bold=True)
    small_font = get_ui_font(9)

    style.configure(
        ".",
        background=PALETTE["bg_main"],
        foreground=PALETTE["fg_text"],
        font=base_font,
        bordercolor=PALETTE["border"],
        focuscolor=PALETTE["accent_blue"],
    )

    style.configure("TFrame", background=PALETTE["bg_main"])
    style.configure("Panel.TFrame", background=PALETTE["bg_panel"])
    style.configure("Header.TFrame", background=PALETTE["bg_surface"])

    style.configure("TLabel", background=PALETTE["bg_main"], foreground=PALETTE["fg_text"], font=base_font)
    style.configure("Panel.TLabel", background=PALETTE["bg_panel"], foreground=PALETTE["fg_text"], font=base_font)
    style.configure("Muted.TLabel", background=PALETTE["bg_panel"], foreground=PALETTE["fg_muted"], font=small_font)
    style.configure("Header.TLabel", background=PALETTE["bg_surface"], foreground=PALETTE["fg_text"], font=base_font)
    style.configure("HeaderTitle.TLabel", background=PALETTE["bg_surface"], foreground=PALETTE["fg_text"], font=get_ui_font(12, True))
    style.configure("Warn.TLabel", background=PALETTE["bg_panel"], foreground=PALETTE["accent_red"], font=bold_font)
    style.configure("Success.TLabel", background=PALETTE["bg_panel"], foreground=PALETTE["accent_green"], font=bold_font)

    style.configure(
        "TLabelframe",
        background=PALETTE["bg_panel"],
        foreground=PALETTE["fg_text"],
        bordercolor=PALETTE["border"],
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=PALETTE["bg_panel"],
        foreground=PALETTE["accent_green"],
        font=bold_font,
    )

    style.configure(
        "TButton",
        background=PALETTE["bg_surface"],
        foreground=PALETTE["fg_text"],
        bordercolor=PALETTE["border"],
        padding=(10, 6),
        font=bold_font,
    )
    style.map(
        "TButton",
        background=[("active", PALETTE["select_bg"]), ("disabled", "#1B2433")],
        foreground=[("disabled", "#64748B")],
    )

    style.configure(
        "Primary.TButton",
        background=PALETTE["accent_blue"],
        foreground="#FFFFFF",
        bordercolor=PALETTE["accent_blue"],
        padding=(12, 7),
        font=bold_font,
    )
    style.map(
        "Primary.TButton",
        background=[("active", PALETTE["accent_blue_hover"]), ("disabled", "#1E3A5F")],
        foreground=[("disabled", "#94A3B8")],
    )

    style.configure(
        "Success.TButton",
        background=PALETTE["accent_green_dark"],
        foreground="#FFFFFF",
        bordercolor=PALETTE["accent_green"],
        padding=(10, 6),
        font=bold_font,
    )
    style.map(
        "Success.TButton",
        background=[("active", PALETTE["accent_green"]), ("disabled", "#1D4433")],
    )

    style.configure(
        "Danger.TButton",
        background="#7F1D1D",
        foreground="#FFFFFF",
        bordercolor=PALETTE["accent_red"],
        padding=(10, 6),
        font=bold_font,
    )
    style.map(
        "Danger.TButton",
        background=[("active", PALETTE["accent_red_dark"]), ("disabled", "#3B1F23")],
    )

    style.configure("TNotebook", background=PALETTE["bg_main"], borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=PALETTE["bg_panel"],
        foreground=PALETTE["fg_muted"],
        padding=(14, 7),
        font=bold_font,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", PALETTE["select_bg"]), ("active", PALETTE["bg_surface"])],
        foreground=[("selected", "#FFFFFF"), ("active", PALETTE["fg_text"])],
    )

    style.configure(
        "TCheckbutton",
        background=PALETTE["bg_panel"],
        foreground=PALETTE["fg_text"],
        font=base_font,
    )
    style.map("TCheckbutton", background=[("active", PALETTE["bg_panel"])])

    style.configure(
        "TRadiobutton",
        background=PALETTE["bg_panel"],
        foreground=PALETTE["fg_text"],
        font=base_font,
    )
    style.map("TRadiobutton", background=[("active", PALETTE["bg_panel"])])

    style.configure(
        "TEntry",
        fieldbackground=PALETTE["bg_input"],
        foreground=PALETTE["fg_text"],
        insertcolor=PALETTE["fg_text"],
        bordercolor=PALETTE["border"],
        padding=4,
    )
    style.configure(
        "TCombobox",
        fieldbackground=PALETTE["bg_input"],
        background=PALETTE["bg_surface"],
        foreground=PALETTE["fg_text"],
        arrowcolor=PALETTE["fg_text"],
        bordercolor=PALETTE["border"],
        padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PALETTE["bg_input"])],
        foreground=[("readonly", PALETTE["fg_text"])],
    )

    style.configure(
        "Treeview",
        background=PALETTE["bg_input"],
        fieldbackground=PALETTE["bg_input"],
        foreground=PALETTE["fg_text"],
        bordercolor=PALETTE["border"],
        rowheight=26,
        font=base_font,
    )
    style.configure(
        "Treeview.Heading",
        background=PALETTE["bg_surface"],
        foreground=PALETTE["fg_text"],
        bordercolor=PALETTE["border"],
        font=bold_font,
        padding=(6, 4),
    )
    style.map(
        "Treeview",
        background=[("selected", PALETTE["select_bg"])],
        foreground=[("selected", "#FFFFFF")],
    )

    style.configure(
        "Horizontal.TProgressbar",
        background=PALETTE["accent_green"],
        troughcolor=PALETTE["bg_input"],
        bordercolor=PALETTE["border"],
        thickness=14,
    )

    style.configure("TPanedwindow", background=PALETTE["bg_main"])
    return style
