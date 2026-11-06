"""Числа словами и согласование с ними."""
from __future__ import annotations

СЛОВОМ_ДО = 10

ЧИСЛА = ("ноль", "один", "два", "три", "четыре", "пять",
         "шесть", "семь", "восемь", "девять", "десять")

ЖЕНСКИЕ = {1: "одна", 2: "две"}


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма слова при числе n. Само число не подставляется."""
    n = abs(int(n))
    хвост, сотня = n % 10, n % 100
    if 11 <= сотня <= 14:
        return many
    if хвост == 1:
        return one
    if хвост in (2, 3, 4):
        return few
    return many


def spelled(n: int, female: bool = False) -> str:
    """Маленькое число словом, большое -- цифрой."""
    n = int(n)
    if 0 <= n <= СЛОВОМ_ДО:
        if female and n in ЖЕНСКИЕ:
            return ЖЕНСКИЕ[n]
        return ЧИСЛА[n]
    return str(n)


def count(n: int, one: str, few: str, many: str, female: bool = False) -> str:
    """Число со словом, как сказал бы человек: «четыре сервера»."""
    return f"{spelled(n, female)} {plural(n, one, few, many)}"


def servers(n: int) -> str:
    """Самое частое сочетание в этой программе."""
    return count(n, "сервер", "сервера", "серверов")
