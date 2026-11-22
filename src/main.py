"""Entry point for FF7 Steam Edition comfort tool."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ui.app import create_app


def main() -> None:
    app = create_app()
    app.mainloop()


if __name__ == "__main__":
    main()
