"""Командная строка.

Здесь проверяется одно главное свойство: `block` без `--yes` не трогает
брандмауэр. Программа, которая правит правила сети, обязана сначала
показать, что собирается сделать, -- иначе человек узнаёт о своём выборе
по тому, что перестал находить матчи.

И второе: отказ предохранителя должен случиться до первой команды и дать
ненулевой код возврата, чтобы скрипт мог на него опереться.
"""
from __future__ import annotations

import json

import pytest

from deadlock_lobby_fix import blocklist, cli, relays

КОНФИГ = {"pops": {
    code: {"desc": f"Город {code}", "relays": [{"ipv4": f"10.0.0.{n}"}]}
    for n, code in enumerate(
        ("ams", "fra", "sto", "waw", "lhr", "par", "iad", "dfw", "syd",
         "tyo"), start=1)
}}


@pytest.fixture()
def мир(monkeypatch):
    """Сеть, PowerShell и брандмауэр -- все подставные."""
    поставлено = {"правила": [], "снято": 0, "admin": True}

    # Список берём до подмены: подменённая `clusters` звала бы саму себя.
    готовые = relays.clusters(fetch=lambda: КОНФИГ)
    monkeypatch.setattr(relays, "clusters", lambda fetch=None: готовые)
    monkeypatch.setattr(
        relays, "measure",
        lambda где, **_k: [relays.Ping(c, 30.0 + 20 * n)
                           for n, c in enumerate(где)])
    monkeypatch.setattr(blocklist, "blocked", lambda run=None: set())
    monkeypatch.setattr(cli, "running_as_admin", lambda: поставлено["admin"])

    def _поставить(codes, among, nearest=None, run=None):
        поставлено["правила"] = sorted(codes)
        return ""

    def _снять(run=None):
        поставлено["снято"] += 1
        return ""

    monkeypatch.setattr(blocklist, "apply", _поставить)
    monkeypatch.setattr(blocklist, "clear", _снять)
    return поставлено


# ------------------------------------------------------------ замер
def test_ping_prints_every_cluster(мир, capsys):
    assert cli.main(["ping"]) == 0
    напечатано = capsys.readouterr().out
    for код in ("ams", "syd", "tyo"):
        assert код in напечатано
    assert "Ближе всего" in напечатано


def test_ping_as_json_is_parseable(мир, capsys):
    assert cli.main(["ping", "--json"]) == 0
    разобрано = json.loads(capsys.readouterr().out)
    assert len(разобрано) == 10
    assert разобрано[0]["code"] == "ams"
    assert разобрано[0]["ms"] == 30.0
    assert разобрано[0]["verdict"] == "хорошо"


def test_no_network_is_an_error_code(monkeypatch, capsys):
    monkeypatch.setattr(relays, "clusters", lambda fetch=None: [])
    assert cli.main(["ping"]) == 1


# ------------------------------------------------------------ закрытие
def test_block_without_yes_changes_nothing(мир, capsys):
    """Предпросмотр -- это предпросмотр."""
    assert cli.main(["block", "syd", "tyo"]) == 0
    assert мир["правила"] == []
    напечатано = capsys.readouterr().out
    assert "Пока ничего не сделано" in напечатано
    assert "--yes" in напечатано


def test_block_with_yes_puts_the_rules(мир):
    assert cli.main(["block", "syd", "tyo", "--yes"]) == 0
    assert мир["правила"] == ["syd", "tyo"]


def test_blocking_the_nearest_is_refused(мир, capsys):
    """Ближайший -- ams: он первый по пингу."""
    assert cli.main(["block", "ams", "--yes"]) == 2
    assert мир["правила"] == []
    assert "Ближайший сервер" in capsys.readouterr().err


def test_blocking_too_many_is_refused(мир, capsys):
    много = ["fra", "sto", "waw", "lhr", "par", "iad", "dfw"]
    assert cli.main(["block", *много, "--yes"]) == 2
    assert мир["правила"] == []
    assert "останется" in capsys.readouterr().err.lower()


def test_an_unknown_code_is_refused(мир, capsys):
    assert cli.main(["block", "луна", "--yes"]) == 2
    assert мир["правила"] == []


def test_without_admin_nothing_is_written(мир, monkeypatch, capsys):
    """Запрос прав вместо тихого отказа -- и правил при этом не ставим."""
    мир["admin"] = False
    monkeypatch.setattr(cli, "relaunch_as_admin", lambda *a, **k: "")
    assert cli.main(["block", "syd", "--yes"]) == 0
    assert мир["правила"] == []


# ------------------------------------------------------------ снятие
def test_unblock_clears_the_rules(мир):
    assert cli.main(["unblock"]) == 0
    assert мир["снято"] == 1


def test_unblock_without_admin_asks_instead_of_failing(мир, monkeypatch):
    мир["admin"] = False
    monkeypatch.setattr(cli, "relaunch_as_admin", lambda *a, **k: "")
    assert cli.main(["unblock"]) == 0
    assert мир["снято"] == 0


# ------------------------------------------------------------ состояние
def test_status_says_what_is_closed(мир, monkeypatch, capsys):
    monkeypatch.setattr(blocklist, "blocked", lambda run=None: {"syd", "tyo"})
    assert cli.main(["status"]) == 0
    напечатано = capsys.readouterr().out
    assert "syd" in напечатано and "tyo" in напечатано


def test_status_as_json(мир, monkeypatch, capsys):
    monkeypatch.setattr(blocklist, "blocked", lambda run=None: {"syd"})
    assert cli.main(["status", "--json"]) == 0
    разобрано = json.loads(capsys.readouterr().out)
    assert разобрано["blocked"] == ["syd"]


# -------------------------------------------------------------- разбор
def test_no_command_opens_the_window(monkeypatch):
    """Запустивший двойным щелчком команду не вводил."""
    открыто = []
    monkeypatch.setattr(cli, "команда_gui",
                        lambda _args: открыто.append(True) or 0)
    assert cli.main([]) == 0
    assert открыто == [True]


def test_every_command_is_listed_in_help(capsys):
    парсер = cli.build_parser()
    текст = парсер.format_help()
    for команда in ("ping", "status", "block", "unblock", "gui"):
        assert команда in текст


# --------------------------------------------------- как это читается
def test_counts_agree_with_their_nouns(мир, capsys):
    """«Закрою 1 серверов» -- первое, по чему видно машину.

    Проверяется на числе, которое ломает наивное правило «по последней
    цифре»: у 1 форма «сервер», и строка обязана это знать.
    """
    cli.main(["block", "syd", "--yes"])
    напечатано = capsys.readouterr().out
    assert "один сервер" in напечатано
    assert "1 сервер" not in напечатано


def test_counts_are_spelled_out_while_they_are_small(мир, capsys):
    cli.main(["block", "syd", "tyo", "--yes"])
    assert "два сервера" in capsys.readouterr().out


def test_a_refusal_is_a_whole_sentence(мир, capsys):
    """Отказ печатается целой фразой, без служебной приставки.

    Иначе человек читает «Так нельзя: Ближайший сервер закрывать
    нельзя» -- одно и то же дважды, и вторая половина звучит как
    сообщение системы, а не как ответ.
    """
    cli.main(["block", "ams", "--yes"])
    # Первая строка stderr -- про замер; отказ идёт последним.
    отказ = capsys.readouterr().err.strip().splitlines()[-1]
    assert отказ.startswith("Ближайший сервер")
    assert отказ.endswith(".")
    for приставка in ("Ошибка", "Так нельзя", "ERROR", "Не вышло"):
        assert приставка not in отказ
