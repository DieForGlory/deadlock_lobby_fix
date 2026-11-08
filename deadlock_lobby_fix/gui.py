"""Окно: таблица пинга и галки «играть здесь»."""
from __future__ import annotations

import logging
import threading
import tkinter as tk

from . import blocklist, relays
from .elevate import relaunch_as_admin, running_as_admin
from .words import plural, servers, spelled

log = logging.getLogger(__name__)

ФОН = "#14161c"
ПАНЕЛЬ = "#1b1e26"
ТЕКСТ = "#d8dce6"
ТУСКЛО = "#8a90a0"
ХОРОШО = "#6fbf73"
ТЕРПИМО = "#d9a441"
ПЛОХО = "#e0714f"
ГЛАВНАЯ = "#2f7d3a"
ГЛАВНАЯ_ПОД_МЫШЬЮ = "#38924a"

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
        self._низ()
        self._список()
        self._обновить_состояние()

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
        self.кнопка_снять = self._кнопка(ряд, "Открыть всё обратно",
                                         self.снять)
        self.кнопка_прав = self._кнопка(ряд, "Запросить права",
                                        self.спросить_права)

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
            text="Нажми «Замерить пинг». Займёт секунд десять — "
                 "опрашиваются все сразу.")
        self.состояние.pack(fill="x", padx=16, pady=(10, 6))

    def _низ(self) -> None:
        """Всё, что под списком. Пакуется до списка, чтобы не обрезалось."""
        низ = tk.Frame(self.root, bg=ФОН)
        низ.pack(side="bottom", fill="x")

        ряд = tk.Frame(низ, bg=ФОН)
        ряд.pack(fill="x", padx=16, pady=(0, 10))
        self.кнопка_применить = tk.Button(
            ряд, text="Применить выбранное", command=self.применить,
            bg=ГЛАВНАЯ, fg="#ffffff", activebackground=ГЛАВНАЯ_ПОД_МЫШЬЮ,
            activeforeground="#ffffff", relief="flat", padx=20, pady=8,
            font=("Segoe UI", 10, "bold"), cursor="hand2", borderwidth=0,
            disabledforeground="#a9c9ad")
        self.кнопка_применить.pack(side="right")
        self.кнопки_отметок = [
            self._ссылка(ряд, "Отметить все", lambda: self._отметить(True)),
            self._ссылка(ряд, "Снять все", lambda: self._отметить(False)),
        ]

        self._подвал(низ)

    def _ссылка(self, где, текст, действие) -> tk.Button:
        """Мелкая кнопка-ссылка для быстрых отметок."""
        кнопка = tk.Button(где, text=текст, command=действие, bg=ФОН,
                           fg=ТУСКЛО, activebackground=ФОН,
                           activeforeground=ТЕКСТ, relief="flat", padx=0,
                           pady=0, font=("Segoe UI", 9, "underline"),
                           cursor="hand2", borderwidth=0,
                           disabledforeground=ПАНЕЛЬ, state="disabled")
        кнопка.pack(side="left", padx=(0, 14))
        return кнопка

    def _отметить(self, играть: bool) -> None:
        """Отметить все или снять все. Ближний отмечен всегда."""
        ближний = self.ближний
        for code, держит in self.галки.items():
            держит.set(играть or code == ближний)

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

    def _подвал(self, где) -> None:
        for текст in (
            "Закрытие делается правилами брандмауэра Windows — для них "
            "нужны права администратора. Сама игра при этом не трогается: "
            "ни файлов, ни памяти. «Открыть всё обратно» убирает только "
            "правила этой программы; то, что настраивалось в брандмауэре "
            "раньше, остаётся как было.",
            "Чем больше закрыто, тем дольше ищется матч — это цена, а не "
            "поломка. Ближайший сервер закрыть нельзя, и хотя бы пять "
            "должны остаться открытыми, иначе матч не найдётся вовсе.",
            "Список серверов Valve меняет. Новый датацентр будет открыт, "
            "пока не замеришь и не применишь выбор заново.",
        ):
            tk.Label(где, text=текст, bg=ФОН, fg=ТУСКЛО,
                     justify="left", anchor="w", wraplength=640,
                     font=("Segoe UI", 8)).pack(fill="x", padx=16,
                                                pady=(0, 4))
        tk.Frame(где, bg=ФОН, height=8).pack()

    def сказать(self, текст: str) -> None:
        self.состояние.configure(text=текст)

    @property
    def ближний(self) -> str | None:
        найден = relays.nearest(self.pings)
        return найден.cluster.code if найден else None

    def _обновить_состояние(self) -> None:
        """Кнопка прав видна, только пока прав нет."""
        if running_as_admin():
            self.кнопка_прав.pack_forget()

    def замерить(self) -> None:
        if self.занято:
            return
        self.занято = True
        self.кнопка_замера.configure(state="disabled")
        self.сказать("Идёт опрос серверов…")
        threading.Thread(target=self._мерить, daemon=True,
                         name="deadlock-lobby-fix: замер").start()

    def _мерить(self) -> None:
        """Нить замера. В окно отсюда не лезем -- только через after."""
        try:
            где = relays.clusters()
            итог = (relays.measure(где), blocklist.blocked()) if где else None
        except Exception as exc:
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
                     f"{ближний.ms:.0f} мс. Отметь, где хочешь играть, "
                     f"и жми «Применить выбранное» внизу — остальные "
                     f"закроются.")
        for кнопка in self.кнопки_отметок:
            кнопка.configure(state="normal")

    def _нарисовать(self, закрытые: set[str]) -> None:
        for виджет in self.строки.winfo_children():
            виджет.destroy()
        self.галки = {}
        ближний = self.ближний
        for ping in self.pings:
            строка = tk.Frame(self.строки, bg=ПАНЕЛЬ)
            строка.pack(fill="x", padx=8, pady=1)

            играть = (ping.cluster.code == ближний
                      or ping.cluster.code not in закрытые)
            держит = tk.BooleanVar(value=играть)
            галка = tk.Checkbutton(
                строка, text=ping.cluster.name, variable=держит, bg=ПАНЕЛЬ,
                fg=ТЕКСТ, selectcolor=ФОН, activebackground=ПАНЕЛЬ,
                activeforeground=ТЕКСТ, anchor="w", font=("Segoe UI", 9),
                highlightthickness=0, borderwidth=0,
                disabledforeground=ТУСКЛО)
            if ping.cluster.code == ближний:
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

    def _выбор(self) -> set[str]:
        """Что закрыть: всё, где галка снята. Ближний не закрывается."""
        ближний = self.ближний
        return {code for code, держит in self.галки.items()
                if not держит.get() and code != ближний}

    def применить(self) -> None:
        if self.занято:
            return
        if not self.pings:
            self.сказать("Сначала жми «Замерить пинг» — без замера не "
                         "видно, какие серверы есть.")
            return
        среди = [p.cluster for p in self.pings]
        выбор = self._выбор()
        отмечено = len(среди) - len(выбор)
        if отмечено < blocklist.KEEP_OPEN:
            self.сказать(
                f"{plural(отмечено, 'Отмечен', 'Отмечено', 'Отмечено')} "
                f"{servers(отмечено)}, а надо хотя бы "
                f"{spelled(blocklist.KEEP_OPEN)} — иначе матч может не "
                f"найтись вовсе.")
            return
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
        self.сказать("Правила ставятся…")
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
            self.сказать("Отмечены все серверы — закрывать нечего, всё "
                         "открыто.")
            return
        стало = plural(сколько, "закрыт", "закрыто", "закрыто")
        self.сказать(f"Готово: играешь только на отмеченных, {стало} "
                     f"{servers(сколько)}. Перезапусти поиск матча, чтобы "
                     f"игра замерила заново.")

    def снять(self) -> None:
        if self.занято:
            return
        if not running_as_admin():
            self.сказать("Для этого нужны права администратора. Жми "
                         "«Запросить права» — откроется второе окно, "
                         "дальше работай в нём.")
            return
        self.занято = True
        self.сказать("Правила снимаются…")
        threading.Thread(target=self._снимать, daemon=True,
                         name="deadlock-lobby-fix: снятие").start()

    def _снимать(self) -> None:
        беда = blocklist.clear()
        self.root.after(0, self._снято, беда)

    def _снято(self, беда: str) -> None:
        self.занято = False
        if not беда:
            self._отметить(True)
        self.сказать(беда if беда else
                     "Всё открыто обратно. Убраны только правила этой "
                     "программы — то, что настраивалось в брандмауэре "
                     "раньше, на месте.")

    def спросить_права(self) -> None:
        """Перезапустить себя через UAC. Нынешнее окно человек закроет сам."""
        отказ = relaunch_as_admin()
        if отказ:
            self.сказать(отказ)
            return
        self.сказать("Открылось второе окно, уже с правами — дальше в "
                     "нём. Это можно закрывать.")


def _тёмный_заголовок(root) -> None:
    """Попросить Windows покрасить рамку окна в тёмное."""
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        темно = ctypes.c_int(1)
        for номер in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, номер, ctypes.byref(темно), ctypes.sizeof(темно))
    except Exception as exc:
        log.debug("тёмная рамка не вышла: %s", exc)


def run() -> int:
    """Открыть окно. Возвращает код возврата для командной строки."""
    root = tk.Tk()
    Окно(root)
    root.mainloop()
    return 0
