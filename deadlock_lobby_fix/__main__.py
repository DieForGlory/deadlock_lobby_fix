"""Точка входа: `python -m deadlock_lobby_fix`.

Без команды открывается окно -- тот, кто запустил двойным щелчком, команду
не вводил и вводить не собирался.
"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
