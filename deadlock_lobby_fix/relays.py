"""Пинг до релеев Valve -- тех самых, по которым Deadlock выбирает сервер.

Зачем это нужно
---------------
Частая жалоба: «кидает в чужой регион, пинг огромный». Выбора региона в
игре нет, и это не упущение интерфейса, а устройство матчмейкинга. Строки
самой игры говорят прямо:

    Citadel_StartMatchmaking_NoRegionPings
        "Unable to communicate with any Steam Datagram Relay..."

То есть клиент замеряет задержку до релеев Steam Datagram Relay, и
матчмейкер решает по этим замерам. Переключателя «играть только в Европе»
нет нигде -- ни в настройках, ни в строках интерфейса. Искать это пришлось
в файлах самой игры: вики отдаёт заглушку, Reddit не пускает, форум забит
спамом с инвайтами.

Раз выбрать нельзя, помочь можно одним: показать человеку то же, что видит
матчмейкер. Свой настоящий пинг до каждого кластера. По нему видно и почему
кидает далеко, и не испорчен ли маршрут у провайдера: если у одного
семьдесят миллисекунд до Стокгольма, а у другого сто сорок -- у второго
беда у провайдера, и она чинится. Без замера это не отличить от «игра
плохая».

Откуда список
-------------
Valve публикует его сама, для этой самой игры:

    https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=1422450

Тридцать семь кластеров, тридцать три с адресами и человеческими именами.
Свой список мы не ведём: он протухнет на первом же новом датацентре.

Чем меряем
----------
`Test-Connection` из PowerShell, а не `ping.exe`. Причина простая: вывод
`ping.exe` переведён на язык системы, и разбирать «Среднее = 84мсек»
против "Average = 84ms" значит завести себе ошибку на ровном месте.
PowerShell отдаёт число полем, и язык системы на это не влияет.
"""
from __future__ import annotations

import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

log = logging.getLogger(__name__)

APP_ID = 1422450
SDR_URL = f"https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid={APP_ID}"

# Сколько раз стучать в каждый кластер. Три: одиночный замер ловит случайный
# всплеск, а десять превращают проверку в минутное ожидание.
TRIES = 3

# Сколько секунд ждать всю команду целиком, считая запуск PowerShell. Это
# потолок на процесс, а не таймаут отдельного пакета: у Test-Connection в
# Windows PowerShell 5.1 такого параметра нет вовсе (-TimeoutSeconds
# появился только в PowerShell 7). Молчащий узел упирается в собственный
# срок Test-Connection, и этот потолок -- последняя страховка от того,
# чтобы один мёртвый адрес задержал весь замер.
GIVE_UP_S = 15

# Докуда пинг считается хорошим, а с какого -- беда. Границы не выдуманы:
# до пятидесяти игра идёт как задумана, после ста пятидесяти стрельба с
# упреждением перестаёт работать вовсе.
GOOD_MS = 50
BAD_MS = 150

# Сколько кластеров опрашивать разом. Тридцать три подряд заняли полторы
# минуты, двенадцатью нитями -- девять секунд. Ожидание здесь не считает
# процессор, а ждёт сети, так что нитям есть чем заняться.
AT_ONCE = 12


@dataclass(frozen=True)
class Cluster:
    """Один кластер Valve: код, человеческое имя и адреса релеев."""

    code: str
    name: str
    ips: tuple[str, ...]


@dataclass(frozen=True)
class Ping:
    """Замер до кластера. `ms is None` -- не ответил, а не «ноль»."""

    cluster: Cluster
    ms: float | None = None

    @property
    def good(self) -> bool:
        return self.ms is not None and self.ms <= GOOD_MS

    @property
    def bad(self) -> bool:
        return self.ms is None or self.ms >= BAD_MS

    @property
    def verdict(self) -> str:
        """Одно слово о числе: по нему красится строка и в окне, и в CLI."""
        if self.ms is None:
            return "молчит"
        if self.good:
            return "хорошо"
        if self.bad:
            return "плохо"
        return "терпимо"


def clusters(fetch=None) -> list[Cluster]:
    """Список кластеров Valve. Пустой, если не достучались.

    `fetch` подменяется в проверках -- и только в них. Пустой список здесь
    не ошибка, а ответ: сети нет или Valve сменила формат. Тот, кто его
    получил, скажет об этом человеку, а не упадёт.
    """
    try:
        if fetch is None:
            import urllib.request  # noqa: PLC0415 - нужен только здесь

            with urllib.request.urlopen(SDR_URL, timeout=20) as answer:
                data = json.load(answer)
        else:
            data = fetch()
    except Exception as exc:  # noqa: BLE001 - скажем словами, а не упадём
        log.info("список релеев не пришёл: %s", exc)
        return []
    out = []
    for code, node in sorted((data.get("pops") or {}).items()):
        ips = tuple(r.get("ipv4") for r in (node.get("relays") or [])
                    if r.get("ipv4"))
        if not ips:
            # Кластер без адресов -- служебный, пинговать нечего.
            continue
        out.append(Cluster(code=code, name=str(node.get("desc") or code),
                           ips=ips))
    return out


def _ask(ip: str, run=None) -> float | None:
    """Средняя задержка до одного адреса, или None."""
    command = (
        f"$r = Test-Connection -ComputerName {ip} -Count {TRIES} "
        f"-ErrorAction Stop; "
        f"($r | Measure-Object -Property ResponseTime -Average).Average"
    )
    try:
        done = (run or _run)(command)
    except Exception as exc:  # noqa: BLE001 - молчащий узел не беда
        log.debug("%s не ответил: %s", ip, exc)
        return None
    text = (done or "").strip()
    try:
        return float(text.replace(",", "."))
    except ValueError:
        # Сюда попадает и пустой ответ, и текст ошибки PowerShell. И то и
        # другое значит «неизвестно», а не «ноль миллисекунд».
        return None


def _run(command: str) -> str:
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=GIVE_UP_S,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return done.stdout


def measure(where: list[Cluster], run=None, at_once: int = AT_ONCE,
            progress=None) -> list[Ping]:
    """Замерить все кластеры и вернуть от ближнего к дальнему.

    Не ответившие уходят в конец: это не «ноль миллисекунд», а
    «неизвестно», и показывать их первыми значило бы соврать -- молчащий
    узел притворился бы самым близким.

    `progress(сделано, всего)` зовётся из рабочих нитей, если передан. Для
    окна это значит, что обновлять виджеты оттуда напрямую нельзя.
    """
    if not where:
        return []
    сделано = 0

    def один(cluster: Cluster) -> Ping:
        nonlocal сделано
        # Первый адрес кластера. Релеи одного кластера стоят в одной стойке,
        # и разница между ними меньше, чем разброс между замерами.
        итог = Ping(cluster=cluster, ms=_ask(cluster.ips[0], run))
        сделано += 1
        if progress is not None:
            progress(сделано, len(where))
        return итог

    with ThreadPoolExecutor(max_workers=max(1, at_once)) as pool:
        out = list(pool.map(один, where))
    return sorted(out, key=lambda p: (p.ms is None, p.ms if p.ms else 0.0))


def nearest(pings: list[Ping]) -> Ping | None:
    """Ближайший ответивший кластер. Его закрывать нельзя -- см. blocklist."""
    return next((p for p in pings if p.ms is not None), None)
