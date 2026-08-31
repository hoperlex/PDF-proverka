"""Redaction командных строк CI-harness (P-13 ADR Bible).

Что доказывают эти тесты
────────────────────────
До правки инвентарь дочерних процессов публиковал сырой `/proc/*/cmdline` в
трёх артефактах сразу: JUnit, журнал событий и диагностику таймаута.
Синтетический `--token=TEST_SECRET_SENTINEL` действительно попадал во все три.
P-13 объявляет redaction контрактом: секреты, presigned URL, cookies и ПДн не
попадают ни в один канал по умолчанию.

Здесь проверяется три вещи:

  1. ни одна известная форма секрета не переживает redaction;
  2. полезная диагностика при этом сохраняется — иначе инвентарь перестанет
     отвечать на вопрос «что за процесс висел», ради которого он и снимается;
  3. локальное правило не разошлось с правилом репозитория
     (`backend/app/core/action_log._scrub`). Оно продублировано сознательно —
     импорт того модуля загружает `.env` и втаскивает боевой секрет в процесс
     pytest (находка OPS03-F1), — поэтому расхождение обязано ловиться тестом,
     а не обнаруживаться на инциденте.

Run: python -m pytest tests/test_ci_redaction.py -q -p no:cacheprovider
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from ci_redaction import redact_cmdline, redact_text  # noqa: E402

SENTINEL = "TEST_SECRET_SENTINEL"
REDACTED_MARK = "[redacted"

#: Корпус форм секрета. Каждая запись — argv, внутри которого спрятан SENTINEL
#: (или иной секрет), и ни одна не имеет права его пережить.
SECRET_ARGV: list[tuple[str, list[str]]] = [
    ("флаг со значением через =", ["app", f"--token={SENTINEL}", "--port=8081"]),
    ("флаг со значением через пробел", ["app", "--api-key", SENTINEL, "--verbose"]),
    ("короткий флаг через пробел", ["app", "--secret", SENTINEL]),
    ("переменная окружения в argv", ["env", f"OPENROUTER_API_KEY={SENTINEL}", "app"]),
    ("password в присвоении", ["app", f"--password={SENTINEL}"]),
    ("cookie", ["curl", "-H", f"Cookie: session={SENTINEL}"]),
    ("authorization bearer", ["curl", "-H", f"Authorization: Bearer {SENTINEL}_LONGER"]),
    ("presigned URL", ["curl", f"https://s3.example.com/o?X-Amz-Signature={SENTINEL}&e=1"]),
    ("userinfo в URL", ["app", "--url", f"https://user:{SENTINEL}@host/path"]),
    ("json-подобное присвоение", ["app", "--cfg", f'{{"api_key":"{SENTINEL}"}}']),
]

#: Секреты, узнаваемые по форме, а не по имени рядом.
SHAPED_SECRETS: list[tuple[str, str]] = [
    ("JWT", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"),
    ("AWS access key", "AKIAIOSFODNN7EXAMPLE"),
    ("GitHub token", "ghp_16C7e42F292c6912E7710c838347Ae178B4a"),
    ("Slack token", "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"),
    ("Google API key", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
    ("OpenAI-подобный", "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD"),
    ("длинный непрозрачный блоб", "aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW3xY5zA7bC9dE1f"),
]


@pytest.mark.parametrize("label,argv", SECRET_ARGV, ids=[c[0] for c in SECRET_ARGV])
def test_named_secret_never_survives_redaction(label: str, argv: list[str]) -> None:
    """Секрет, названный своим именем, вырезается в любой форме записи.

    Форма «через пробел» разобрана отдельно не случайно: правило для свободного
    текста её пропускает, потому что требует `=` или `:`. Здесь границы
    аргументов ещё известны, поэтому fail-closed вырезает следующий токен, не
    разбирая его вид.
    """
    result = redact_cmdline(argv)
    assert SENTINEL not in result, f"{label}: секрет пережил redaction — {result!r}"


@pytest.mark.parametrize("label,secret", SHAPED_SECRETS, ids=[c[0] for c in SHAPED_SECRETS])
def test_shaped_secret_is_recognised_without_a_name(label: str, secret: str) -> None:
    """Секрет узнаётся по форме, даже если рядом нет подсказывающего имени.

    В командной строке ключ часто стоит голым позиционным аргументом — тогда
    правило «имя=значение» не срабатывает вовсе, и остаётся только форма.
    """
    result = redact_cmdline(["app", secret, "--port=8081"])
    assert secret not in result, f"{label}: секрет пережил redaction — {result!r}"


def test_diagnostics_survive_redaction() -> None:
    """Redaction не имеет права съесть саму причину, ради которой снят инвентарь.

    Если под правило попадёт каждый длинный путь, диагностика перестанет
    отвечать на вопрос «что за процесс висел», и инвентарь станет бесполезен.
    Поэтому проверяем обратное направление тоже.
    """
    argv = [
        "/root/projects/PDF-proverka/.venv/bin/python3",
        "-m", "uvicorn", "backend.app.main:app",
        "--host", "127.0.0.1", "--port", "8081", "--reload",
    ]
    result = redact_cmdline(argv)
    assert "uvicorn" in result
    assert "backend.app.main:app" in result
    assert "8081" in result
    assert "127.0.0.1" in result
    assert "[redacted" not in result, f"вычищено лишнее: {result!r}"


#: Флаги, которые ВЫГЛЯДЯТ секретными из-за короткой подстроки внутри слова.
#: Без границ слова `sig` внутри `design` и `pin` внутри `spin` вырезали бы
#: совершенно безобидные значения — измерено, `--spin-up worker` превращался в
#: `--spin-up [redacted]`.
LOOKALIKE_ARGV: list[tuple[str, list[str]]] = [
    ("sig внутри design", ["app", "--design-output", "plan.png"]),
    ("pin внутри spin", ["app", "--spin-up", "worker"]),
    ("sas внутри sasl", ["app", "--sasl-mechanism", "PLAIN"]),
    ("otp внутри optimize", ["app", "--optimize-level", "3"]),
]


@pytest.mark.parametrize("label,argv", LOOKALIKE_ARGV, ids=[c[0] for c in LOOKALIKE_ARGV])
def test_lookalike_flags_do_not_lose_their_values(label: str, argv: list[str]) -> None:
    """Похожее на секрет имя — ещё не секрет.

    Перередактирование здесь не безобидно: инвентарь снимают, чтобы узнать,
    ЧТО за процесс висел, и вычищенный ответ равносилен отсутствию ответа.
    Правило разделяет случаи границами слова — тем же приёмом и по той же
    причине, что и `action_log._SENSITIVE_NAME_RE`.
    """
    result = redact_cmdline(argv)
    assert REDACTED_MARK not in result, f"{label}: вычищено лишнее — {result!r}"
    assert argv[-1] in result


def test_genuine_short_secret_names_still_redact() -> None:
    """Границы слова не должны ослабить правило там, где имя настоящее."""
    for flag in ("--sig", "--sas-token", "--otp", "--pin", "--salt", "--pwd"):
        result = redact_cmdline(["app", flag, SENTINEL])
        assert SENTINEL not in result, f"{flag}: секрет пережил redaction — {result!r}"


def test_flag_without_value_at_the_end_does_not_crash() -> None:
    """Секретный флаг последним токеном: значения нет, падать не на чем."""
    assert redact_cmdline(["app", "--token"]) == "app --token"


def test_control_characters_are_stripped() -> None:
    """Управляющие символы ломают XML отчёта и в артефакте не нужны."""
    assert "\x00" not in redact_cmdline(["app", "a\x00b"])
    assert "\x1b" not in redact_cmdline(["app", "\x1b[31mred"])


def test_empty_argv_is_empty_string() -> None:
    assert redact_cmdline([]) == ""


# ---------------------------------------------------------------------------
# Сверка с правилом репозитория
# ---------------------------------------------------------------------------


def _repo_scrub():
    """Правило redaction из `backend/app/core/action_log`, если оно доступно."""
    try:
        from backend.app.core.action_log import _scrub
    except Exception as exc:  # pragma: no cover — зависит от окружения
        pytest.skip(f"правило репозитория недоступно: {type(exc).__name__}: {exc}")
    return _scrub


@pytest.mark.parametrize("label,secret", SHAPED_SECRETS, ids=[c[0] for c in SHAPED_SECRETS])
def test_local_rule_agrees_with_the_repository_rule(label: str, secret: str) -> None:
    """Два правила не разошлись на одном корпусе секретов.

    Локальное правило продублировано сознательно: импорт репозиторного модуля
    загружает `.env` и добавляет в окружение процесса боевой provider-секрет
    (OPS03-F1). Плагин, который ради защиты от утечки сам затаскивает секрет в
    процесс pytest, — нерабочее решение. Цена дубликата — риск расхождения,
    и оплачивается он этим тестом.
    """
    scrub = _repo_scrub()
    text = f"app {secret} --port=8081"
    assert secret not in scrub(text), f"{label}: правило репозитория пропустило"
    assert secret not in redact_text(text), f"{label}: локальное правило пропустило"


def test_local_rule_is_stricter_on_space_separated_secrets() -> None:
    """Отличие от репозиторного правила — сознательное и в сторону строгости.

    `--token SECRET` через пробел правило для свободного текста пропускает: оно
    требует `=` или `:`, а в склеенной строке границы аргументов уже потеряны.
    Локальное правило работает по argv, где границы известны, и потому строже.
    Тест фиксирует именно это — чтобы отличие не приняли за дефект.
    """
    scrub = _repo_scrub()
    argv = ["app", "--api-key", SENTINEL]
    assert SENTINEL in scrub(" ".join(argv)), (
        "правило репозитория неожиданно ловит форму через пробел — "
        "тогда обоснование дубликата надо пересмотреть"
    )
    assert SENTINEL not in redact_cmdline(argv)
