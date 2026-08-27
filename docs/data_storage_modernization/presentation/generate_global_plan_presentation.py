#!/usr/bin/env /usr/bin/python3
"""Собрать светлую ODP/PDF-презентацию общего плана модернизации данных."""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import uno  # noqa: F401 — регистрирует UNO-importer для com.sun.star
from com.sun.star.awt import Point, Size
from com.sun.star.awt.FontWeight import BOLD, NORMAL
from com.sun.star.drawing.FillStyle import NONE as FILL_NONE
from com.sun.star.drawing.FillStyle import SOLID as FILL_SOLID
from com.sun.star.drawing.LineStyle import NONE as LINE_NONE
from com.sun.star.drawing.LineStyle import SOLID as LINE_SOLID
from com.sun.star.drawing.TextVerticalAdjust import CENTER as V_CENTER
from com.sun.star.drawing.TextVerticalAdjust import TOP as V_TOP
from com.sun.star.style.ParagraphAdjust import CENTER, LEFT, RIGHT

from generate_stage_1_presentation import connect_office, property_value


OUT_DIR = Path(__file__).resolve().parent
ODP_PATH = OUT_DIR / "00_global_plan_presentation.odp"
PDF_PATH = OUT_DIR / "00_global_plan_presentation.pdf"

SLIDE_W = 33867
SLIDE_H = 19050


def mm(value: float) -> int:
    return int(round(value * 100))


def rgb(value: str) -> int:
    return int(value.removeprefix("#"), 16)


def set_prop(obj, name: str, value) -> None:
    try:
        setattr(obj, name, value)
    except Exception:
        try:
            obj.setPropertyValue(name, value)
        except Exception:
            pass


BG = rgb("#F6F8F7")
SURFACE = rgb("#FFFFFF")
SURFACE_ALT = rgb("#F0F4F3")
INK = rgb("#203039")
MUTED = rgb("#687780")
FAINT = rgb("#8E9AA0")
LINE = rgb("#DCE5E3")
WHITE = rgb("#FFFFFF")

TEAL = rgb("#2F8F83")
TEAL_SOFT = rgb("#E1F1EE")
BLUE = rgb("#527BA4")
BLUE_SOFT = rgb("#E7EFF7")
VIOLET = rgb("#776FA3")
VIOLET_SOFT = rgb("#EEEAF6")
GREEN = rgb("#5D8B68")
GREEN_SOFT = rgb("#E7F1E9")
AMBER = rgb("#C4873D")
AMBER_SOFT = rgb("#F8EEDC")
SLATE = rgb("#506B75")
SLATE_SOFT = rgb("#E6EEF0")
RED = rgb("#B95F61")
RED_SOFT = rgb("#F7E7E7")

FONT = "Liberation Sans"
MONO = "Liberation Mono"


class LightDeck:
    def __init__(self, document):
        self.doc = document
        self.pages = document.getDrawPages()
        self.slide_no = 0

    def new_slide(self):
        if self.slide_no == 0:
            page = self.pages.getByIndex(0)
            while page.getCount():
                page.remove(page.getByIndex(0))
        else:
            page = self.pages.insertNewByIndex(self.pages.getCount())
        page.Width = SLIDE_W
        page.Height = SLIDE_H
        set_prop(page, "Layout", 0)
        self.slide_no += 1
        self.rect(page, 0, 0, 338.67, 190.5, BG, radius=0)
        return page

    def rect(
        self,
        page,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: int,
        *,
        line: int | None = None,
        line_width: float = 0.35,
        radius: float = 3,
        transparency: int = 0,
    ):
        shape = self.doc.createInstance("com.sun.star.drawing.RectangleShape")
        shape.Position = Point(mm(x), mm(y))
        shape.Size = Size(mm(w), mm(h))
        shape.FillStyle = FILL_SOLID
        shape.FillColor = fill
        set_prop(shape, "FillTransparence", transparency)
        if line is None:
            shape.LineStyle = LINE_NONE
        else:
            shape.LineStyle = LINE_SOLID
            shape.LineColor = line
            shape.LineWidth = mm(line_width)
        set_prop(shape, "CornerRadius", mm(radius))
        page.add(shape)
        return shape

    def ellipse(
        self,
        page,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: int,
        *,
        line: int | None = None,
        line_width: float = 0.35,
        transparency: int = 0,
    ):
        shape = self.doc.createInstance("com.sun.star.drawing.EllipseShape")
        shape.Position = Point(mm(x), mm(y))
        shape.Size = Size(mm(w), mm(h))
        shape.FillStyle = FILL_SOLID
        shape.FillColor = fill
        set_prop(shape, "FillTransparence", transparency)
        if line is None:
            shape.LineStyle = LINE_NONE
        else:
            shape.LineStyle = LINE_SOLID
            shape.LineColor = line
            shape.LineWidth = mm(line_width)
        page.add(shape)
        return shape

    def line(
        self,
        page,
        x: float,
        y: float,
        w: float,
        h: float = 0,
        *,
        color: int = LINE,
        width: float = 0.45,
    ):
        shape = self.doc.createInstance("com.sun.star.drawing.LineShape")
        shape.Position = Point(mm(x), mm(y))
        shape.Size = Size(mm(w), mm(h))
        shape.LineStyle = LINE_SOLID
        shape.LineColor = color
        shape.LineWidth = mm(width)
        page.add(shape)
        return shape

    def text(
        self,
        page,
        value: str,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        size: float = 16,
        color: int = INK,
        bold: bool = False,
        align=LEFT,
        valign=V_TOP,
        font: str = FONT,
        margin: float = 0,
    ):
        shape = self.doc.createInstance("com.sun.star.drawing.TextShape")
        shape.Position = Point(mm(x), mm(y))
        shape.Size = Size(mm(w), mm(h))
        page.add(shape)
        shape.String = value
        shape.FillStyle = FILL_NONE
        shape.LineStyle = LINE_NONE
        shape.CharFontName = font
        shape.CharHeight = size
        shape.CharColor = color
        shape.CharWeight = BOLD if bold else NORMAL
        shape.ParaAdjust = align
        shape.TextVerticalAdjust = valign
        shape.TextLeftDistance = mm(margin)
        shape.TextRightDistance = mm(margin)
        shape.TextUpperDistance = mm(margin)
        shape.TextLowerDistance = mm(margin)
        set_prop(shape, "TextAutoGrowHeight", False)
        set_prop(shape, "TextAutoGrowWidth", False)
        return shape

    def card(
        self,
        page,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: int = SURFACE,
        line: int = LINE,
        radius: float = 4,
    ):
        return self.rect(page, x, y, w, h, fill, line=line, radius=radius)

    def pill(
        self,
        page,
        value: str,
        x: float,
        y: float,
        w: float,
        *,
        fill: int = TEAL_SOFT,
        color: int = TEAL,
        size: float = 8.5,
    ):
        self.rect(page, x, y, w, 7.5, fill, radius=3.7)
        self.text(
            page,
            value,
            x,
            y + 0.2,
            w,
            7,
            size=size,
            color=color,
            bold=True,
            align=CENTER,
            valign=V_CENTER,
        )

    def header(
        self,
        page,
        title: str,
        subtitle: str,
        number: int,
        *,
        accent: int = TEAL,
        soft: int = TEAL_SOFT,
        label: str = "ОБЩИЙ ПЛАН",
    ):
        self.pill(page, label, 18, 10, 51, fill=soft, color=accent)
        self.text(page, title, 18, 23, 278, 16, size=25, bold=True)
        self.text(page, subtitle, 18, 40, 292, 10, size=11.5, color=MUTED)
        self.text(
            page,
            f"{number:02d}",
            307,
            12,
            15,
            7,
            size=9.5,
            color=FAINT,
            bold=True,
            align=RIGHT,
        )
        self.line(page, 18, 53, 304, color=LINE, width=0.35)

    def footer(self, page, source: str = ""):
        if source:
            self.text(page, source, 18, 182, 244, 4, size=7.3, color=FAINT)
        self.text(
            page,
            "PDF-proverka · 27.08.2026",
            267,
            182,
            55,
            4,
            size=7.3,
            color=FAINT,
            align=RIGHT,
        )

    def bullet(
        self,
        page,
        value: str,
        x: float,
        y: float,
        w: float,
        *,
        dot: int = TEAL,
        color: int = INK,
        size: float = 10.5,
        h: float = 12,
    ):
        self.ellipse(page, x, y + 2.2, 2.5, 2.5, dot)
        self.text(page, value, x + 5.2, y, w - 5.2, h, size=size, color=color)

    def arrow(self, page, x: float, y: float, *, color: int = MUTED, w: float = 10):
        self.text(
            page,
            "→",
            x,
            y,
            w,
            8,
            size=14,
            color=color,
            bold=True,
            align=CENTER,
            valign=V_CENTER,
        )


def slide_title(deck: LightDeck):
    page = deck.new_slide()
    deck.pill(page, "АРХИТЕКТУРНАЯ ДОРОЖНАЯ КАРТА", 18, 14, 81)
    deck.text(
        page,
        "План развития\nхранения и движения данных",
        18,
        38,
        194,
        50,
        size=30,
        bold=True,
    )
    deck.text(
        page,
        "От разрозненных файлов и ссылок — к понятным источникам истины,\n"
        "проверяемой целостности и быстрому интерфейсу.",
        18,
        96,
        210,
        22,
        size=14,
        color=MUTED,
    )

    pills = [
        ("5 этапов", 18, 132, 39, TEAL_SOFT, TEAL),
        ("без big bang", 62, 132, 51, BLUE_SOFT, BLUE),
        ("с rollback", 118, 132, 43, VIOLET_SOFT, VIOLET),
        ("один source of truth", 166, 132, 69, GREEN_SOFT, GREEN),
    ]
    for value, x, y, w, fill, color in pills:
        deck.pill(page, value, x, y, w, fill=fill, color=color, size=8.2)

    # Мягкая схема справа: метаданные и байты сходятся в один продуктовый экран.
    deck.ellipse(page, 240, 30, 76, 76, SURFACE, line=LINE, line_width=0.45)
    deck.ellipse(page, 252, 42, 52, 52, SURFACE_ALT, line=LINE)
    deck.ellipse(page, 265, 55, 26, 26, TEAL_SOFT, line=TEAL)
    deck.text(page, "APP", 265, 61, 26, 9, size=12, color=TEAL, bold=True, align=CENTER)

    labels = [
        ("PostgreSQL", 216, 25, BLUE, 48, 9),
        ("S3", 298, 34, VIOLET, 9, 17),
        ("кэш", 305, 91, AMBER, 10, 14),
        ("внешний\nисточник", 222, 96, GREEN, 28, 19),
    ]
    for label, x, y, color, w, h in labels:
        deck.text(page, label, x, y, w, h, size=9, color=color, bold=True, align=CENTER)

    deck.line(page, 249, 43, 19, 18, color=BLUE)
    deck.line(page, 303, 48, -17, 18, color=VIOLET)
    deck.line(page, 304, 96, -18, -20, color=AMBER)
    deck.line(page, 246, 103, 23, -26, color=GREEN)

    deck.card(page, 243, 126, 72, 28, fill=SURFACE, line=LINE)
    deck.text(page, "Главный принцип", 250, 131, 58, 6, size=8.5, color=MUTED, bold=True, align=CENTER)
    deck.text(page, "одно основное место\nдля каждого типа данных", 249, 140, 60, 12, size=10.5, bold=True, align=CENTER)
    deck.footer(page, "Основа: 00_global_plan.md")


def slide_why(deck: LightDeck):
    page = deck.new_slide()
    deck.header(
        page,
        "Почему систему нужно упорядочить",
        "Сегодня приложение работает, но ответственность за данные распределена между слишком многими местами.",
        2,
        accent=RED,
        soft=RED_SOFT,
    )

    sources = [
        ("JSON + latest", "актуальность\nв двух местах", TEAL_SOFT, TEAL),
        ("Внешние URL", "файл может\nисчезнуть", BLUE_SOFT, BLUE),
        ("Локальный диск", "каноника, кэш\nи staging рядом", AMBER_SOFT, AMBER),
        ("SQLite", "локальный\nуправляющий контур", VIOLET_SOFT, VIOLET),
    ]
    for idx, (title, desc, fill, color) in enumerate(sources):
        x = 18 + idx * 77
        deck.card(page, x, 66, 70, 39, fill=fill, line=color)
        deck.text(page, title, x + 5, 72, 60, 7, size=11.5, color=color, bold=True, align=CENTER)
        deck.text(page, desc, x + 5, 84, 60, 14, size=9.2, color=INK, align=CENTER)

    deck.text(page, "Что это создаёт", 18, 119, 55, 7, size=11, color=MUTED, bold=True)
    risks = [
        ("01", "Решение может потерять связь\nс замечанием после переаудита"),
        ("02", "Один файл имеет несколько\nадресов и трактовок актуальности"),
        ("03", "Сбой диска или внешней ссылки\nстановится потерей рабочего доступа"),
    ]
    for idx, (num, text) in enumerate(risks):
        x = 18 + idx * 102
        deck.card(page, x, 132, 94, 33, fill=SURFACE, line=LINE)
        deck.ellipse(page, x + 6, 139, 10, 10, RED_SOFT, line=RED)
        deck.text(page, num, x + 6, 141, 10, 5, size=7.8, color=RED, bold=True, align=CENTER)
        deck.text(page, text, x + 21, 137, 67, 20, size=9.6, bold=True)

    deck.rect(page, 18, 171, 298, 6, TEAL_SOFT, radius=3)
    deck.text(
        page,
        "Приоритеты плана: целостность данных · меньше источников истины · предсказуемое быстродействие",
        22,
        170.7,
        290,
        6,
        size=9.3,
        color=TEAL,
        bold=True,
        align=CENTER,
    )
    deck.footer(page)


def slide_target(deck: LightDeck):
    page = deck.new_slide()
    deck.header(
        page,
        "Целевая модель: у каждого слоя одна роль",
        "Метаданные, байты, импорт и временная обработка больше не конкурируют за статус каноники.",
        3,
        accent=TEAL,
        soft=TEAL_SOFT,
    )

    nodes = [
        (18, 78, 48, "Внешний\nисточник", "только импорт", GREEN_SOFT, GREEN),
        (78, 78, 48, "Ingest", "проверка + SHA", TEAL_SOFT, TEAL),
        (140, 68, 67, "Приложение", "единые storage / metadata API", SURFACE, INK),
        (221, 60, 48, "PostgreSQL", "метаданные", BLUE_SOFT, BLUE),
        (221, 104, 48, "Свой S3", "файлы", VIOLET_SOFT, VIOLET),
        (283, 78, 39, "UI /\nворкеры", "через API", SLATE_SOFT, SLATE),
    ]
    for x, y, w, title, desc, fill, color in nodes:
        deck.card(page, x, y, w, 31, fill=fill, line=color)
        deck.text(page, title, x + 3, y + 5, w - 6, 12, size=10.8, color=color, bold=True, align=CENTER)
        deck.text(page, desc, x + 3, y + 20, w - 6, 6, size=7.8, color=MUTED, align=CENTER)

    deck.arrow(page, 67, 90, color=TEAL)
    deck.arrow(page, 128, 90, color=TEAL)
    deck.line(page, 207, 84, 14, -9, color=BLUE)
    deck.line(page, 207, 93, 14, 25, color=VIOLET)
    deck.line(page, 269, 76, 14, 14, color=SLATE)
    deck.line(page, 269, 119, 14, -23, color=SLATE)

    roles = [
        ("PostgreSQL", "связи, статусы, версии, решения", BLUE),
        ("S3", "оригиналы и неизменяемые результаты", VIOLET),
        ("Локальный диск", "кэш и рабочая область — можно очистить", AMBER),
    ]
    for idx, (name, desc, color) in enumerate(roles):
        x = 18 + idx * 102
        deck.card(page, x, 137, 94, 28, fill=SURFACE, line=LINE)
        deck.rect(page, x, 137, 4, 28, color, radius=2)
        deck.text(page, name, x + 9, 141, 77, 7, size=10.5, color=color, bold=True)
        deck.text(page, desc, x + 9, 151, 77, 10, size=8.5, color=INK)

    deck.text(page, "Производные данные и индексы всегда пересоздаются из этих источников.", 18, 171, 304, 6, size=9.2, color=MUTED, align=CENTER)
    deck.footer(page)


def slide_roadmap(deck: LightDeck):
    page = deck.new_slide()
    deck.header(
        page,
        "Дорожная карта: сначала смысл, затем инфраструктура",
        "Каждый этап уменьшает риск сам по себе и оставляет контролируемый возврат к предыдущему режиму.",
        4,
        accent=BLUE,
        soft=BLUE_SOFT,
    )

    stages = [
        ("1", "ID и\nцелостность", TEAL, TEAL_SOFT),
        ("2", "Файлы, S3\nи ingest", VIOLET, VIOLET_SOFT),
        ("3", "PostgreSQL\nметаданных", GREEN, GREEN_SOFT),
        ("4", "Индексы и\nскорость", AMBER, AMBER_SOFT),
        ("5", "Один source\nof truth", SLATE, SLATE_SOFT),
    ]
    for idx, (num, title, color, soft) in enumerate(stages):
        x = 18 + idx * 61
        deck.card(page, x, 74, 52, 43, fill=SURFACE, line=color)
        deck.ellipse(page, x + 19.5, 65, 13, 13, soft, line=color)
        deck.text(page, num, x + 19.5, 67, 13, 7, size=9.5, color=color, bold=True, align=CENTER, valign=V_CENTER)
        deck.text(page, title, x + 5, 86, 42, 18, size=10.2, color=color, bold=True, align=CENTER)
        if idx < len(stages) - 1:
            deck.arrow(page, x + 52, 90, color=FAINT, w=9)

    deck.pill(page, "2.1 · потоковый ingest", 18, 128, 70, fill=VIOLET_SOFT, color=VIOLET, size=8)
    deck.text(page, "2.0–2.2 параллельно, без новой публикации", 86, 129, 82, 6, size=7.7, color=MUTED)
    deck.pill(page, "1-Б · projects_v2_primary", 177, 128, 78, fill=TEAL_SOFT, color=TEAL, size=8)
    deck.text(page, "гейт production-записи этапа 2", 259, 129, 63, 6, size=8.0, color=MUTED)

    deck.rect(page, 18, 147, 304, 20, RED_SOFT, line=RED, radius=4)
    deck.text(page, "Срочно до этапа 2", 25, 151, 46, 6, size=8.5, color=RED, bold=True)
    deck.text(page, "закрыть небезопасный export/download · проверить production auth и nginx", 76, 150, 238, 8, size=10.2, color=INK, bold=True)

    deck.text(page, "Нет массового удаления при миграции: shadow → parity → canary → primary → cleanup.", 18, 172, 304, 6, size=9.2, color=MUTED, align=CENTER)
    deck.footer(page)


def stage_slide(
    deck: LightDeck,
    *,
    slide_no: int,
    stage_no: str,
    title: str,
    subtitle: str,
    accent: int,
    soft: int,
    before: str,
    after: str,
    changes: list[str],
    user_benefits: list[str],
    system_benefits: list[str],
    handoff: str,
    source: str,
):
    page = deck.new_slide()
    deck.header(
        page,
        f"{stage_no}. {title}",
        subtitle,
        slide_no,
        accent=accent,
        soft=soft,
        label=f"ЭТАП {stage_no}",
    )

    # Слева — один читаемый переход «было → стало».
    deck.card(page, 18, 63, 87, 100, fill=soft, line=accent)
    deck.text(page, "СМЫСЛ ЭТАПА", 25, 70, 73, 6, size=8, color=accent, bold=True)
    deck.text(page, stage_no, 25, 82, 25, 18, size=28, color=accent, bold=True)
    deck.text(page, "Было", 25, 107, 20, 6, size=8.3, color=MUTED, bold=True)
    deck.text(page, before, 25, 116, 66, 13, size=10.3, color=INK, bold=True)
    deck.text(page, "↓", 49, 131, 16, 8, size=14, color=accent, bold=True, align=CENTER)
    deck.text(page, "Стало", 25, 141, 20, 6, size=8.3, color=accent, bold=True)
    deck.text(page, after, 25, 149, 66, 11, size=10.3, color=accent, bold=True)

    # Центр — изменения.
    deck.card(page, 116, 63, 96, 100, fill=SURFACE, line=LINE)
    deck.text(page, "Что меняем", 124, 70, 80, 8, size=13.5, bold=True)
    for idx, item in enumerate(changes):
        deck.bullet(page, item, 124, 87 + idx * 17, 80, dot=accent, size=10.1, h=14)

    # Справа — два вида пользы.
    deck.card(page, 223, 63, 99, 100, fill=SURFACE, line=LINE)
    deck.text(page, "Что получаем", 231, 70, 83, 8, size=13.5, bold=True)
    deck.pill(page, "ДЛЯ ПОЛЬЗОВАТЕЛЯ", 231, 84, 55, fill=soft, color=accent, size=7.3)
    for idx, item in enumerate(user_benefits):
        deck.bullet(page, item, 231, 96 + idx * 14, 83, dot=accent, size=9.5, h=12)
    deck.pill(page, "ДЛЯ СИСТЕМЫ", 231, 127, 45, fill=SURFACE_ALT, color=SLATE, size=7.3)
    for idx, item in enumerate(system_benefits):
        deck.bullet(page, item, 231, 139 + idx * 13, 83, dot=SLATE, size=9.2, h=11)

    deck.rect(page, 18, 169, 304, 8, SURFACE_ALT, radius=4)
    deck.text(page, "Дальше", 24, 170.3, 20, 5, size=7.8, color=MUTED, bold=True)
    deck.text(page, handoff, 48, 169.9, 267, 6, size=9.1, color=accent, bold=True)
    deck.footer(page, source)


def slide_stage_1(deck: LightDeck):
    stage_slide(
        deck,
        slide_no=5,
        stage_no="1",
        title="Единые правила идентичности",
        subtitle="Не новая система вместо v2, а точная дельта к уже работающему projects_v2.",
        accent=TEAL,
        soft=TEAL_SOFT,
        before="Путь, latest и F-NNN\nмогут менять смысл",
        after="Стабильные UID и\nнеизменяемый run",
        changes=[
            "document_uid, version_id, run_id и finding_uid",
            "Manifest и один канонический current",
            "Самодостаточные решения эксперта и lineage",
            "1-Б: запись переключается на projects_v2_primary",
        ],
        user_benefits=[
            "Решение не теряется после переаудита",
            "История версии остаётся понятной",
        ],
        system_benefits=[
            "Один смысл у каждой сущности",
            "Готовая основа для S3 и PostgreSQL",
        ],
        handoff="После 1-Б можно безопасно включать production-запись файлового контура этапа 2.",
        source="01_storage_and_identity_rules.md · 01b_projects_v2_write_cutover.md",
    )


def slide_stage_2(deck: LightDeck):
    stage_slide(
        deck,
        slide_no=6,
        stage_no="2",
        title="Единый файловый контур, S3 и ingest",
        subtitle="Один Storage Service управляет байтами; внешние источники остаются необязательными adapters.",
        accent=VIOLET,
        soft=VIOLET_SOFT,
        before="Пути, локальный диск\nи временные URL",
        after="blob_id + manifest +\nprivate S3",
        changes=[
            "2.1: потоковый ingest без больших bytes в RAM",
            "2.2: blob_id, manifests и Storage Service",
            "2.3–2.4: S3 shadow, backfill и cutover",
            "2.5: внешний S3/HTTPS только как adapters",
        ],
        user_benefits=[
            "Документ не зависит от внешней ссылки",
            "Большие загрузки и PDF работают стабильнее",
        ],
        system_benefits=[
            "Проверяемые immutable bytes",
            "Диск становится кэшем, adapter не блокирует план",
        ],
        handoff="Стабильные blob_id и manifests становятся файловой основой PostgreSQL этапа 3.",
        source="02_unified_file_storage_and_ingest.md · 02_01_streaming_ingest.md",
    )


def slide_stage_3(deck: LightDeck):
    stage_slide(
        deck,
        slide_no=7,
        stage_no="3",
        title="PostgreSQL для метаданных",
        subtitle="Связи и статусы переходят из файловых JSON в транзакционную модель с явными ограничениями.",
        accent=GREEN,
        soft=GREEN_SOFT,
        before="JSON, указатели и\nсвязи в каталогах",
        after="Таблицы, PK/FK и\nтранзакции",
        changes=[
            "Таблицы объектов, документов, версий и run",
            "Связи файлов по blob_id и логической роли",
            "Замечания, решения и история изменений",
            "Metadata Service, outbox, backfill и parity",
        ],
        user_benefits=[
            "Одинаковая история во всех экранах",
            "Нет пропавших или дублированных связей",
        ],
        system_benefits=[
            "Транзакции и ограничения целостности",
            "Параллельная работа и штатный backup",
        ],
        handoff="Реальные SQL-профили дают основу для точной индексации этапа 4.",
        source="03_postgresql_metadata.md",
    )


def slide_stage_4(deck: LightDeck):
    stage_slide(
        deck,
        slide_no=8,
        stage_no="4",
        title="Индексация и ускорение чтения",
        subtitle="Оптимизация следует за измерениями: ускоряются реальные пользовательские запросы.",
        accent=AMBER,
        soft=AMBER_SOFT,
        before="Тяжёлые запросы и\nповторный рендер",
        after="SQL-индексы, views и\nкэш производных",
        changes=[
            "Индексы под версии, статусы, даты и поиск",
            "Производные views для тяжёлых списков",
            "S3-кэш/CDN для миниатюр и страниц",
            "Профилирование P50/P95 и стоимости",
        ],
        user_benefits=[
            "Быстрее открываются списки и документы",
            "Стабильнее работа на больших объёмах",
        ],
        system_benefits=[
            "Нет постоянного обхода файлового дерева",
            "Ускорение подтверждено метриками",
        ],
        handoff="После стабильного периода можно отключать legacy-read и временные projections.",
        source="00_global_plan.md · этап 4",
    )


def slide_stage_5(deck: LightDeck):
    stage_slide(
        deck,
        slide_no=9,
        stage_no="5",
        title="Один источник истины и очистка наследия",
        subtitle="Финальное переключение выполняется только после parity, restore drill и наблюдения.",
        accent=SLATE,
        soft=SLATE_SOFT,
        before="Legacy-режим и\nнесколько зеркал",
        after="PostgreSQL + S3;\nостальное — кэш",
        changes=[
            "Чтение метаданных остаётся только в PostgreSQL",
            "S3 остаётся единственным источником файлов",
            "Legacy и _system выводятся по реестру",
            "Rollback-копии архивируются по retention",
        ],
        user_benefits=[
            "Единое поведение во всех экранах",
            "Предсказуемая история и доступность",
        ],
        system_benefits=[
            "Нет конкурирующих источников истины",
            "Кэши безопасно пересоздаются",
        ],
        handoff="Целевая модель завершена: метаданные — PostgreSQL, байты — S3, диск — кэш.",
        source="00_global_plan.md · этап 5",
    )

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    profile = Path(tempfile.mkdtemp(prefix="global-plan-presentation-lo-"))
    process = None
    document = None
    try:
        process, context = connect_office(port, profile)
        desktop = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", context
        )
        hidden = property_value("Hidden", True)
        document = desktop.loadComponentFromURL(
            "private:factory/simpress", "_blank", 0, (hidden,)
        )
        deck = LightDeck(document)
        slide_title(deck)
        slide_why(deck)
        slide_target(deck)
        slide_roadmap(deck)
        slide_stage_1(deck)
        slide_stage_2(deck)
        slide_stage_3(deck)
        slide_stage_4(deck)
        slide_stage_5(deck)

        document.storeAsURL(
            ODP_PATH.as_uri(),
            (
                property_value("FilterName", "impress8"),
                property_value("Overwrite", True),
            ),
        )
        document.storeToURL(
            PDF_PATH.as_uri(),
            (
                property_value("FilterName", "impress_pdf_Export"),
                property_value("Overwrite", True),
            ),
        )
    finally:
        if document is not None:
            try:
                document.close(True)
            except Exception:
                pass
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(profile, ignore_errors=True)

    print(ODP_PATH)
    print(PDF_PATH)


if __name__ == "__main__":
    main()
