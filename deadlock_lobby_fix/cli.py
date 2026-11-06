"""Командная строка: померить, посмотреть, закрыть, открыть.

Окно удобнее, но командную строку видно насквозь -- а программа, которая
правит брандмауэр, обязана быть видна насквозь. Здесь каждая команда
печатает, что именно она сделает, и `block` без `--yes` ничего не делает
вовсе: только показывает список.

`--json` есть у каждой команды, которая что-то узнаёт. Это не украшение:
кто-то захочет вставить замер в свой скрипт, и пусть он разбирает JSON, а
не нашу табличку.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import blocklist, relays
from .elevate import relaunch_as_admin, running_as_admin
from .words import plural, servers

# Цвет только в настоящем терминале и только по просьбе. Перенаправленный
# вывод с escape-последовательностями читать нечем, а в файле они мусор.
ЦВЕТА = {
    "хорошо": "\033[92m",
    "терпимо": "\033[93m",
    "плохо": "\033[91m",
    "молчит": "\033[90m",
}
СБРОС = "\033[0m"


def _красить(нужно: bool):
    if not нужно:
        return lambda текст, _вердикт: текст
    return lambda текст, вердикт: f"{ЦВЕТА.get(вердикт, '')}{текст}{СБРОС}"


def _хочется_цвета(args) -> bool:
    if args.no_color:
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _замерить(args) -> list[relays.Ping]:
    где = relays.clusters()
    if not где:
        print("Valve не ответила — похоже, сети нет. Проверь и попробуй "
              "ещё раз.", file=sys.stderr)
        return []
    if not args.json:
        print(f"Спрашиваю {servers(len(где))}, это секунд десять…",
              file=sys.stderr)
    return relays.measure(где)


def _таблица(pings, закрытые, args) -> None:
    """Кластеры от ближнего к дальнему, с пометкой закрытых."""
    краска = _красить(_хочется_цвета(args))
    ближний = relays.nearest(pings)
    ширина = max((len(p.cluster.name) for p in pings), default=20)
    for ping in pings:
        число = f"{ping.ms:>6.0f} мс" if ping.ms is not None else "  молчит"
        метки = []
        if ping.cluster.code in закрытые:
            метки.append("закрыт")
        if ближний is not None and ping.cluster.code == ближний.cluster.code:
            метки.append("ближе всех")
        хвост = ("  [" + ", ".join(метки) + "]") if метки else ""
        print(f"  {ping.cluster.code:<6} {ping.cluster.name:<{ширина}}  "
              f"{краска(число, ping.verdict)}{хвост}")


def _как_json(pings, закрытые) -> None:
    print(json.dumps([
        {"code": p.cluster.code, "name": p.cluster.name, "ms": p.ms,
         "verdict": p.verdict, "blocked": p.cluster.code in закрытые}
        for p in pings], ensure_ascii=False, indent=2))


# ------------------------------------------------------------- команды
def команда_ping(args) -> int:
    pings = _замерить(args)
    if not pings:
        return 1
    закрытые = blocklist.blocked()
    if args.json:
        _как_json(pings, закрытые)
        return 0
    _таблица(pings, закрытые, args)
    ближний = relays.nearest(pings)
    if ближний is None:
        print("\nНе ответил ни один сервер. Так бывает, когда связь "
              "перекрыта целиком — загляни в брандмауэр.")
        return 1
    print(f"\nБлиже всего {ближний.cluster.name} — {ближний.ms:.0f} мс.")
    return 0


def команда_status(args) -> int:
    закрытые = blocklist.blocked()
    if args.json:
        print(json.dumps({"blocked": sorted(закрытые),
                          "admin": running_as_admin()},
                         ensure_ascii=False, indent=2))
        return 0
    if not закрытые:
        print("Ничего не закрыто — моих правил в брандмауэре нет.")
    else:
        print(f"Закрыто: {servers(len(закрытые))} — "
              f"{', '.join(sorted(закрытые))}.")
    if not running_as_admin():
        print("Прав администратора нет: смотреть можно, менять нельзя.")
    return 0


def команда_block(args) -> int:
    """Закрыть названные кластеры. Без --yes только показывает."""
    pings = _замерить(args)
    if not pings:
        return 1
    среди = [p.cluster for p in pings]
    ближний = relays.nearest(pings)
    выбор = set(args.codes)

    беда = blocklist.check(выбор, среди,
                           ближний.cluster.code if ближний else None)
    if беда:
        print(беда, file=sys.stderr)
        return 2

    имена = {c.code: c.name for c in среди}
    осталось = len(среди) - len(выбор)
    это = plural(len(выбор), "вот этот", "вот эти", "вот эти")
    print(f"\nЗакрою {это}:")
    for code in sorted(выбор):
        print(f"  {code:<6} {имена[code]}")
    print(f"Открытым останется {servers(осталось)}. Чем больше "
          f"закрыто, тем дольше ищется матч.")

    if not args.yes:
        print("\nПока ничего не сделано. Если всё верно — добавь --yes.")
        return 0
    if not running_as_admin():
        print("\nНужны права администратора, спрашиваю…")
        отказ = relaunch_as_admin()
        if отказ:
            print(отказ, file=sys.stderr)
            return 3
        print("Открыл второе окно с правами — продолжай в нём.")
        return 0

    отказ = blocklist.apply(выбор, среди,
                            ближний.cluster.code if ближний else None)
    if отказ:
        print(отказ, file=sys.stderr)
        return 3
    print(f"\nГотово, закрыл {servers(len(выбор))}. Перезапусти поиск "
          f"матча, чтобы игра замерила заново.")
    return 0


def команда_unblock(args) -> int:
    """Снять всё наше. Чужих правил не трогает."""
    if not running_as_admin():
        print("Нужны права администратора, спрашиваю…")
        отказ = relaunch_as_admin()
        if отказ:
            print(отказ, file=sys.stderr)
            return 3
        print("Открыл второе окно с правами — продолжай в нём.")
        return 0
    отказ = blocklist.clear()
    if отказ:
        print(отказ, file=sys.stderr)
        return 3
    print("Открыл всё обратно. Убрал только свои правила — то, что ты "
          "настраивал в брандмауэре раньше, на месте.")
    return 0


def команда_gui(_args) -> int:
    from .gui import run  # noqa: PLC0415 - tkinter грузится только для окна

    return run()


# --------------------------------------------------------------- разбор
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="deadlock-lobby-fix",
        description="Показывает, за сколько ты дозваниваешься до "
                    "серверов Valve, и даёт закрыть те, где играть не "
                    "хочешь. Без команды открывает окно.")
    ap.add_argument("--debug", action="store_true",
                    help="рассказывать, что происходит внутри")
    дальше = ap.add_subparsers(dest="command")

    def общее(под):
        под.add_argument("--json", action="store_true",
                         help="ответ в JSON — если разбираешь скриптом")
        под.add_argument("--no-color", action="store_true",
                         help="без цвета, даже если терминал его умеет")
        return под

    общее(дальше.add_parser(
        "ping", help="замерить пинг до всех серверов")
    ).set_defaults(func=команда_ping)

    общее(дальше.add_parser(
        "status", help="посмотреть, что закрыто сейчас")
    ).set_defaults(func=команда_status)

    закрыть = общее(дальше.add_parser(
        "block", help="закрыть названные серверы (коды берутся из ping)"))
    закрыть.add_argument("codes", nargs="+", metavar="КОД",
                         help="коды серверов, например syd tyo gru")
    закрыть.add_argument("--yes", action="store_true",
                         help="сделать, а не только показать")
    закрыть.set_defaults(func=команда_block)

    общее(дальше.add_parser(
        "unblock", help="открыть всё обратно")
    ).set_defaults(func=команда_unblock)

    общее(дальше.add_parser(
        "gui", help="открыть окно")
    ).set_defaults(func=команда_gui)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s")
    if getattr(args, "func", None) is None:
        # Без команды -- окно: тот, кто запустил двойным щелчком, команду
        # не вводил и вводить не собирался.
        return команда_gui(args)
    return args.func(args)
