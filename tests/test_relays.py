"""Пинг до релеев Valve.

Главное свойство этого расчёта -- он не выдаёт молчание за ноль. Узел, не
ответивший на запрос, это «неизвестно», а не «нулевая задержка», и если
спутать одно с другим, он встанет первым в списке ближайших -- то есть
программа посоветует играть там, куда вообще не достучалась.

Ни один тест не стучит в сеть: вместо `urllib` подставляется готовый
ответ, вместо PowerShell -- функция, возвращающая строку.
"""
from __future__ import annotations

from deadlock_lobby_fix import relays

КОНФИГ = {"pops": {
    "ams": {"desc": "Amsterdam (Netherlands)",
            "relays": [{"ipv4": "1.1.1.1"}, {"ipv4": "1.1.1.2"}]},
    "syd": {"desc": "Sydney (Australia)", "relays": [{"ipv4": "2.2.2.2"}]},
    "xyz": {"desc": "Служебный", "relays": []},
}}


# --------------------------------------------------------- список Valve
def test_clusters_come_with_names_and_addresses():
    got = relays.clusters(fetch=lambda: КОНФИГ)
    assert [c.code for c in got] == ["ams", "syd"]
    assert got[0].name == "Amsterdam (Netherlands)"
    assert got[0].ips == ("1.1.1.1", "1.1.1.2")


def test_a_cluster_without_addresses_is_skipped():
    """Служебный кластер пинговать нечем."""
    assert "xyz" not in [c.code for c in relays.clusters(fetch=lambda: КОНФИГ)]


def test_no_answer_from_valve_is_not_a_crash():
    """Сети нет -- это ответ, а не падение: окну есть что сказать."""
    def сломалось():
        raise OSError("сеть недоступна")

    assert relays.clusters(fetch=сломалось) == []


def test_a_changed_format_is_not_a_crash():
    """Valve вправе сменить формат, и падать на этом нельзя."""
    assert relays.clusters(fetch=lambda: {}) == []
    assert relays.clusters(fetch=lambda: {"pops": None}) == []


# ---------------------------------------------------------------- замер
def test_the_nearest_comes_first():
    got = _замер({"1.1.1.1": "80", "2.2.2.2": "290"})
    assert [p.cluster.code for p in got] == ["ams", "syd"]


def test_a_silent_relay_goes_last_not_first():
    """Иначе молчащий узел притворится самым близким."""
    got = _замер({"1.1.1.1": "", "2.2.2.2": "290"})
    assert [p.cluster.code for p in got] == ["syd", "ams"]
    assert got[-1].ms is None


def test_a_comma_decimal_is_understood():
    """На русской системе PowerShell печатает 83,5 вместо 83.5."""
    got = relays.measure(relays.clusters(fetch=lambda: КОНФИГ),
                         run=lambda _cmd: "83,5")
    assert got[0].ms == 83.5


def test_a_broken_answer_counts_as_silence():
    got = relays.measure(relays.clusters(fetch=lambda: КОНФИГ),
                         run=lambda _cmd: "Test-Connection: узел не найден")
    assert all(p.ms is None for p in got)


def test_a_thrown_error_counts_as_silence():
    """PowerShell может и не запуститься -- это тоже «неизвестно»."""
    def взрыв(_cmd):
        raise OSError("powershell не найден")

    got = relays.measure(relays.clusters(fetch=lambda: КОНФИГ), run=взрыв)
    assert all(p.ms is None for p in got)


def test_nothing_to_measure_is_not_an_error():
    assert relays.measure([]) == []


def test_only_the_first_address_is_asked():
    """Релеи одного кластера стоят в одной стойке: второй адрес ничего не
    добавит, а время замера удвоит."""
    спрошено = []
    relays.measure(relays.clusters(fetch=lambda: КОНФИГ),
                   run=lambda cmd: спрошено.append(cmd) or "50")
    assert any("1.1.1.1" in c for c in спрошено)
    assert not any("1.1.1.2" in c for c in спрошено)


def test_progress_is_reported():
    """Девять секунд без признаков жизни выглядят как зависшее окно."""
    шаги = []
    relays.measure(relays.clusters(fetch=lambda: КОНФИГ),
                   run=lambda _cmd: "50", at_once=1,
                   progress=lambda сделано, всего: шаги.append((сделано, всего)))
    assert шаги == [(1, 2), (2, 2)]


# -------------------------------------------------------------- вердикт
def test_the_verdict_matches_the_number():
    ams, syd = relays.clusters(fetch=lambda: КОНФИГ)
    assert relays.Ping(ams, 40).good
    assert not relays.Ping(ams, 40).bad
    assert relays.Ping(syd, 290).bad
    assert relays.Ping(syd, None).bad


def test_silence_is_its_own_verdict():
    """«Молчит» -- это не «плохо»: неизвестность, а не плохой пинг. Иначе
    раскраска соврёт, что узел измерен и оказался далёким."""
    ams = relays.clusters(fetch=lambda: КОНФИГ)[0]
    assert relays.Ping(ams, None).verdict == "молчит"
    assert relays.Ping(ams, 300).verdict == "плохо"
    assert relays.Ping(ams, 90).verdict == "терпимо"
    assert relays.Ping(ams, 20).verdict == "хорошо"


def test_all_four_verdicts_differ():
    """Четыре исхода -- четыре слова, иначе красить не по чему."""
    ams = relays.clusters(fetch=lambda: КОНФИГ)[0]
    слова = {relays.Ping(ams, ms).verdict for ms in (20, 90, 300, None)}
    assert len(слова) == 4


# ------------------------------------------------------------- ближайший
def test_the_nearest_skips_the_silent():
    ams, syd = relays.clusters(fetch=lambda: КОНФИГ)
    найден = relays.nearest([relays.Ping(ams, None), relays.Ping(syd, 200)])
    assert найден.cluster.code == "syd"


def test_without_answers_there_is_no_nearest():
    ams = relays.clusters(fetch=lambda: КОНФИГ)[0]
    assert relays.nearest([]) is None
    assert relays.nearest([relays.Ping(ams, None)]) is None


# --------------------------------------------------------------- помощь
def _замер(ответы: dict):
    return relays.measure(
        relays.clusters(fetch=lambda: КОНФИГ),
        run=lambda cmd: next(v for k, v in ответы.items() if k in cmd))
