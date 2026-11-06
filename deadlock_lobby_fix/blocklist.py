"""Закрыть связь с кластерами, на которых играть не хочется.

Как это работает
----------------
Матчмейкинг Deadlock решает по замеренному пингу до релеев Steam Datagram
Relay -- это сказано строками самой игры (`Citadel_StartMatchmaking_
NoRegionPings`). До чего клиент не достучался, того для матчмейкера не
существует, и туда он не отправит. Значит правило брандмауэра, закрывающее
адреса кластера, убирает его из выбора.

Приём не новый: тем же живут «пикеры серверов» для CS и Dota. Игру он не
трогает -- ни кода, ни памяти, ни файлов; это настройка сети на своей
машине.

Чем это опасно на самом деле
----------------------------
Не блокировкой, а перебором. У той же игры есть строка:

    "Unable to communicate with any Steam Datagram Relay..."

-- то есть закрыв слишком много, человек не сыграет вовсе. Поэтому здесь
три предохранителя, и обойти их нельзя:

* ближайший кластер закрыть нельзя никогда;
* незакрытых должно остаться не меньше `KEEP_OPEN`;
* проверка идёт до первой команды -- отказ на середине оставил бы
  половину правил поставленными.

Снимается именно наше, по метке в имени правила. Чужие правила брандмауэра
не трогаются и даже не перечисляются: человек мог настроить там что угодно
задолго до нас.

И ещё одно, о чём стоит сказать вслух: чем больше закрыто, тем дольше
ищется матч. Это не поломка, это цена.

Права
-----
Правила брандмауэра требуют запуска от имени администратора. Без них
ничего не делается молча: `can_change()` скажет заранее, а не на середине.
"""
from __future__ import annotations

import json
import logging
import subprocess

from .words import plural, servers, spelled

log = logging.getLogger(__name__)

# Имя, по которому мы узнаём свои правила. Менять нельзя: по нему же они и
# снимаются, а переименование оставит прежние висеть навсегда.
MARK = "DeadlockLobbyFix-relay"

# Сколько кластеров обязано остаться открытыми. Пять: закрыв больше, человек
# рискует не найти матч вовсе, а эта беда выглядит как «программа сломала
# игру» и чинится не сразу.
KEEP_OPEN = 5

# Сколько ждать PowerShell. Правила ставятся быстро, но на холодной машине
# первый запуск самого PowerShell занимает несколько секунд.
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
    except Exception as exc:  # noqa: BLE001 - нет ответа значит «нет прав»
        log.info("права не проверились: %s", exc)
        return False


def blocked(run=None) -> set[str]:
    """Какие кластеры закрыты нами. Чужие правила не считаются."""
    command = (f"Get-NetFirewallRule -DisplayName '{MARK}-*' "
               f"-ErrorAction SilentlyContinue | "
               f"Select-Object -ExpandProperty DisplayName | ConvertTo-Json")
    try:
        text = (run or _run)(command).strip()
    except Exception as exc:  # noqa: BLE001
        log.info("список правил не прочитался: %s", exc)
        return set()
    if not text:
        return set()
    try:
        names = json.loads(text)
    except ValueError:
        names = [text]
    if isinstance(names, str):
        # Одно правило PowerShell отдаёт строкой, а не списком из одного.
        names = [names]
    out = set()
    for name in names:
        tail = str(name).rsplit("-", 1)[-1].strip()
        if tail:
            out.add(tail)
    return out


def check(codes, among, nearest: str | None = None) -> str:
    """Что не так с этим набором. Пустая строка -- всё в порядке.

    Возвращается готовая фраза, а не обрывок: тот, кто её показывает,
    ничего к ней не дописывает. Иначе каждый зовущий придумывает своё
    начало, и человек читает то «Ошибка: ближайший кластер...», то
    «Так нельзя: ближайший кластер...».
    """
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
    """Закрыть ровно эти кластеры и открыть все остальные.

    Возвращает пустую строку, если получилось, иначе причину. Сперва
    снимает всё своё, потом ставит заново -- так набор правил всегда
    описывает то, что человек выбрал, а не историю его нажатий.
    """
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
            # Обе стороны: исходящие закрывают наш стук в релей, входящие --
            # его ответ. Одного направления мало, ответ может прийти по уже
            # открытому пути.
            for направление in ("Outbound", "Inbound"):
                (run or _run)(
                    f"New-NetFirewallRule -DisplayName "
                    f"'{MARK}-{направление}-{code}' -Direction {направление} "
                    f"-Action Block -RemoteAddress {адреса} "
                    f"-Description 'deadlock-lobby-fix: кластер {code} закрыт "
                    f"по просьбе игрока' | Out-Null"
                )
        return ""
    except Exception as exc:  # noqa: BLE001 - скажем словами, а не упадём
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
    except Exception as exc:  # noqa: BLE001
        log.info("правила не снялись: %s", exc)
        return f"Правила не снялись. Windows ответил так: {exc}"
