"""Перезапуск самого себя с правами администратора.

Правила брандмауэра без них не создаются, а узнаёт об этом человек в самый
неподходящий момент -- когда уже замерил пинг и выбрал, что закрывать.
Поэтому права проверяются заранее, а здесь лежит способ их получить, не
заставляя человека искать «запуск от имени администратора» в контекстном
меню.

Просим мы их только когда надо. Замер пинга правами не пользуется, и
запускать всю программу от администратора ради таблички с числами -- дурной
тон, который приучает соглашаться на UAC не глядя.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)

SHELL_OK = 32          # ShellExecuteW: всё, что больше, -- успех


def running_as_admin() -> bool:
    """Есть ли у этого процесса права администратора.

    Через WinAPI, а не через PowerShell: здесь ответ нужен сразу, при
    запуске окна, а запуск PowerShell на холодной машине занимает секунды.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes  # noqa: PLC0415 - только на Windows

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:  # noqa: BLE001 - нет ответа значит «нет прав»
        log.info("права не проверились: %s", exc)
        return False


def relaunch_as_admin(args: list[str] | None = None) -> str:
    """Запустить эту же программу заново, через UAC.

    Возвращает пустую строку, если запрос ушёл, иначе причину. Нынешний
    процесс при этом не закрывается: решение закрыться принимает тот, кто
    звал, -- окну надо успеть попрощаться, а CLI просто выйдет.

    Отказ в UAC -- это не ошибка программы, а ответ человека, и звучит он
    соответственно.
    """
    if os.name != "nt":
        return "Права администратора бывают только на Windows."
    if running_as_admin():
        return ""
    хвост = list(sys.argv[1:] if args is None else args)
    try:
        import ctypes  # noqa: PLC0415

        if getattr(sys, "frozen", False):
            # Собранный exe запускает сам себя: своего скрипта у него нет.
            цель, строка = sys.executable, subprocess.list2cmdline(хвост)
        else:
            цель = sys.executable
            строка = subprocess.list2cmdline(["-m", "deadlock_lobby_fix", *хвост])
        код = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", цель, строка, None, 1)
    except Exception as exc:  # noqa: BLE001
        log.info("перезапуск не вышел: %s", exc)
        return f"Перезапустить не получилось: {exc}"
    if код <= SHELL_OK:
        # 5 -- ACCESS_DENIED, то есть человек нажал «Нет» в окне UAC.
        return ("Права не выданы — видимо, в окне Windows нажали «Нет»."
                if код == 5 else
                f"Windows отказался перезапускать программу (код {код}).")
    return ""
