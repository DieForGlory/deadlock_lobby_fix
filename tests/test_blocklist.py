"""Закрытие кластеров брандмауэром.

Опасность здесь не в блокировке, а в переборе: закрыв слишком много,
человек не найдёт матч вовсе, и выглядеть это будет как «программа сломала
игру». Поэтому предохранители проверяются подробнее, чем сама работа.

Ни один тест не трогает настоящий брандмауэр: вместо запуска команд
подставляется запись того, что было бы запущено.
"""
from __future__ import annotations

from dataclasses import dataclass

from deadlock_lobby_fix import blocklist


@dataclass(frozen=True)
class Узел:
    code: str
    ips: tuple = ("1.2.3.4",)


ВСЕ = [Узел(c) for c in
       ("ams", "fra", "sto", "waw", "lhr", "par", "iad", "dfw", "syd", "tyo")]


class Запись:
    """Запоминает команды вместо того, чтобы их выполнять."""

    def __init__(self, admin=True, answers=None):
        self.команды = []
        self.admin = admin
        self.answers = answers or {}

    def __call__(self, command: str) -> str:
        self.команды.append(command)
        if "IsInRole" in command:
            return "True" if self.admin else "False"
        for ключ, ответ in self.answers.items():
            if ключ in command:
                return ответ
        return ""


# ------------------------------------------------------- предохранители
def test_the_nearest_cluster_cannot_be_closed():
    беда = blocklist.check({"ams"}, ВСЕ, nearest="ams")
    assert "Ближайший сервер закрывать нельзя" in беда


def test_closing_too_many_is_refused():
    """Открытыми обязано остаться хотя бы пять."""
    много = {u.code for u in ВСЕ[:7]}
    assert "останется" in blocklist.check(много, ВСЕ, nearest=None)


def test_exactly_keep_open_left_is_allowed():
    """Граница включительно: пять открытых -- ещё можно."""
    сколько = len(ВСЕ) - blocklist.KEEP_OPEN
    assert blocklist.check({u.code for u in ВСЕ[:сколько]}, ВСЕ) == ""


def test_an_unknown_cluster_is_refused():
    """Опечатка в коде не должна молча закрыть не то."""
    беда = blocklist.check({"луна"}, ВСЕ)
    assert "луна" in беда and "нет" in беда


def test_a_sensible_choice_passes():
    assert blocklist.check({"syd", "tyo"}, ВСЕ, nearest="ams") == ""


def test_closing_nothing_is_allowed():
    """Пустой выбор -- это «открыть всё», и запрещать его незачем."""
    assert blocklist.check(set(), ВСЕ, nearest="ams") == ""


def test_the_guard_runs_before_anything_is_changed():
    """Отказ обязан случиться до первой команды, а не на середине."""
    запись = Запись()
    беда = blocklist.apply({u.code for u in ВСЕ[:8]}, ВСЕ, run=запись)
    assert беда and запись.команды == []


# ------------------------------------------------------------- права
def test_without_admin_rights_nothing_is_attempted():
    запись = Запись(admin=False)
    беда = blocklist.apply({"syd"}, ВСЕ, nearest="ams", run=запись)
    assert "администратора" in беда
    assert not any("New-NetFirewallRule" in c for c in запись.команды)


# ------------------------------------------------------------- работа
def test_both_directions_are_closed():
    """Одного направления мало: ответ может прийти по открытому пути."""
    запись = Запись()
    assert blocklist.apply({"syd"}, ВСЕ, nearest="ams", run=запись) == ""
    правила = [c for c in запись.команды if "New-NetFirewallRule" in c]
    assert len(правила) == 2
    assert any("Outbound" in c for c in правила)
    assert any("Inbound" in c for c in правила)


def test_old_rules_go_before_new_ones():
    """Набор правил описывает выбор человека, а не историю его нажатий."""
    запись = Запись()
    blocklist.apply({"syd"}, ВСЕ, nearest="ams", run=запись)
    снятие = next(i for i, c in enumerate(запись.команды)
                  if "Remove-NetFirewallRule" in c)
    постановка = next(i for i, c in enumerate(запись.команды)
                      if "New-NetFirewallRule" in c)
    assert снятие < постановка


def test_only_our_own_rules_are_touched():
    """Человек мог настроить брандмауэр задолго до нас."""
    запись = Запись()
    blocklist.clear(run=запись)
    assert all(blocklist.MARK in c for c in запись.команды
               if "FirewallRule" in c)


def test_every_rule_carries_the_mark():
    """По метке они и снимаются. Правило без неё останется навсегда."""
    запись = Запись()
    blocklist.apply({"syd", "tyo"}, ВСЕ, nearest="ams", run=запись)
    for команда in запись.команды:
        if "New-NetFirewallRule" in команда:
            assert f"'{blocklist.MARK}-" in команда


def test_a_broken_powershell_is_reported_not_raised():
    """Окно должно сказать, а не упасть."""
    def взрыв(_cmd):
        raise OSError("powershell не найден")

    беда = blocklist.clear(run=взрыв)
    assert "не снялись" in беда and "powershell не найден" in беда


# ------------------------------------------------------------ чтение
def test_what_is_closed_is_read_back():
    запись = Запись(answers={"Get-NetFirewallRule":
                             '["DeadlockLobbyFix-relay-Outbound-syd",'
                             ' "DeadlockLobbyFix-relay-Inbound-syd"]'})
    assert blocklist.blocked(run=запись) == {"syd"}


def test_a_single_rule_reads_back_too():
    """PowerShell отдаёт одну строку без скобок списка."""
    запись = Запись(answers={"Get-NetFirewallRule":
                             '"DeadlockLobbyFix-relay-Outbound-tyo"'})
    assert blocklist.blocked(run=запись) == {"tyo"}


def test_nothing_closed_reads_as_nothing():
    пусто = Запись(answers={"Get-NetFirewallRule": ""})
    assert blocklist.blocked(run=пусто) == set()


def test_only_our_rules_are_listed():
    """Запрос идёт по нашей метке: чужих правил мы не перечисляем."""
    запись = Запись()
    blocklist.blocked(run=запись)
    assert all(blocklist.MARK in c for c in запись.команды)
