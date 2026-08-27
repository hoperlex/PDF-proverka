#!/usr/bin/env /usr/bin/python3
"""Собрать редактируемую ODP-презентацию этапа 1 и экспортировать её в PDF."""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import uno
from com.sun.star.awt import Point, Size
from com.sun.star.awt.FontWeight import BOLD, NORMAL
from com.sun.star.beans import PropertyValue
from com.sun.star.drawing.FillStyle import NONE as FILL_NONE
from com.sun.star.drawing.FillStyle import SOLID as FILL_SOLID
from com.sun.star.drawing.LineStyle import NONE as LINE_NONE
from com.sun.star.drawing.LineStyle import SOLID as LINE_SOLID
from com.sun.star.drawing.TextVerticalAdjust import CENTER as V_CENTER
from com.sun.star.drawing.TextVerticalAdjust import TOP as V_TOP
from com.sun.star.style.ParagraphAdjust import CENTER, LEFT, RIGHT


OUT_DIR = Path(__file__).resolve().parent
ODP_PATH = OUT_DIR / "01_storage_identity_presentation.odp"
PDF_PATH = OUT_DIR / "01_storage_identity_presentation.pdf"

SLIDE_W = 33867
SLIDE_H = 19050


def mm(value: float) -> int:
    return int(round(value * 100))


def rgb(value: str) -> int:
    return int(value.removeprefix("#"), 16)


BG = rgb("#0D1219")
PANEL = rgb("#151D28")
PANEL_2 = rgb("#1A2333")
LINE = rgb("#2A3544")
TEXT = rgb("#E2E8F0")
MUTED = rgb("#93A4B8")
TEAL = rgb("#00C2B8")
TEAL_DARK = rgb("#083E40")
BLUE = rgb("#4A9EFF")
BLUE_DARK = rgb("#172F52")
GREEN = rgb("#22D38A")
GREEN_DARK = rgb("#123D32")
AMBER = rgb("#F5A623")
AMBER_DARK = rgb("#47351A")
RED = rgb("#FF4D6D")
RED_DARK = rgb("#471F2B")
PURPLE = rgb("#A78BFA")
PURPLE_DARK = rgb("#2E2852")
WHITE = rgb("#FFFFFF")

FONT = "Liberation Sans"
MONO = "Liberation Mono"


def property_value(name: str, value) -> PropertyValue:
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def set_prop(obj, name: str, value) -> None:
    try:
        setattr(obj, name, value)
    except Exception:
        try:
            obj.setPropertyValue(name, value)
        except Exception:
            pass


class Deck:
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
        line_width: float = 0.4,
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
            shape.LineWidth = mm(0.45)
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
        width: float = 0.5,
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
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        size: float = 16,
        color: int = TEXT,
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
        shape.String = text
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
        fill: int = PANEL,
        line: int = LINE,
        radius: float = 3,
    ):
        return self.rect(page, x, y, w, h, fill, line=line, radius=radius)

    def pill(
        self,
        page,
        text: str,
        x: float,
        y: float,
        w: float,
        *,
        fill: int = TEAL_DARK,
        color: int = TEAL,
        size: float = 9,
    ):
        self.rect(page, x, y, w, 7.5, fill, radius=3.7)
        self.text(page, text, x, y + 0.2, w, 7.1, size=size, color=color,
                  bold=True, align=CENTER, valign=V_CENTER)

    def header(self, page, title: str, subtitle: str, number: int):
        self.pill(page, "STORAGE MODERNIZATION · ЭТАП 1", 18, 10, 67)
        self.text(page, title, 18, 22, 274, 17, size=26, bold=True)
        self.text(page, subtitle, 18, 39, 286, 10, size=11.5, color=MUTED)
        self.text(page, f"{number:02d}", 306, 12, 16, 8, size=10, color=MUTED,
                  bold=True, align=RIGHT)
        self.line(page, 18, 52, 304, color=LINE, width=0.35)

    def footer(self, page, source: str = ""):
        if source:
            self.text(page, source, 18, 181.5, 270, 4, size=7.5, color=MUTED)
        self.text(page, "PDF-proverka · 27.08.2026", 275, 181.5, 47, 4,
                  size=7.5, color=MUTED, align=RIGHT)

    def bullet(
        self,
        page,
        text: str,
        x: float,
        y: float,
        w: float,
        *,
        color: int = TEXT,
        dot: int = TEAL,
        size: float = 11.5,
        h: float = 10,
    ):
        self.ellipse(page, x, y + 2.4, 2.7, 2.7, dot)
        self.text(page, text, x + 5.2, y, w - 5.2, h, size=size, color=color,
                  valign=V_TOP)

    def metric(self, page, value: str, label: str, x: float, y: float,
               w: float, color: int):
        self.card(page, x, y, w, 29, fill=PANEL_2, line=LINE)
        self.text(page, value, x + 5, y + 3.5, w - 10, 11, size=22,
                  color=color, bold=True)
        self.text(page, label, x + 5, y + 16, w - 10, 9, size=9.5,
                  color=MUTED)


def slide_1(deck: Deck):
    page = deck.new_slide()
    deck.pill(page, "ЭТАП 1 ГЛОБАЛЬНОГО ПЛАНА", 18, 13, 58)
    deck.text(page, "1", 18, 32, 42, 20, size=44, bold=True, color=TEAL)
    deck.text(page, "Единая идентичность\nи целостность данных", 18, 54, 190, 42,
              size=28, bold=True)
    deck.text(page, "Не новое хранилище. Точная дельта к уже работающему projects_v2.",
              18, 103, 195, 18, size=15, color=MUTED)

    deck.rect(page, 18, 132, 195, 27, TEAL_DARK, line=TEAL, radius=4)
    deck.text(page, "Главная цель", 25, 137, 42, 6, size=9, color=TEAL, bold=True)
    deck.text(page,
              "Решение человека всегда остаётся связано\nс тем же документом, запуском и замечанием.",
              25, 145, 176, 12, size=12.5, bold=True)

    deck.ellipse(page, 229, 28, 88, 88, PANEL_2, line=LINE)
    deck.ellipse(page, 242, 41, 62, 62, TEAL_DARK, line=TEAL)
    deck.ellipse(page, 258, 57, 30, 30, TEAL, line=TEAL)
    deck.text(page, "v2", 258, 61, 30, 17, size=19, color=BG, bold=True,
              align=CENTER, valign=V_CENTER)
    deck.text(page, "document_uid", 228, 22, 45, 8, size=9.5, color=BLUE,
              bold=True, align=CENTER)
    deck.text(page, "finding_uid", 282, 29, 40, 8, size=9.5, color=PURPLE,
              bold=True, align=CENTER)
    deck.text(page, "immutable run", 285, 98, 40, 8, size=9.5, color=GREEN,
              bold=True, align=CENTER)
    deck.text(page, "decision", 222, 105, 38, 8, size=9.5, color=AMBER,
              bold=True, align=CENTER)

    deck.line(page, 272, 48, -18, -14, color=BLUE, width=0.5)
    deck.line(page, 296, 55, 8, -17, color=PURPLE, width=0.5)
    deck.line(page, 296, 88, 10, 15, color=GREEN, width=0.5)
    deck.line(page, 250, 91, -8, 15, color=AMBER, width=0.5)

    deck.text(page, "projects_v2 остаётся фундаментом", 228, 128, 90, 11,
              size=13, bold=True, align=CENTER)
    deck.text(page, "Этап 1 укрепляет связи поверх него", 228, 142, 90, 9,
              size=10.5, color=MUTED, align=CENTER)
    deck.footer(page)


def slide_2(deck: Deck):
    page = deck.new_slide()
    deck.header(page, "Почему этап 1 — дельта к projects_v2",
                "Повторная миграция создаст второй источник истины и вернёт уже закрытые риски.", 2)

    deck.text(page, "Уже работающий фундамент", 18, 59, 188, 8,
              size=13, bold=True)
    foundation_y = 127
    deck.rect(page, 18, foundation_y, 188, 26, TEAL_DARK, line=TEAL, radius=4)
    deck.text(page, "projects_v2", 18, foundation_y + 3, 188, 10,
              size=20, bold=True, color=TEAL, align=CENTER)
    deck.text(page, "сохраняем структуру · усиливаем идентичность",
              18, foundation_y + 14, 188, 7, size=9.5, color=TEXT, align=CENTER)

    items = [
        ("01", "Версии vNNN", "единая раскладка"),
        ("02", "SHA-256 входа", "проверка байтов"),
        ("03", "Read / write фасады", "единые точки доступа"),
        ("04", "Миграция + parity", "проверка без потерь"),
    ]
    for idx, (num, title, desc) in enumerate(items):
        x = 18 + idx * 47
        deck.card(page, x, 77, 42, 40, fill=PANEL, line=LINE)
        deck.ellipse(page, x + 4, 82, 9, 9, TEAL_DARK, line=TEAL)
        deck.text(page, num, x + 4, 83, 9, 6, size=8.5, color=TEAL,
                  bold=True, align=CENTER, valign=V_CENTER)
        deck.text(page, title, x + 4, 94, 34, 8, size=10.5, bold=True)
        deck.text(page, desc, x + 4, 104, 34, 8, size=8.5, color=MUTED)
        deck.line(page, x + 21, 117, 0, 10, color=TEAL, width=0.55)

    deck.text(page, "Проверенная база", 220, 59, 102, 8, size=13, bold=True)
    deck.metric(page, "184", "документа в полной проверке", 220, 75, 48, BLUE)
    deck.metric(page, "0", "неожиданных потерь", 274, 75, 48, GREEN)
    deck.metric(page, "341+", "версий требуют legacy-чтение", 220, 110, 48, AMBER)
    deck.metric(page, "179 + 5", "match + ожидаемые отличия", 274, 110, 48, PURPLE)

    deck.rect(page, 18, 162, 304, 13, RED_DARK, line=RED, radius=3)
    deck.text(page, "Почему не «с чистого листа»", 23, 164.5, 57, 7,
              size=9.5, color=RED, bold=True, valign=V_CENTER)
    deck.text(page,
              "Новая параллельная модель = два набора ID, две миграции и новый риск расхождения данных.",
              82, 164.5, 232, 7, size=10, color=TEXT, valign=V_CENTER)
    deck.footer(page,
                "Источники: projects_v2_migration_plan.md, projects_v2_storage_standard.md, new_upload_format.md")


def slide_3(deck: Deck):
    page = deck.new_slide()
    deck.header(page, "Опасность текущей схемы",
                "Критичный риск — не расположение файлов, а потеря смысла связей между ними.", 3)

    deck.card(page, 18, 62, 198, 79, fill=PANEL, line=LINE)
    deck.text(page, "Как решение становится «сиротой»", 25, 68, 115, 8,
              size=13, bold=True)

    flow = [
        (25, BLUE_DARK, BLUE, "v001", "F-006", "Нестыковка\nплощадей"),
        (87, AMBER_DARK, AMBER, "переаудит", "merge / dedup", "Новый порядок\nсписка"),
        (149, RED_DARK, RED, "v002", "F-006", "Другая проблема\nили ID исчез"),
    ]
    for x, fill, accent, top, middle, bottom in flow:
        deck.card(page, x, 86, 49, 43, fill=fill, line=accent)
        deck.text(page, top, x + 3, 89, 43, 6, size=8.5, color=accent,
                  bold=True, align=CENTER)
        deck.text(page, middle, x + 3, 97, 43, 9, size=12, bold=True,
                  align=CENTER)
        deck.text(page, bottom, x + 3, 109, 43, 14, size=9, color=TEXT,
                  align=CENTER)
    deck.text(page, "→", 75, 97, 10, 10, size=20, color=MUTED, bold=True,
              align=CENTER)
    deck.text(page, "→", 137, 97, 10, 10, size=20, color=MUTED, bold=True,
              align=CENTER)

    deck.rect(page, 25, 132, 184, 5, RED, radius=2.5)
    deck.text(page, "Решение хранит project + F-NNN и больше не находит исходную суть",
              25, 143, 188, 11, size=10.5, color=RED, bold=True, align=CENTER)

    deck.card(page, 226, 62, 96, 79, fill=RED_DARK, line=RED)
    deck.text(page, "447", 232, 70, 84, 25, size=38, color=RED, bold=True,
              align=CENTER)
    deck.text(page, "орфанов из 6440 решений", 232, 96, 84, 9, size=12,
              bold=True, align=CENTER)
    deck.text(page, "≈ 7% исторических решений\nне имеют надёжной связи",
              234, 111, 80, 17, size=10, color=TEXT, align=CENTER)

    risks = [
        ("2×", "текущая версия", "TXT и JSON"),
        ("↻", "мутация результата", "03_findings + .bak"),
        ("4", "формата run_id", "без единой роли"),
        ("/", "пути как ссылки", "ломаются при переносе"),
    ]
    for idx, (icon, title, desc) in enumerate(risks):
        x = 18 + idx * 77
        deck.card(page, x, 157, 72, 18, fill=PANEL_2, line=LINE)
        deck.text(page, icon, x + 4, 160, 11, 10, size=13, color=AMBER,
                  bold=True, align=CENTER, valign=V_CENTER)
        deck.text(page, title, x + 18, 159, 49, 6, size=9.5, bold=True)
        deck.text(page, desc, x + 18, 166, 49, 6, size=8, color=MUTED)
    deck.footer(page, "Источник метрики: stable_finding_id.md, замер от 29.06.2026")


def slide_4(deck: Deck):
    page = deck.new_slide()
    deck.header(page, "Было → станет",
                "Этап 1 меняет внутренние связи, сохраняя привычные названия и экранные номера.", 4)

    deck.text(page, "БЫЛО", 18, 59, 122, 7, size=11, color=RED,
              bold=True, align=CENTER)
    deck.text(page, "СТАНЕТ", 200, 59, 122, 7, size=11, color=TEAL,
              bold=True, align=CENTER)

    rows = [
        ("Документ", "Путь + object + code", "document_uid", "Код и путь остаются алиасами"),
        ("Замечание", "F-NNN = личность", "finding_uid = fnd_<ULID>", "F-NNN остаётся номером"),
        ("Решение", "project + F-NNN\nполя берутся из latest",
         "UID + версия + снимок", "Самодостаточная запись"),
        ("Результат", "03_findings меняется\nrun_id смешаны",
         "Неизменяемый run", "Вердикты — отдельный review-слой"),
    ]
    for idx, (label, before, after, note) in enumerate(rows):
        y = 70 + idx * 24
        deck.text(page, label, 18, y + 4.5, 28, 9, size=9.5, color=MUTED,
                  bold=True, valign=V_CENTER)
        deck.card(page, 48, y, 92, 18, fill=RED_DARK, line=RED)
        deck.text(page, before, 53, y + 2, 82, 13, size=10.2, color=TEXT,
                  align=CENTER, valign=V_CENTER)
        deck.text(page, "→", 151, y + 2, 28, 12, size=20, color=MUTED,
                  bold=True, align=CENTER, valign=V_CENTER)
        deck.card(page, 190, y, 132, 18, fill=TEAL_DARK, line=TEAL)
        deck.text(page, after, 195, y + 1.5, 52, 7, size=10.2, color=TEAL,
                  bold=True, align=CENTER, valign=V_CENTER)
        deck.line(page, 251, y + 4, 0, 11, color=LINE, width=0.35)
        deck.text(page, note, 256, y + 2, 61, 13, size=8.6, color=TEXT,
                  align=CENTER, valign=V_CENTER)

    deck.rect(page, 48, 175, 274, 2.5, TEAL, radius=1.2)
    deck.text(page, "Внешне интерфейс почти не меняется · внутри появляется доказуемая история",
              48, 163, 274, 8, size=10.5, color=TEAL, bold=True, align=CENTER)
    deck.footer(page)


def slide_5(deck: Deck):
    page = deck.new_slide()
    deck.header(page, "Сквозная цепочка идентичности",
                "Из решения можно пройти назад до точного запуска, версии и входного файла.", 5)

    nodes = [
        ("object_id", "Объект", BLUE),
        ("discipline", "Раздел", BLUE),
        ("document_uid", "Документ", TEAL),
        ("version_id", "Версия", TEAL),
        ("run_id", "Запуск", GREEN),
        ("finding_uid", "Замечание", PURPLE),
        ("decision_id", "Решение", AMBER),
    ]
    x_positions = [18, 62, 106, 154, 200, 247, 289]
    widths = [35, 35, 39, 35, 39, 36, 33]
    for idx, ((code, label, color), x, w) in enumerate(zip(nodes, x_positions, widths)):
        deck.card(page, x, 78, w, 39, fill=PANEL_2, line=color)
        deck.ellipse(page, x + w / 2 - 4.5, 83, 9, 9,
                     TEAL_DARK if color == TEAL else PANEL, line=color)
        deck.text(page, str(idx + 1), x + w / 2 - 4.5, 84, 9, 6,
                  size=8, color=color, bold=True, align=CENTER, valign=V_CENTER)
        deck.text(page, code, x + 2, 95, w - 4, 7, size=8.5, color=color,
                  bold=True, align=CENTER, font=MONO)
        deck.text(page, label, x + 2, 105, w - 4, 6, size=8.5, color=TEXT,
                  align=CENTER)
        if idx < len(nodes) - 1:
            next_x = x_positions[idx + 1]
            deck.text(page, "→", x + w + 0.5, 91, next_x - x - w - 1, 9,
                      size=14, color=MUTED, bold=True, align=CENTER,
                      valign=V_CENTER)

    deck.card(page, 57, 137, 92, 23, fill=BLUE_DARK, line=BLUE)
    deck.text(page, "Входной файл + SHA-256", 62, 141, 82, 7,
              size=11, color=BLUE, bold=True, align=CENTER)
    deck.text(page, "доказывает, какие байты проверялись", 62, 150, 82, 6,
              size=8.5, color=TEXT, align=CENTER)

    deck.card(page, 190, 137, 92, 23, fill=PURPLE_DARK, line=PURPLE)
    deck.text(page, "Страница + block_id", 195, 141, 82, 7,
              size=11, color=PURPLE, bold=True, align=CENTER)
    deck.text(page, "локализует проблему на чертеже", 195, 150, 82, 6,
              size=8.5, color=TEXT, align=CENTER)

    deck.line(page, 103, 137, 72, -20, color=BLUE, width=0.5)
    deck.line(page, 236, 137, 29, -20, color=PURPLE, width=0.5)
    deck.text(page, "Путь, имя папки и F-NNN больше не определяют личность данных",
              50, 169, 240, 8, size=11.5, color=TEAL, bold=True, align=CENTER)
    deck.footer(page)


def slide_6(deck: Deck):
    page = deck.new_slide()
    deck.header(page, "Что делаем на этапе 1",
                "Аддитивные изменения: сначала наблюдаем, затем записываем рядом и только потом переключаем чтение.", 6)

    work = [
        ("01", "Актуальный baseline", "Считаем документы, версии,\nорфаны и расхождения", BLUE),
        ("02", "document_uid", "Добавляем UID без\nпереноса папок", TEAL),
        ("03", "finding_uid", "Разделяем личность\nи экранный F-NNN", PURPLE),
        ("04", "Решения эксперта", "Снимок сути, версии,\nrun и автора", AMBER),
        ("05", "Неизменяемый run", "Review отдельно; latest\nвосстанавливается", GREEN),
        ("06", "Manifest и указатели", "schema_version; current\nтолько после manifest", RED),
    ]
    for idx, (num, title, desc, color) in enumerate(work):
        row = idx // 3
        col = idx % 3
        x = 18 + col * 103
        y = 65 + row * 52
        deck.card(page, x, y, 97, 43, fill=PANEL, line=LINE)
        deck.rect(page, x, y, 5, 43, color, radius=2)
        deck.ellipse(page, x + 10, y + 8, 11, 11, PANEL_2, line=color)
        deck.text(page, num, x + 10, y + 9.5, 11, 7, size=8.5, color=color,
                  bold=True, align=CENTER, valign=V_CENTER)
        deck.text(page, title, x + 26, y + 7, 64, 8, size=12, bold=True)
        deck.text(page, desc, x + 26, y + 18, 64, 17, size=9.3, color=MUTED)

    deck.line(page, 34, 169, 265, color=LINE, width=0.5)
    phases = [
        ("A", "наблюдение"), ("B", "двойная запись"),
        ("C", "теневое чтение"), ("D", "переключение"),
        ("E", "строгие правила"),
    ]
    for idx, (letter, label) in enumerate(phases):
        x = 31 + idx * 56
        deck.ellipse(page, x, 164.5, 9, 9, TEAL_DARK, line=TEAL)
        deck.text(page, letter, x, 166, 9, 6, size=8, color=TEAL,
                  bold=True, align=CENTER, valign=V_CENTER)
        deck.text(page, label, x - 10, 175, 30, 5, size=8, color=MUTED,
                  align=CENTER)
    deck.footer(page)


def slide_7(deck: Deck):
    page = deck.new_slide()
    deck.header(page, "Этап 1 открывает следующие этапы",
                "Идентификаторы и источники истины фиксируются до переноса данных и оптимизации.", 7)

    stages = [
        ("1", "ID + целостность", TEAL, "Сейчас"),
        ("2", "Файлы + S3", PURPLE, "Ingest"),
        ("3", "PostgreSQL", GREEN, "Связи"),
        ("4", "Индексы", AMBER, "Скорость"),
        ("5", "Переключение", RED, "1 контур"),
    ]
    for idx, (num, title, color, tag) in enumerate(stages):
        x = 18 + idx * 61
        deck.card(page, x, 67, 52, 48,
                  fill=TEAL_DARK if idx == 0 else PANEL, line=color)
        deck.text(page, num, x + 4, 72, 44, 10, size=17, color=color,
                  bold=True, align=CENTER)
        deck.text(page, title, x + 4, 86, 44, 11, size=9.5, color=TEXT,
                  bold=True, align=CENTER)
        deck.pill(page, tag.upper(), x + 8, 102, 36, fill=PANEL_2,
                  color=color, size=7.5)
        if idx < len(stages) - 1:
            deck.text(page, "→", x + 52, 83, 9, 9, size=12, color=MUTED,
                      bold=True, align=CENTER)

    deck.card(page, 18, 128, 304, 40, fill=PANEL_2, line=LINE)
    deck.text(page, "Этап 2 не ждёт внешнюю интеграцию", 25, 134, 82, 12,
              size=12.5, bold=True)
    deck.text(page, "Общий ingest", 113, 133, 67, 8,
              size=10.5, color=TEAL, bold=True, align=CENTER)
    deck.text(page, "browser обязателен", 113, 143, 67, 6,
              size=8.5, color=MUTED, align=CENTER)
    deck.rect(page, 113, 151, 67, 9, TEAL_DARK, line=TEAL, radius=3)
    deck.text(page, "внешние adapters опциональны", 113, 151.6, 67, 6.5,
              size=7.6, color=TEAL, bold=True, align=CENTER, valign=V_CENTER)

    deck.text(page, "защищённый пакет задания  →", 184, 143, 60, 8,
              size=8.5, color=TEXT, align=CENTER)
    deck.text(page, "Удалённый воркер", 246, 133, 67, 8,
              size=10.5, color=BLUE, bold=True, align=CENTER)
    deck.text(page, "C-07 остаётся неизменным", 246, 143, 67, 6,
              size=8.5, color=MUTED, align=CENTER)
    deck.rect(page, 246, 151, 67, 9, BLUE_DARK, line=BLUE, radius=3)
    deck.text(page, "существующий защищённый канал", 246, 151.6, 67, 6.5,
              size=7.4, color=BLUE, bold=True, align=CENTER, valign=V_CENTER)

    deck.footer(page,
                "Гейт production-записи этапа 2: подэтап 1-Б · Storage contract · baseline · restore plan")


def slide_8(deck: Deck):
    page = deck.new_slide()
    deck.header(page, "Польза и критерий готовности",
                "Этап 1 снижает риск немедленно и одновременно удешевляет PostgreSQL/S3-миграции.", 8)

    deck.card(page, 18, 64, 145, 76, fill=TEAL_DARK, line=TEAL)
    deck.text(page, "Краткосрочно", 25, 71, 130, 9, size=16,
              color=TEAL, bold=True)
    deck.bullet(page, "Решения не теряются после переаудита", 25, 87, 128,
                dot=TEAL, size=10.5)
    deck.bullet(page, "Ошибки ссылок видны и диагностируются", 25, 103, 128,
                dot=TEAL, size=10.5)
    deck.bullet(page, "Завершённый run воспроизводим", 25, 119, 128,
                dot=TEAL, size=10.5)

    deck.card(page, 177, 64, 145, 76, fill=BLUE_DARK, line=BLUE)
    deck.text(page, "Долгосрочно", 184, 71, 130, 9, size=16,
              color=BLUE, bold=True)
    deck.bullet(page, "PostgreSQL получает готовые PK/FK", 184, 87, 128,
                dot=BLUE, size=10.5)
    deck.bullet(page, "S3 меняет адрес файла, а не его смысл", 184, 103, 128,
                dot=BLUE, size=10.5)
    deck.bullet(page, "Индексы строятся по стабильным ключам", 184, 119, 128,
                dot=BLUE, size=10.5)

    deck.text(page, "Готово, когда", 18, 150, 42, 7, size=11, color=MUTED,
              bold=True)
    gates = [
        ("100%", "documents с UID", TEAL),
        ("0", "расхождений current", GREEN),
        ("100%", "новых findings с UID", PURPLE),
        ("0", "мутаций completed run", BLUE),
        ("100%", "manifest со schema", AMBER),
    ]
    for idx, (value, label, color) in enumerate(gates):
        x = 63 + idx * 52
        deck.card(page, x, 146, 47, 27, fill=PANEL_2, line=color)
        deck.text(page, value, x + 3, 150, 41, 8, size=13, color=color,
                  bold=True, align=CENTER)
        deck.text(page, label, x + 3, 160, 41, 8, size=7.8, color=TEXT,
                  align=CENTER)

    deck.rect(page, 18, 177, 304, 2, TEAL, radius=1)
    deck.footer(page)


def connect_office(port: int, profile: Path):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice не найден")

    command = [
        soffice,
        f"-env:UserInstallation={profile.as_uri()}",
        "--headless",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--norestore",
        f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_context
    )
    connection = (
        f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    )
    for _ in range(80):
        try:
            context = resolver.resolve(connection)
            return process, context
        except Exception:
            if process.poll() is not None:
                raise RuntimeError("LibreOffice завершился до подключения")
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError("Не удалось подключиться к LibreOffice")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    profile = Path(tempfile.mkdtemp(prefix="s1-presentation-lo-"))
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
        deck = Deck(document)
        slide_1(deck)
        slide_2(deck)
        slide_3(deck)
        slide_4(deck)
        slide_5(deck)
        slide_6(deck)
        slide_7(deck)
        slide_8(deck)

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
