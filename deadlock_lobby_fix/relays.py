"""Пинг до релеев Valve -- тех самых, по которым Deadlock выбирает сервер."""
from __future__ import annotations

import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

log = logging.getLogger(__name__)

APP_ID = 1422450
SDR_URL = f"https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid={APP_ID}"

TRIES = 3

GIVE_UP_S = 15

GOOD_MS = 50
BAD_MS = 150

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
    """Список кластеров Valve. Пустой, если не достучались."""
    try:
        if fetch is None:
            import urllib.request

            with urllib.request.urlopen(SDR_URL, timeout=20) as answer:
                data = json.load(answer)
        else:
            data = fetch()
    except Exception as exc:
        log.info("список релеев не пришёл: %s", exc)
        return []
    out = []
    for code, node in sorted((data.get("pops") or {}).items()):
        ips = tuple(r.get("ipv4") for r in (node.get("relays") or [])
                    if r.get("ipv4"))
        if not ips:
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
    except Exception as exc:
        log.debug("%s не ответил: %s", ip, exc)
        return None
    text = (done or "").strip()
    try:
        return float(text.replace(",", "."))
    except ValueError:
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
    """Замерить все кластеры и вернуть от ближнего к дальнему."""
    if not where:
        return []
    сделано = 0

    def один(cluster: Cluster) -> Ping:
        nonlocal сделано
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
