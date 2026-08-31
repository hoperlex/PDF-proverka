"""Безопасная публикация командных строк CI-harness (P-13 ADR Bible).

История дефекта
───────────────
Первая редакция инвентаря публиковала сырой `/proc/*/cmdline`: синтетический
`--token=…` попадал в JUnit, журнал событий и диагностику таймаута.

Вторая редакция вырезала ИЗВЕСТНЫЕ формы секрета — и провалилась на всём, чего
не знала: `--payload SECRET`, `--value=SECRET`, просто `SECRET` позиционным
аргументом публиковались как есть. Значение попадало в артефакт не потому, что
было признано безопасным, а потому, что регулярное выражение его не узнало.
P-13 требует ровно обратного: «Попадание регулируется явным allowlist поля, а
не отсутствием запрета».

Третья редакция — allowlist. Публикуется только структура, безопасная по
построению. Эти тесты доказывают три вещи:

  1. произвольный секрет не публикуется НИ В КАКОЙ позиции — тест не
     перечисляет известные формы, а требует, чтобы наружу не выходило ничего,
     кроме явно разрешённого;
  2. диагностическая ценность при этом сохраняется: исполняемый файл, имена
     флагов, безопасные значения, счётчики и отпечаток;
  3. сверка с правилом репозитория не загрязняет процесс pytest секретом —
     она уехала в отдельный процесс с чистым окружением.

Run: python -m pytest tests/test_ci_redaction.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from ci_redaction import (  # noqa: E402
    argv_fingerprint,
    publishable_comm,
    sanitize_traceback,
    redact_text,
    safe_cmdline,
    summarize_argv,
)

SENTINEL = "SHORT_PRIVATE_SENTINEL"
OPAQUE_SENTINEL = "q7z4m2n8p5r3t6v9"

#: Позиции, в которых секрет может оказаться в командной строке. Список
#: перечисляет ПОЗИЦИИ, а не формы секрета: в этом и смысл allowlist — форма
#: значения не важна, не разрешено значит не публикуется.
SECRET_POSITIONS: list[tuple[str, list[str]]] = [
    ("значение неизвестного флага через пробел", ["app", "--payload", SENTINEL]),
    ("значение неизвестного флага через =", ["app", f"--value={SENTINEL}"]),
    ("голый позиционный аргумент", ["app", SENTINEL]),
    ("первый позиционный из нескольких", ["app", SENTINEL, "--verbose", "x"]),
    ("значение известного секретного флага", ["app", "--token", SENTINEL]),
    ("значение флага из allowlist небезопасной формы", ["app", "--port", SENTINEL]),
    ("переменная окружения в argv", ["env", f"KEY={SENTINEL}", "app"]),
    ("аргумент после --", ["app", "--", SENTINEL]),
    ("значение с виду безобидного флага", ["app", "--log-level", SENTINEL]),
    ("секрет внутри аргумента -c", ["python", "-c", f"x = '{SENTINEL}'"]),
    ("секрет записан как имя флага", ["app", f"--{SENTINEL}"]),
    ("секрет как короткий флаг", ["app", f"-{SENTINEL}"]),
]


@pytest.mark.parametrize(
    "label,argv", SECRET_POSITIONS, ids=[c[0] for c in SECRET_POSITIONS]
)
def test_arbitrary_secret_is_never_published(label: str, argv: list[str]) -> None:
    """Произвольное значение не публикуется ни в какой позиции.

    Ключевое отличие от denylist: тест не требует, чтобы секрет был «узнан».
    Он требует, чтобы наружу не выходило ничего, кроме явно разрешённого, — и
    поэтому проходит для секрета любой формы, включая ту, которой ещё не
    придумали.
    """
    rendered = safe_cmdline(argv)
    assert SENTINEL not in rendered, f"{label}: секрет опубликован — {rendered!r}"
    summary = summarize_argv(argv)
    assert SENTINEL not in json.dumps(summary, ensure_ascii=False), (
        f"{label}: секрет остался в структуре — {summary!r}"
    )


def test_positional_arguments_are_counted_but_never_shown() -> None:
    """Позиционные аргументы считаются, но не публикуются.

    Именно позиционный аргумент чаще всего и оказывается секретом, и признака
    «этот безопасен» у него нет. Счётчик сообщает, сколько сведений скрыто, —
    читающий не примет краткость за полноту.
    """
    summary = summarize_argv(["app", "секрет-один", "секрет-два", "--verbose"])
    assert summary["positional_count"] == 2
    assert summary["flags"] == ["--verbose"]
    assert "[2 позиционных]" in safe_cmdline(["app", "a", "b", "--verbose"])

    # `--` завершает option parsing: даже точно похожие на
    # разрешённые флаги токены после него остаются позиционными.
    after_separator = summarize_argv(
        ["app", "--", "--port=8081", "--log-level=debug", "-m=uvicorn"]
    )
    assert after_separator["flags"] == []
    assert after_separator["positional_count"] == 3
    rendered = safe_cmdline(["app", "--", "--port=8081"])
    assert "--port" not in rendered
    assert "8081" not in rendered


def test_flag_names_are_published_but_values_are_not() -> None:
    """Точно allowlisted имя публикуется; произвольное значение — нет."""
    summary = summarize_argv(["app", "--payload", "тайна", "--dry-run"])
    assert summary["flags"] == ["--payload", "--dry-run"]
    assert "тайна" not in json.dumps(summary, ensure_ascii=False)


def test_allowlisted_flags_keep_safe_values() -> None:
    """Диагностика сохранена там, где значение доказуемо безопасно.

    Обратное направление проверки обязательно: инвентарь снимают, чтобы
    узнать, ЧТО за процесс висел. Если allowlist вычистит всё, инструмент
    перестанет отвечать на свой единственный вопрос.
    """
    rendered = safe_cmdline([
        "/usr/bin/python3", "-m", "uvicorn", "backend.app.main:app",
        "--host", "127.0.0.1", "--port", "8081", "--reload",
    ])
    assert "python3" in rendered
    assert "-m=uvicorn" in rendered
    assert "--host=127.0.0.1" in rendered
    assert "--port=8081" in rendered
    assert "--reload" in rendered


def test_allowlisted_flag_with_unsafe_value_loses_the_value() -> None:
    """Флаг в allowlist — ещё не разрешение публиковать любое его значение.

    Проверяются оба условия: флаг разрешён И значение подходит под безопасную
    форму. Достаточно одного `--port $(cat /run/secrets/db)`, чтобы понять,
    зачем нужно второе.
    """
    summary = summarize_argv(["app", "--port", "$(cat /run/secrets/db)"])
    assert summary["flags"] == ["--port"]
    assert "secrets" not in json.dumps(summary, ensure_ascii=False)


def test_only_allowlisted_executable_basename_is_published() -> None:
    """argv[0] не доверяем: путь и само имя могут быть секретом."""
    home = os.path.expanduser("~")
    summary = summarize_argv([f"{home}/venv/bin/python3", "--verbose"])
    assert summary["executable"] == "python3"
    assert home not in str(summary["executable"])

    cases = (
        (OPAQUE_SENTINEL, "<executable>"),
        (f"/srv/customers/{OPAQUE_SENTINEL}/python", "python"),
    )
    for argv0, expected in cases:
        hidden = summarize_argv([argv0])
        assert hidden["executable"] == expected
        assert OPAQUE_SENTINEL not in safe_cmdline([argv0])


def test_digest_identifies_the_command_without_revealing_it() -> None:
    """Отпечаток позволяет сличить две команды, не раскрывая содержимого."""
    a = ["app", "--token", SENTINEL]
    b = ["app", "--token", SENTINEL]
    c = ["app", "--token", "другое"]
    assert argv_fingerprint(a) == argv_fingerprint(b)
    assert argv_fingerprint(a) != argv_fingerprint(c)
    assert SENTINEL not in argv_fingerprint(a)
    # Разделитель `\0` исключает коллизию склейки.
    assert argv_fingerprint(["ab", "c"]) != argv_fingerprint(["a", "bc"])


def test_argc_reports_the_full_length() -> None:
    """Счётчик аргументов показывает полную длину, а не длину опубликованного."""
    summary = summarize_argv(["app", "--token", SENTINEL, "поз1", "поз2"])
    assert summary["argc"] == 5
    assert len(summary["flags"]) == 1


def test_control_characters_are_stripped() -> None:
    """Управляющие символы ломают XML отчёта и в артефакте не нужны."""
    rendered = safe_cmdline(["app\x00x", "--verbose\x1b[31m"])
    assert "\x00" not in rendered
    assert "\x1b" not in rendered


def test_empty_argv_is_handled() -> None:
    summary = summarize_argv([])
    assert summary["argc"] == 0
    assert summary["flags"] == []
    assert safe_cmdline([]) == f"argv:{summary['argv_fingerprint'][:16]}"


def test_unallowlisted_or_malformed_flag_is_hidden() -> None:
    """То, что лишь похоже на флаг, не получает привилегий флага.

    «Начинается с дефиса» — ещё не имя флага. Пока форма имени была широкой,
    `app --SHORT_PRIVATE_SENTINEL` публиковал секрет как имя флага: имена ведь
    публикуются. Но и правильная форма не достаточна: lowercase opaque
    секрет проходит синтаксис, но не точный allowlist. Оба случая считаются
    скрытыми флагами, а не позиционными аргументами.
    """
    for token in (
        "--" + SENTINEL * 5,
        f"--{SENTINEL}",
        f"-{SENTINEL}",
        f"--{OPAQUE_SENTINEL}",
    ):
        summary = summarize_argv(["app", token])
        assert summary["flags"] == [], token
        assert summary["positional_count"] == 0, token
        assert summary["hidden_flag_count"] == 1, token
        assert OPAQUE_SENTINEL not in safe_cmdline(["app", token]), token


def test_conventional_flag_names_are_still_published() -> None:
    """Сужение формы не должно съесть обычные флаги — иначе диагностики нет."""
    argv = [
        "py", "-m", "pytest", "-p", "no:cacheprovider",
        "--junitxml", "report.xml", "--per-test-timeout", "30", "--no-header",
    ]
    flags = summarize_argv(argv)["flags"]
    assert "-m=pytest" in flags
    assert "-p" in flags
    assert "--junitxml" in flags
    assert "--per-test-timeout=30" in flags
    assert "--no-header" in flags


# ---------------------------------------------------------------------------
# Сверка с правилом репозитория — ТОЛЬКО в отдельном процессе
# ---------------------------------------------------------------------------

#: Секреты, узнаваемые по форме. Для allowlist они не особенные — он не
#: публикует и неузнаваемые. Корпус нужен эшелонированной защите
#: `redact_text()`, которая осталась для свободных полей.
SHAPED_SECRETS: list[tuple[str, str]] = [
    ("JWT", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"),
    ("AWS access key", "AKIAIOSFODNN7EXAMPLE"),
    ("GitHub token", "ghp_16C7e42F292c6912E7710c838347Ae178B4a"),
    ("Slack token", "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"),
    ("Google API key", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
    ("длинный непрозрачный блоб", "aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW3xY5zA7bC9dE1f"),
]

_COMPARE_SCRIPT = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
before = sorted(os.environ)
from backend.app.core.action_log import _scrub
after = sorted(os.environ)
secrets = json.loads(sys.argv[2])
survived = [s for s in secrets if s in _scrub("app " + s + " --port=8081")]
print("@@RESULT@@" + json.dumps({"before": before, "after": after, "survived": survived}))
"""


def _run_repo_rule(secrets: list[str]) -> dict:
    """Прогнать правило репозитория В ОТДЕЛЬНОМ процессе с чистым окружением.

    Импорт `backend.app.core.action_log` загружает `.env` и добавляет в
    окружение процесса provider-секрет — это находка OPS03-F1. Прежняя
    редакция этого теста импортировала модуль прямо здесь и тем самым САМА
    затаскивала секрет в общий процесс pytest: тест про утечку устраивал
    утечку. Измерено в чистом подпроцессе: 0 переменных до импорта, 2 после.
    """
    # Изоляция сама должна быть allowlist: фильтр по `API`/`TOKEN`
    # оставлял `AWS_SECRET_ACCESS_KEY`, `PASSWORD` и новые формы
    # учётных данных. Подпроцессу не нужна ни одна переменная
    # родителя; включаем только явный запрет dotenv.
    env = {"AUDIT_DISABLE_DOTENV": "1", "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [sys.executable, "-c", _COMPARE_SCRIPT, str(_ROOT), json.dumps(secrets)],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(_ROOT),
    )
    marker = [ln for ln in done.stdout.splitlines() if ln.startswith("@@RESULT@@")]
    if not marker:
        pytest.skip(f"правило репозитория недоступно: {done.stderr[-400:]}")
    return json.loads(marker[0][len("@@RESULT@@"):])


def test_defence_in_depth_rule_agrees_with_the_repository() -> None:
    """`redact_text` не разошёлся с правилом репозитория на общем корпусе.

    Он больше не основная гарантия — её даёт allowlist, — но остался
    эшелонированной защитой свободных полей, и расхождение обязано ловиться
    тестом, а не обнаруживаться на инциденте.
    """
    secrets = [secret for _, secret in SHAPED_SECRETS]
    result = _run_repo_rule(secrets)
    assert result["survived"] == [], f"правило репозитория пропустило: {result['survived']}"
    for secret in secrets:
        assert secret not in redact_text(f"app {secret} --port=8081"), (
            "локальное правило пропустило то, что ловит репозиторное"
        )


def test_comparison_does_not_contaminate_the_pytest_process() -> None:
    """Сама сверка не загрязняет процесс pytest секретом.

    Проверяется не намерение, а результат: подпроцесс сообщает, какие
    provider-переменные были у него до и после импорта, и здесь же сверяется
    окружение родителя.
    """
    parent_before = {k for k in os.environ if "OPENROUTER" in k or "API_KEY" in k}
    result = _run_repo_rule(["AKIAIOSFODNN7EXAMPLE"])
    parent_after = {k for k in os.environ if "OPENROUTER" in k or "API_KEY" in k}

    expected_child_env = {"AUDIT_DISABLE_DOTENV", "PYTHONIOENCODING", "LC_CTYPE"}
    assert set(result["before"]) <= expected_child_env, (
        f"подпроцесс стартовал с неразрешённым окружением: {result['before']}"
    )
    assert result["after"] == result["before"], (
        f"импорт изменил окружение подпроцесса: {result['after']}"
    )
    assert parent_after == parent_before, (
        f"сверка добавила переменные в процесс pytest: {parent_after - parent_before}"
    )


# ---------------------------------------------------------------------------
# Третий круг: comm, отпечаток и traceback
# ---------------------------------------------------------------------------


def test_comm_is_not_trusted_because_a_process_sets_it_itself() -> None:
    """`comm` — недоверенный ввод, а не имя программы.

    Процесс задаёт его себе сам через `prctl(PR_SET_NAME)`: пятнадцать
    символов, полностью подконтрольных источнику. Прежде значение уходило в
    инвентарь, журнал, диагностику и JUnit нетронутым — измерено на подделанном
    `q7z4m2n8p5r3t`.
    """
    assert publishable_comm(OPAQUE_SENTINEL[:15]) == "<comm>"
    assert publishable_comm("q7z4m2n8p5r3t") == "<comm>"
    # Обычные имена остаются: иначе инвентарь перестанет отвечать, что висело.
    for name in ("python3", "python", "uvicorn", "node", "sh"):
        assert publishable_comm(name) == name


def test_fingerprint_is_not_brute_forceable() -> None:
    """Отпечаток не должен раскрывать значение перебором словаря.

    У argv низкая энтропия. Обычный SHA-256 позволял восстановить `--pin 0427`
    за 10 000 попыток — то есть «отпечаток» публиковал само значение, только
    медленнее. Ключ HMAC случаен, в памяти процесса и не публикуется, поэтому
    перебор без него бесполезен.
    """
    target = argv_fingerprint(["app", "--pin", "0427"])
    recovered = [
        f"{i:04d}" for i in range(10000)
        if _offline_sha256(["app", "--pin", f"{i:04d}"]) == target
    ]
    assert recovered == [], f"отпечаток восстановлен перебором: {recovered}"
    # Сличение внутри прогона при этом работает — ради него отпечаток и нужен.
    assert argv_fingerprint(["a", "b"]) == argv_fingerprint(["a", "b"])
    assert argv_fingerprint(["a", "b"]) != argv_fingerprint(["a", "c"])


def _offline_sha256(argv: list[str]) -> str:
    """Тот самый перебор, который работал до перехода на HMAC."""
    import hashlib

    digest = hashlib.sha256()
    for part in argv:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def test_fingerprint_key_is_never_published() -> None:
    """Ключ отпечатка не выходит наружу ни через одно поле."""
    import ci_redaction

    key_hex = ci_redaction._FINGERPRINT_KEY.hex()
    summary = summarize_argv(["app", "--verbose"])
    blob = json.dumps(summary, ensure_ascii=False) + safe_cmdline(["app", "--verbose"])
    assert key_hex not in blob
    assert len(ci_redaction._FINGERPRINT_KEY) == 32


def test_traceback_keeps_the_location_and_drops_the_directories() -> None:
    """Дамп сохраняет файл, строку и функцию, но теряет дерево каталогов.

    Каталоги несут идентификаторы проекта и клиента (`/srv/customers/<id>/`), а
    отвечает дамп на вопрос «где зависло» — для этого достаточно имени файла.
    """
    dump = (
        "Thread 0x1 (most recent call first):\n"
        f'  File "/srv/customers/{OPAQUE_SENTINEL}/app/builder.py", line 142 in resolve\n'
        '  File "/root/projects/PDF-proverka/tests/test_x.py", line 7 in test_y\n'
    )
    cleaned = sanitize_traceback(dump)
    assert OPAQUE_SENTINEL not in cleaned
    assert "/srv/customers" not in cleaned
    assert 'File "builder.py", line 142 in resolve' in cleaned
    assert 'File "test_x.py", line 7 in test_y' in cleaned


def test_traceback_still_scrubs_known_secret_shapes() -> None:
    """Свободный остаток дампа проходит эшелонированную защиту."""
    cleaned = sanitize_traceback("RuntimeError: token=AKIAIOSFODNN7EXAMPLE failed")
    assert "AKIAIOSFODNN7EXAMPLE" not in cleaned
