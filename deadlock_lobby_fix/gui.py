"""Окно: таблица пинга и галки «здесь не играть».

Почему tkinter
--------------
Он идёт в самом Python. Человеку, который пришёл чинить пинг, не придётся
ставить ни Qt, ни колёса на сто мегабайт -- скачал, запустил, увидел числа.
Для таблички с числами и десятком галок этого хватает с запасом, а каждая
лишняя зависимость в программе, которую советуют друг другу в чате, -- это
ещё один способ до неё не добраться.

Почему галки заперты до замера
------------------------------
Закрывать кластеры вслепую -- верный способ остаться без матча. Сперва
цифры, потом решение. И ближайший заперт прямо в списке, с объяснением на
месте: отказать после нажатия «Применить» было бы честно, но поздно.

Про нити
--------
Замер идёт в стороне от окна: тридцать три кластера -- это девять секунд, и
всё это время окно не должно выглядеть повисшим. Tkinter не терпит
обращений из чужой нити, поэтому назад результат приходит через
`after(0, ...)` -- то есть уже в нити окна.
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk

from . import blocklist, relays
from .elevate import relaunch_as_admin, running_as_admin
from .words import servers

log = logging.getLogger(__name__)

# Тёмное, потому что рядом игра, а не таблица в офисе. Цвета вердикта
# заведены здесь же: тут цвет -- это данные, годится кластер или нет, а не
# оформление, и подбирались они так, чтобы «терпимо» и «плохо» различались
# с одного взгляда.
ФОН = "#14161c"
ПАНЕЛЬ = "#1b1e26"
ТЕКСТ = "#d8dce6"
ТУСКЛО = "#8a90a0"
ХОРОШО = "#6fbf73"
ТЕРПИМО = "#d9a441"
ПЛОХО = "#e0714f"

ЦВЕТ = {"хорошо": ХОРОШО, "терпимо": ТЕРПИМО,
        "плохо": ПЛОХО, "молчит": ТУСКЛО}


class Окно:
    """Всё окно целиком. Состояние -- замеры и галки, больше ничего."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.pings: list[relays.Ping] = []
        self.галки: dict[str, tk.BooleanVar] = {}
        self.занято = False

        root.title("Deadlock: пинг до серверов")
        root.configure(bg=ФОН)
        root.minsize(700, 620)
        _тёмный_заголовок(root)

        self._шапка()
        self._кнопки()
        self._строка_состояния()
        self._список()
        self._подвал()
        self._обновить_состояние()

    # ------------------------------------------------------------ сборка
    def _шапка(self) -> None:
        tk.Label(self.root, text="Куда тебя может закинуть", bg=ФОН,
                 fg=ТЕКСТ, font=("Segoe UI", 15, "bold"), anchor="w"
                 ).pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(
            self.root, bg=ФОН, fg=ТУСКЛО, justify="left", anchor="w",
            wraplength=640, font=("Segoe UI", 9),
            text="Регион в Deadlock не выбирается. Игра сама смотрит, до "
                 "каких серверов Valve ты дозваниваешься быстрее, и по "
                 "этому решает, где тебе играть. Вот те же числа, что "
                 "видит она."
        ).pack(fill="x", padx=16, pady=(0, 8))

    def _кнопки(self) -> None:
        ряд = tk.Frame(self.root, bg=ФОН)
        ряд.pack(fill="x", padx=16)
        self.кнопка_замера = self._кнопка(ряд, "Замерить пинг", self.замерить)
        self.кнопка_применить = self._кнопка(ряд, "Закрыть отмеченные",
                                             self.применить)
        self.кнопка_снять = self._кнопка(ряд, "Открыть всё обратно",
                                         self.снять)
        self.кнопка_прав = self._кнопка(ряд, "Запросить права",
                                        self.спросить_права)
        self.кнопка_применить.configure(state="disabled")

    def _кнопка(self, где, текст, действие) -> tk.Button:
        кнопка = tk.Button(где, text=текст, command=действие, bg=ПАНЕЛЬ,
                           fg=ТЕКСТ, activebackground="#272b36",
                           activeforeground=ТЕКСТ, relief="flat",
                           padx=12, pady=6, font=("Segoe UI", 9),
                           cursor="hand2", borderwidth=0,
                           disabledforeground=ТУСКЛО)
        кнопка.pack(side="left", padx=(0, 8))
        return кнопка

    def _строка_состояния(self) -> None:
        self.состояние = tk.Label(
            self.root, bg=ФОН, fg=ТУСКЛО, justify="left", anchor="w",
            wraplength=640, font=("Segoe UI", 9),
            text="Нажми «Замерить пинг». Займёт секунд десять — спрашиваю "
                 "все сразу.")
        self.состояние.pack(fill="x", padx=16, pady=(10, 6))

    def _список(self) -> None:
        """Прокручиваемый список кластеров: холст с рамкой внутри."""
        коробка = tk.Frame(self.root, bg=ПАНЕЛЬ)
        коробка.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self.холст = tk.Canvas(коробка, bg=ПАНЕЛЬ, highlightthickness=0)
        полоса = tk.Scrollbar(коробка, orient="vertical",
                              command=self.холст.yview)
        self.холст.configure(yscrollcommand=полоса.set)
        полоса.pack(side="right", fill="y")
        self.холст.pack(side="left", fill="both", expand=True)

        self.строки = tk.Frame(self.холст, bg=ПАНЕЛЬ)
        окошко = self.холст.create_window((0, 0), window=self.строки,
                                          anchor="nw")
        self.строки.bind(
            "<Configure>",
            lambda _e: self.холст.configure(
                scrollregion=self.холст.bbox("all")))
        # Внутренняя рамка должна быть шириной с холст, иначе числа справа
        # прижмутся к тексту вместо правого края.
        self.холст.bind(
            "<Configure>",
            lambda e: self.холст.itemconfigure(окошко, width=e.width))
        self.холст.bind_all("<MouseWheel>", self._колесо)

        self.пусто = tk.Label(self.строки, bg=ПАНЕЛЬ, fg=ТУСКЛО,
                              font=("Segoe UI", 9), anchor="w",
                              text="  Серверы появятся здесь после "
                                   "замера.")
        self.пусто.pack(fill="x", pady=10)

    def _колесо(self, event) -> None:
        self.холст.yview_scroll(int(-event.delta / 120), "units")

    def _подвал(self) -> None:
        for текст in (
            "Закрываю правилами брандмауэра Windows — для них нужны права "
            "администратора. Саму игру не трогаю: ни файлов, ни памяти. "
            "«Открыть всё обратно» убирает только мои правила; то, что ты "
            "настраивал в брандмауэре раньше, остаётся как было.",
            "Чем больше закрыто, тем дольше ищется матч — это цена, а не "
            "поломка. Ближайший сервер закрыть не дам, и хотя бы пять "
            "должны остаться открытыми, иначе матч не найдётся вовсе.",
            "Список серверов Valve меняет. Новый датацентр будет открыт, "
            "пока не замеришь и не закроешь его заново.",
        ):
            tk.Label(self.root, text=текст, bg=ФОН, fg=ТУСКЛО,
                     justify="left", anchor="w", wraplength=640,
                     font=("Segoe UI", 8)).pack(fill="x", padx=16,
                                                pady=(0, 4))
        tk.Frame(self.root, bg=ФОН, height=8).pack()

    # ------------------------------------------------------------ помощь
    def сказать(self, текст: str) -> None:
        self.состояние.configure(text=текст)

    @property
    def ближний(self) -> str | None:
        найден = relays.nearest(self.pings)
        return найден.cluster.code if найден else None

    def _обновить_состояние(self) -> None:
        """Кнопку прав показываем только пока прав нет."""
        if running_as_admin():
            self.кнопка_прав.pack_forget()

    # ------------------------------------------------------------- замер
    def замерить(self) -> None:
        if self.занято:
            return
        self.занято = True
        self.кнопка_замера.configure(state="disabled")
        self.сказать("Спрашиваю серверы…")
        threading.Thread(target=self._мерить, daemon=True,
                         name="deadlock-lobby-fix: замер").start()

    def _мерить(self) -> None:
        """Нить замера. В окно отсюда не лезем -- только через after."""
        try:
            где = relays.clusters()
            итог = (relays.measure(где), blocklist.blocked()) if где else None
        except Exception as exc:  # noqa: BLE001 - окно скажет, а не упадёт
            log.info("замер не вышел: %s", exc)
            self.root.after(0, self._замер_не_вышел, str(exc))
            return
        self.root.after(0, self._замерено, итог)

    def _замер_не_вышел(self, почему: str) -> None:
        self.занято = False
        self.кнопка_замера.configure(state="normal")
        self.сказать(f"Замер сорвался: {почему}")

    def _замерено(self, итог) -> None:
        self.занято = False
        self.кнопка_замера.configure(state="normal")
        if not итог:
            self.сказать("Valve не ответила — похоже, сети нет. Проверь "
                         "и попробуй ещё раз.")
            return
        self.pings, закрытые = итог
        self._нарисовать(закрытые)
        ближний = relays.nearest(self.pings)
        if ближний is None:
            self.сказать("Не ответил ни один сервер. Так бывает, когда "
                         "связь перекрыта целиком — загляни в брандмауэр.")
            return
        self.сказать(f"Ближе всего {ближний.cluster.name} — "
                     f"{ближний.ms:.0f} мс. Отметь, где играть не хочешь, "
                     f"и жми «Закрыть отмеченные».")
        self.кнопка_применить.configure(state="normal")

    def _нарисовать(self, закрытые: set[str]) -> None:
        for виджет in self.строки.winfo_children():
            виджет.destroy()
        self.галки = {}
        ближний = self.ближний
        for ping in self.pings:
            строка = tk.Frame(self.строки, bg=ПАНЕЛЬ)
            строка.pack(fill="x", padx=8, pady=1)

            держит = tk.BooleanVar(value=ping.cluster.code in закрытые)
            галка = tk.Checkbutton(
                строка, text=ping.cluster.name, variable=держит, bg=ПАНЕЛЬ,
                fg=ТЕКСТ, selectcolor=ФОН, activebackground=ПАНЕЛЬ,
                activeforeground=ТЕКСТ, anchor="w", font=("Segoe UI", 9),
                highlightthickness=0, borderwidth=0,
                disabledforeground=ТУСКЛО)
            if ping.cluster.code == ближний:
                # Ближайший заперт прямо здесь: объяснить это на месте
                # честнее, чем отказом после нажатия «Применить».
                галка.configure(state="disabled",
                                text=f"{ping.cluster.name}  — ближе всех")
            галка.pack(side="left", fill="x", expand=True)
            self.галки[ping.cluster.code] = держит

            число = (f"{ping.ms:.0f} мс" if ping.ms is not None
                     else "молчит")
            tk.Label(строка, text=число, bg=ПАНЕЛЬ,
                     fg=ЦВЕТ.get(ping.verdict, ТУСКЛО),
                     font=("Segoe UI", 9, "bold"), width=11, anchor="e"
                     ).pack(side="right")

    # ----------------------------------------------------------- правила
    def _выбор(self) -> set[str]:
        ближний = self.ближний
        return {code for code, держит in self.галки.items()
                if держит.get() and code != ближний}

    def применить(self) -> None:
        if self.занято or not self.pings:
            return
        среди = [p.cluster for p in self.pings]
        выбор = self._выбор()
        # Проверяем до первой команды, а не после: отказ на середине
        # оставил бы половину правил поставленными.
        беда = blocklist.check(выбор, среди, self.ближний)
        if беда:
            self.сказать(беда)
            return
        if not running_as_admin():
            self.сказать("Для этого нужны права администратора. Жми "
                         "«Запросить права» — откроется второе окно, "
                         "дальше работай в нём.")
            return
        self.занято = True
        self.кнопка_применить.configure(state="disabled")
        self.сказать("Закрываю…")
        threading.Thread(
            target=self._ставить, args=(выбор, среди), daemon=True,
            name="deadlock-lobby-fix: правила").start()

    def _ставить(self, выбор, среди) -> None:
        беда = blocklist.apply(выбор, среди, self.ближний)
        self.root.after(0, self._поставлено, беда, len(выбор))

    def _поставлено(self, беда: str, сколько: int) -> None:
        self.занято = False
        self.кнопка_применить.configure(state="normal")
        if беда:
            self.сказать(беда)
            return
        if not сколько:
            self.сказать("Все серверы открыты — закрывать было нечего.")
            return
        self.сказать(f"Готово, закрыл {servers(сколько)}. Перезапусти поиск "
                     f"матча, чтобы игра замерила заново.")

    def снять(self) -> None:
        if self.занято:
            return
        if not running_as_admin():
            self.сказать("Для этого нужны права администратора. Жми "
                         "«Запросить права» — откроется второе окно, "
                         "дальше работай в нём.")
            return
        self.занято = True
        self.сказать("Открываю обратно…")
        threading.Thread(target=self._снимать, daemon=True,
                         name="deadlock-lobby-fix: снятие").start()

    def _снимать(self) -> None:
        беда = blocklist.clear()
        self.root.after(0, self._снято, беда)

    def _снято(self, беда: str) -> None:
        self.занято = False
        for держит in self.галки.values():
            держит.set(False)
        self.сказать(беда if беда else
                     "Открыл всё обратно. Убрал только свои правила — то, "
                     "что ты настраивал в брандмауэре раньше, на месте.")

    def спросить_права(self) -> None:
        """Перезапустить себя через UAC. Нынешнее окно человек закроет сам.

        Сам не закрываюсь намеренно: если в UAC нажмут «Нет», человек
        останется вообще без окна и без объяснения, почему оно исчезло.
        """
        отказ = relaunch_as_admin()
        if отказ:
            self.сказать(отказ)
            return
        self.сказать("Открыл второе окно, уже с правами — дальше в нём. "
                     "Это можно закрывать.")


def _тёмный_заголовок(root) -> None:
    """Попросить Windows покрасить рамку окна в тёмное.

    Иначе получается светлая системная полоса над тёмным окном -- вид
    незаконченной программы. Работает с Windows 10 1809 и новее; где не
    работает, тихо ничего не делает, и это не повод о чём-то сообщать.
    """
    try:
        import ctypes  # noqa: PLC0415 - только на Windows

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        темно = ctypes.c_int(1)
        # 20 -- DWMWA_USE_IMMERSIVE_DARK_MODE. На сборках до 20H1 этот
        # номер был 19, поэтому пробуем оба и не смотрим на ответ.
        for номер in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, номер, ctypes.byref(темно), ctypes.sizeof(темно))
    except Exception as exc:  # noqa: BLE001 - цвет рамки не стоит падения
        log.debug("тёмная рамка не вышла: %s", exc)


def run() -> int:
    """Открыть окно. Возвращает код возврата для командной строки."""
    root = tk.Tk()
    Окно(root)
    root.mainloop()
    return 0
