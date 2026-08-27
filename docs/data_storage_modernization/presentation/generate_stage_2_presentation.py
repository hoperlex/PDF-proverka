#!/usr/bin/env /usr/bin/python3
"""Собрать ODP/PDF-презентацию нового этапа 2: файлы, S3 и ingest."""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import uno  # noqa: F401
from com.sun.star.drawing.TextVerticalAdjust import CENTER as V_CENTER
from com.sun.star.style.ParagraphAdjust import CENTER, RIGHT

from generate_stage_1_presentation import (
    AMBER,
    AMBER_DARK,
    BG,
    BLUE,
    BLUE_DARK,
    Deck,
    GREEN,
    GREEN_DARK,
    LINE,
    MUTED,
    PANEL,
    PANEL_2,
    PURPLE,
    PURPLE_DARK,
    RED,
    RED_DARK,
    TEAL,
    TEAL_DARK,
    TEXT,
    connect_office,
    property_value,
)


OUT_DIR = Path(__file__).resolve().parent
ODP_PATH = OUT_DIR / "02_unified_storage_presentation.odp"
PDF_PATH = OUT_DIR / "02_unified_storage_presentation.pdf"


class Stage2Deck(Deck):
    def header(self, page, title: str, subtitle: str, number: int):
        self.pill(page, "STORAGE MODERNIZATION · ЭТАП 2", 18, 10, 67)
        self.text(page, title, 18, 22, 274, 17, size=26, bold=True)
        self.text(page, subtitle, 18, 39, 286, 10, size=11.5, color=MUTED)
        self.text(page, f"{number:02d}", 306, 12, 16, 8, size=10,
                  color=MUTED, bold=True, align=RIGHT)
        self.line(page, 18, 52, 304, color=LINE, width=0.35)

    def footer(self, page, source: str = ""):
        if source:
            self.text(page, source, 18, 181.5, 270, 4,
                      size=7.5, color=MUTED)
        self.text(page, "PDF-proverka · 27.08.2026", 275, 181.5, 47, 4,
                  size=7.5, color=MUTED, align=RIGHT)


def down(deck: Deck, page, x: float, y: float, color: int = MUTED):
    deck.text(page, "↓", x, y, 10, 8, size=15, color=color,
              bold=True, align=CENTER, valign=V_CENTER)


def slide_1(deck: Stage2Deck):
    page = deck.new_slide()
    deck.pill(page, "НОВЫЙ ЭТАП 2 · ПРЕЖНИЙ ЭТАП 3", 18, 13, 88)
    deck.text(page, "2", 18, 32, 42, 20, size=44, bold=True, color=PURPLE)
    deck.text(page, "Единый файловый контур,\nсобственный S3 и импорт",
              18, 54, 200, 42, size=28, bold=True)
    deck.text(page,
              "Один ingest и один Storage Service. Внешний S3 — только опциональный adapter.",
              18, 104, 200, 18, size=14.2, color=MUTED)

    deck.rect(page, 18, 134, 200, 27, PURPLE_DARK, line=PURPLE, radius=4)
    deck.text(page, "Главный результат", 25, 139, 48, 6,
              size=9, color=PURPLE, bold=True)
    deck.text(page,
              "Собственный S3 хранит долговечные байты;\nлокальный диск — staging, workspace и кэш.",
              25, 147, 185, 12, size=12.2, bold=True)

    nodes = [
        (230, 32, "Sources", "browser обязателен", TEAL_DARK, TEAL),
        (230, 75, "Ingest", "stream + verify", BLUE_DARK, BLUE),
        (230, 118, "Own S3", "immutable blobs", PURPLE_DARK, PURPLE),
    ]
    for x, y, title, desc, fill, color in nodes:
        deck.card(page, x, y, 82, 27, fill=fill, line=color)
        deck.text(page, title, x + 5, y + 4, 72, 7, size=12,
                  color=color, bold=True, align=CENTER)
        deck.text(page, desc, x + 5, y + 15, 72, 6, size=8.5,
                  color=TEXT, align=CENTER)
    down(deck, page, 266, 61)
    down(deck, page, 266, 104)
    deck.footer(page, "Основа: 00_global_plan.md · 02_unified_file_storage_and_ingest.md")


def slide_2(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Почему прежний этап внешней доставки удалён",
                "Функции нет в коде, а отдельный проект дублировал бы весь файловый контур.", 2)

    facts = [
        ("НЕТ", "S3 SDK и\nsource adapter", RED_DARK, RED),
        ("НЕТ", "credentials, API\nи UI", RED_DARK, RED),
        ("ЕСТЬ", "browser upload\nи локальный path", TEAL_DARK, TEAL),
        ("НУЖЕН", "собственный S3\nбез ожидания извне", PURPLE_DARK, PURPLE),
    ]
    for idx, (value, label, fill, color) in enumerate(facts):
        x = 18 + idx * 77
        deck.card(page, x, 66, 69, 42, fill=fill, line=color)
        deck.text(page, value, x + 4, 72, 61, 9, size=15,
                  color=color, bold=True, align=CENTER)
        deck.text(page, label, x + 6, 87, 57, 14, size=9,
                  color=TEXT, align=CENTER)

    deck.card(page, 18, 122, 145, 44, fill=RED_DARK, line=RED)
    deck.text(page, "Было", 25, 128, 30, 7, size=10, color=RED, bold=True)
    deck.text(page, "1 → внешний импорт → свой S3 → PostgreSQL",
              25, 140, 130, 15, size=11.2, bold=True)

    deck.card(page, 177, 122, 145, 44, fill=GREEN_DARK, line=GREEN)
    deck.text(page, "Стало", 184, 128, 34, 7, size=10, color=GREEN, bold=True)
    deck.text(page, "1 → единый storage + ingest → PostgreSQL",
              184, 140, 130, 15, size=11.2, bold=True)
    deck.footer(page, "ADR_external_sources_are_optional.md")


def slide_3(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Один путь для всех входных каналов",
                "Adapter получает поток; публикацией версии управляет только общий ingest.", 3)

    sources = [
        ("Browser", "обязательный", TEAL),
        ("Local admin", "allowlisted", BLUE),
        ("HTTPS", "опционально", AMBER),
        ("External S3", "опционально", PURPLE),
    ]
    for idx, (title, tag, color) in enumerate(sources):
        x = 18 + idx * 76
        deck.card(page, x, 62, 68, 27, fill=PANEL, line=color)
        deck.text(page, title, x + 4, 67, 60, 7, size=11,
                  color=color, bold=True, align=CENTER)
        deck.text(page, tag, x + 4, 78, 60, 5, size=7.8,
                  color=MUTED, align=CENTER)

    down(deck, page, 164, 94, TEAL)
    pipeline = [
        ("2.1", "staging · unpack · classify · precheck", TEAL_DARK, TEAL),
        ("2.2", "blob_id · checksum · manifest schema 2", BLUE_DARK, BLUE),
        ("2.3", "own S3 · immutable key · verify", PURPLE_DARK, PURPLE),
        ("PUB", "atomic version publication", GREEN_DARK, GREEN),
    ]
    for idx, (num, text, fill, color) in enumerate(pipeline):
        y = 104 + idx * 18
        deck.card(page, 64, y, 210, 14, fill=fill, line=color)
        deck.pill(page, num, 70, y + 3, 19, fill=PANEL_2, color=color, size=7.5)
        deck.text(page, text, 95, y + 3, 170, 6, size=9.2,
                  color=TEXT, bold=True, align=CENTER)
    deck.footer(page, "02_01_streaming_ingest.md")


def slide_4(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Сегментация 2.0–2.7",
                "Каждый сегмент даёт самостоятельный результат и собственный acceptance gate.", 4)

    segments = [
        ("2.0", "Security + baseline", RED),
        ("2.1", "Streaming ingest", TEAL),
        ("2.2", "Storage Core", BLUE),
        ("2.3", "S3 new writes", PURPLE),
        ("2.4", "Backfill + cutover", GREEN),
        ("2.5", "Source adapters", AMBER),
        ("2.6", "Derived + cache", BLUE),
        ("2.7", "Operations + DR", TEAL),
    ]
    for idx, (num, title, color) in enumerate(segments):
        col, row = idx % 4, idx // 4
        x, y = 18 + col * 77, 68 + row * 49
        deck.card(page, x, y, 69, 39, fill=PANEL, line=color)
        deck.text(page, num, x + 5, y + 5, 20, 8, size=13,
                  color=color, bold=True)
        deck.text(page, title, x + 5, y + 18, 59, 13, size=9.5,
                  color=TEXT, bold=True, align=CENTER)

    deck.rect(page, 18, 169, 304, 8, AMBER_DARK, line=AMBER, radius=3)
    deck.text(page, "2.5 можно пропустить: отсутствие внешнего adapter не блокирует 2.0–2.4, 2.6–2.7 и этап 3.",
              23, 170, 294, 6, size=8.8, color=AMBER, bold=True, align=CENTER)
    deck.footer(page)


def slide_5(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Storage Core: логика не знает bucket и path",
                "Бизнес-код работает с blob_id, role и manifest через единый facade.", 5)

    deck.card(page, 18, 64, 92, 96, fill=BLUE_DARK, line=BLUE)
    deck.text(page, "Storage Service", 25, 72, 78, 8,
              size=15, color=BLUE, bold=True, align=CENTER)
    api = ["put_path / put_stream", "open_stream / Range", "materialize", "ensure_derived", "stat / controlled delete"]
    for idx, item in enumerate(api):
        deck.pill(page, item, 28, 91 + idx * 13, 72,
                  fill=PANEL_2, color=TEXT, size=8)

    deck.text(page, "→", 113, 105, 15, 10, size=18, color=MUTED,
              bold=True, align=CENTER)
    deck.card(page, 130, 64, 82, 96, fill=PURPLE_DARK, line=PURPLE)
    deck.text(page, "Blob + manifest", 138, 72, 66, 8,
              size=15, color=PURPLE, bold=True, align=CENTER)
    deck.text(page, "blob_id", 142, 94, 58, 8, size=12,
              color=TEXT, bold=True, align=CENTER)
    deck.text(page, "role · size · SHA-256", 140, 109, 62, 8,
              size=9, color=MUTED, align=CENTER)
    deck.text(page, "immutable input/run manifest", 140, 126, 62, 14,
              size=9, color=TEXT, align=CENTER)
    deck.text(page, "schema_version: 2", 142, 145, 58, 7,
              size=8.5, color=PURPLE, bold=True, align=CENTER)

    deck.text(page, "→", 215, 105, 15, 10, size=18, color=MUTED,
              bold=True, align=CENTER)
    deck.card(page, 232, 64, 90, 96, fill=GREEN_DARK, line=GREEN)
    deck.text(page, "Adapters", 240, 72, 74, 8,
              size=15, color=GREEN, bold=True, align=CENTER)
    for idx, item in enumerate(["local primary", "S3 shadow", "S3 canary", "S3 primary"]):
        deck.pill(page, item, 244, 92 + idx * 15, 66,
                  fill=PANEL_2, color=TEXT, size=8)
    deck.footer(page, "Object key не несёт бизнес-смысла; SHA-256 не заменяет blob_id")


def slide_6(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Миграция без big bang",
                "Сначала теневая запись и сверка, удаление локальных файлов — только после restore drill.", 6)

    phases = [
        ("A", "Inventory", "roles · bytes · hardlinks", TEAL),
        ("B", "Shadow", "идемпотентный upload", BLUE),
        ("C", "Parity", "size + SHA-256", PURPLE),
        ("D", "Canary", "read по объекту", AMBER),
        ("E", "Primary", "S3 source of truth", GREEN),
        ("F", "Restore", "DR + cleanup", RED),
    ]
    for idx, (letter, title, desc, color) in enumerate(phases):
        x = 18 + idx * 51
        deck.card(page, x, 72, 43, 57, fill=PANEL, line=color)
        deck.ellipse(page, x + 15, 64, 13, 13, PANEL_2, line=color)
        deck.text(page, letter, x + 15, 66, 13, 7, size=9,
                  color=color, bold=True, align=CENTER, valign=V_CENTER)
        deck.text(page, title, x + 4, 84, 35, 7, size=10,
                  color=color, bold=True, align=CENTER)
        deck.text(page, desc, x + 4, 101, 35, 16, size=7.7,
                  color=TEXT, align=CENTER)
        if idx < len(phases) - 1:
            deck.text(page, "→", x + 43, 92, 8, 8, size=11,
                      color=MUTED, bold=True, align=CENTER)

    deck.card(page, 18, 145, 304, 25, fill=RED_DARK, line=RED)
    deck.text(page, "STOP CONDITIONS", 25, 151, 44, 6,
              size=8, color=RED, bold=True)
    deck.text(page,
              "checksum mismatch · неизвестный файл · нет свободного staging · backup/restore не доказан",
              73, 149, 240, 10, size=9, color=TEXT, bold=True, align=CENTER)
    deck.footer(page, "Append-only migration journal хранится отдельно от мигрируемого дерева")


def slide_7(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Внешние источники — адаптер, не этап",
                "Они подключаются после общего контура и никогда не становятся каноникой.", 7)

    adapters = [
        ("Browser", "ОБЯЗАТЕЛЕН", "production + rollback", TEAL_DARK, TEAL),
        ("HTTPS pull", "ОПЦИЯ", "точный generation + digest", BLUE_DARK, BLUE),
        ("External S3", "ОПЦИЯ", "read-only role + VersionId", PURPLE_DARK, PURPLE),
        ("Push inbox", "ОПЦИЯ", "quarantine prefix", AMBER_DARK, AMBER),
    ]
    for idx, (title, status, desc, fill, color) in enumerate(adapters):
        x = 18 + idx * 77
        deck.card(page, x, 67, 69, 51, fill=fill, line=color)
        deck.text(page, title, x + 4, 73, 61, 8, size=11,
                  color=color, bold=True, align=CENTER)
        deck.pill(page, status, x + 12, 88, 45,
                  fill=PANEL_2, color=color, size=7.2)
        deck.text(page, desc, x + 6, 103, 57, 10, size=7.8,
                  color=TEXT, align=CENTER)

    deck.card(page, 18, 135, 145, 32, fill=RED_DARK, line=RED)
    deck.text(page, "C-07", 25, 143, 28, 8, size=14, color=RED, bold=True)
    deck.text(page, "Удалённый воркер не получает S3 credentials.",
              55, 141, 100, 13, size=9, color=TEXT, bold=True, align=CENTER)

    deck.card(page, 177, 135, 145, 32, fill=GREEN_DARK, line=GREEN)
    deck.text(page, "S3 ГЕЙТ", 184, 143, 30, 8, size=10.5, color=GREEN, bold=True)
    deck.text(page, "S3 ADR + граница C-07 утверждены до shadow-write.",
              215, 140, 99, 15, size=8.7, color=TEXT, bold=True, align=CENTER)
    deck.footer(page, "Без владельца/контракта/выгоды optional adapter остаётся backlog")


def slide_8(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Пользовательская производительность",
                "S3 сам по себе не ускоряет UI: нужны Range, materialize cache и фоновые derivatives.", 8)

    columns = [
        ("Загрузка", ["stream в staging", "RAM не растёт с ZIP", "безопасный retry"], TEAL),
        ("PDF", ["Range-чтение", "короткий content URL", "одна materialize-копия"], BLUE),
        ("Кропы", ["ensure_derived(recipe)", "background render", "placeholder + poll"], PURPLE),
        ("Эксплуатация", ["quota + retention", "cache hit ratio", "P50/P95 + cost"], AMBER),
    ]
    for idx, (title, bullets, color) in enumerate(columns):
        x = 18 + idx * 77
        deck.card(page, x, 66, 69, 91, fill=PANEL, line=color)
        deck.text(page, title, x + 5, 73, 59, 8, size=12,
                  color=color, bold=True, align=CENTER)
        for j, item in enumerate(bullets):
            deck.rect(page, x + 8, 94 + j * 20, 4, 4, color, radius=2)
            deck.text(page, item, x + 15, 91 + j * 20, 47, 12,
                      size=8.7, color=TEXT)

    deck.text(page,
              "Критерий: измеренное улучшение без второго ingest и без обязательной внешней зависимости.",
              18, 169, 304, 7, size=9.5, color=GREEN, bold=True, align=CENTER)
    deck.footer(page)


def slide_9(deck: Stage2Deck):
    page = deck.new_slide()
    deck.header(page, "Когда этап 2 действительно завершён",
                "Не после создания bucket, а после cutover, восстановления и измеренного пользовательского результата.", 9)

    checks = [
        ("1", "Единый streaming ingest", TEAL),
        ("2", "Storage Service — единственный writer", BLUE),
        ("3", "Manifest schema 2: blob_id + SHA", PURPLE),
        ("4", "S3 ADR → primary + historical parity", GREEN),
        ("5", "Range/materialize/derivatives работают", AMBER),
        ("6", "Backup + restore + rollback PASS", RED),
        ("7", "Воркеры без S3 credentials", BLUE),
        ("8", "Adapter 2.5 не является гейтом", TEAL),
    ]
    for idx, (num, text, color) in enumerate(checks):
        col, row = idx % 2, idx // 2
        x, y = 18 + col * 154, 66 + row * 26
        deck.card(page, x, y, 145, 20, fill=PANEL, line=color)
        deck.ellipse(page, x + 6, y + 5, 10, 10, PANEL_2, line=color)
        deck.text(page, num, x + 6, y + 7, 10, 5, size=7.5,
                  color=color, bold=True, align=CENTER)
        deck.text(page, text, x + 21, y + 5, 117, 8, size=9.2,
                  color=TEXT, bold=True)

    deck.rect(page, 18, 172, 304, 3, PURPLE, radius=1)
    deck.footer(page, "Дальше: этап 3 — PostgreSQL · этап 4 — индексы · этап 5 — отключение наследия")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    profile = Path(tempfile.mkdtemp(prefix="s2-storage-presentation-lo-"))
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
        deck = Stage2Deck(document)
        slide_1(deck)
        slide_2(deck)
        slide_3(deck)
        slide_4(deck)
        slide_5(deck)
        slide_6(deck)
        slide_7(deck)
        slide_8(deck)
        slide_9(deck)

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
