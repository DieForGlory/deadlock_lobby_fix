"""Перезапуск самого себя с правами администратора."""
from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)

SHELL_OK = 32


def running_as_admin() -> bool:
    """Есть ли у этого процесса права администратора."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:
        log.info("права не проверились: %s", exc)
        return False


def relaunch_as_admin(args: list[str] | None = None) -> str:
    """Запустить эту же программу заново, через UAC."""
    if os.name != "nt":
        return "Права администратора бывают только на Windows."
    if running_as_admin():
        return ""
    хвост = list(sys.argv[1:] if args is None else args)
    try:
        import ctypes

        if getattr(sys, "frozen", False):
            цель, строка = sys.executable, subprocess.list2cmdline(хвост)
        else:
            цель = sys.executable
            строка = subprocess.list2cmdline(["-m", "deadlock_lobby_fix", *хвост])
        код = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", цель, строка, None, 1)
    except Exception as exc:
        log.info("перезапуск не вышел: %s", exc)
        return f"Перезапустить не получилось: {exc}"
    if код <= SHELL_OK:
        return ("Права не выданы — видимо, в окне Windows нажали «Нет»."
                if код == 5 else
                f"Windows отказался перезапускать программу (код {код}).")
    return ""
