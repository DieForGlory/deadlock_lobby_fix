"""Точка входа: `python -m deadlock_lobby_fix`."""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
