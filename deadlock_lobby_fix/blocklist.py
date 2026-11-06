"""Закрыть связь с кластерами, на которых играть не хочется."""
from __future__ import annotations

import json
import logging
import subprocess

from .words import plural, servers, spelled

log = logging.getLogger(__name__)

MARK = "DeadlockLobbyFix-relay"

KEEP_OPEN = 5

GIVE_UP_S = 60


def _run(command: str) -> str:
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=GIVE_UP_S,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0:
        raise OSError((done.stderr or "").strip()[:300] or "не вышло")
    return done.stdout


def can_change(run=None) -> bool:
    """Хватает ли прав. Правила брандмауэра требуют администратора."""
    command = ("[bool](([Security.Principal.WindowsPrincipal]"
               "[Security.Principal.WindowsIdentity]::GetCurrent())"
               ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))")
    try:
        return (run or _run)(command).strip().lower() == "true"
    except Exception as exc:
        log.info("права не проверились: %s", exc)
        return False


def blocked(run=None) -> set[str]:
    """Какие кластеры закрыты нами. Чужие правила не считаются."""
    command = (f"Get-NetFirewallRule -DisplayName '{MARK}-*' "
               f"-ErrorAction SilentlyContinue | "
               f"Select-Object -ExpandProperty DisplayName | ConvertTo-Json")
    try:
        text = (run or _run)(command).strip()
    except Exception as exc:
        log.info("список правил не прочитался: %s", exc)
        return set()
    if not text:
        return set()
    try:
        names = json.loads(text)
    except ValueError:
        names = [text]
    if isinstance(names, str):
        names = [names]
    out = set()
    for name in names:
        tail = str(name).rsplit("-", 1)[-1].strip()
        if tail:
            out.add(tail)
    return out


def check(codes, among, nearest: str | None = None) -> str:
    """Что не так с этим набором. Пустая строка -- всё в порядке."""
    want = set(codes)
    known = {c.code for c in among}
    unknown = want - known
    if unknown:
        каких = ", ".join(sorted(unknown))
        какого = plural(len(unknown), "такого сервера нет",
                        "таких серверов нет", "таких серверов нет")
        return f"{каких} — {какого} в списке. Коды бери из замера."
    if nearest and nearest in want:
        return ("Ближайший сервер закрывать нельзя: без него матч искать "
                "будет негде.")
    left = len(known) - len(want)
    if left < KEEP_OPEN:
        return (f"Открытым останется {servers(left)}, а надо хотя бы "
                f"{spelled(KEEP_OPEN)}. Закроешь больше — рискуешь не найти "
                f"матч вовсе.")
    return ""


def apply(codes, among, nearest: str | None = None, run=None) -> str:
    """Закрыть ровно эти кластеры и открыть все остальные."""
    want = set(codes)
    беда = check(want, among, nearest)
    if беда:
        return беда
    if not can_change(run):
        return ("Нужны права администратора — без них Windows не даёт "
                "трогать брандмауэр.")
    try:
        clear(run)
        by_code = {c.code: c for c in among}
        for code in sorted(want):
            адреса = ",".join(by_code[code].ips)
            if not адреса:
                continue
            for направление in ("Outbound", "Inbound"):
                (run or _run)(
                    f"New-NetFirewallRule -DisplayName "
                    f"'{MARK}-{направление}-{code}' -Direction {направление} "
                    f"-Action Block -RemoteAddress {адреса} "
                    f"-Description 'deadlock-lobby-fix: кластер {code} закрыт "
                    f"по просьбе игрока' | Out-Null"
                )
        return ""
    except Exception as exc:
        log.info("правила не поставились: %s", exc)
        return f"Правила не встали. Windows ответил так: {exc}"


def clear(run=None) -> str:
    """Снять всё, что поставили мы. Чужого не трогает."""
    try:
        (run or _run)(
            f"Get-NetFirewallRule -DisplayName '{MARK}-*' "
            f"-ErrorAction SilentlyContinue | Remove-NetFirewallRule"
        )
        return ""
    except Exception as exc:
        log.info("правила не снялись: %s", exc)
        return f"Правила не снялись. Windows ответил так: {exc}"
