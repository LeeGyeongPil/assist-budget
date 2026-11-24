"""AC-9: English and Korean messages: same keys, working switch, documented precedence."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

import assist_budget
from assist_budget.cli import build_parser, main
from assist_budget.i18n import messages, resolve_lang, translate
from conftest import HOUSE

SRC = Path(assist_budget.__file__).parent
PLACEHOLDER = re.compile(r"\{(\w+)\}")
KEY_LIKE = re.compile(r"^(err|warn|help|report|apply|undo|demo|suggest|verdict|col)_\w+$")


def test_keys_identical():
    en, ko = messages("en"), messages("ko")
    assert set(en) == set(ko)
    for key in en:
        assert set(PLACEHOLDER.findall(en[key])) == set(PLACEHOLDER.findall(ko[key])), key
        assert en[key].strip() and ko[key].strip(), key


def test_every_key_used_in_code_exists_and_none_is_unused():
    used: set[str] = set()
    for path in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and KEY_LIKE.match(node.value):
                used.add(node.value)
    used |= {"error_prefix", "warn_prefix", "interrupted", "no_area", "help_apply", "help_undo",
             "help_apply_file", "help_undo_file", "help_apply_yes", "help_undo_yes",
             "verdict_fits", "verdict_tight", "verdict_over"}  # built from f-strings
    missing = used - set(messages("en"))
    assert not missing, f"keys used in code but missing from the message tables: {sorted(missing)}"
    unused = set(messages("en")) - used
    assert not unused, f"messages that no code uses: {sorted(unused)}"


def test_translate_falls_back_to_english_and_fills_placeholders():
    assert translate("ko", "err_no_token", name="HA_TOKEN").count("HA_TOKEN") == 2
    assert translate("en", "does_not_exist") == "does_not_exist"


def test_unsupported_language_is_rejected():
    with pytest.raises(ValueError, match="unsupported language"):
        messages("fr")


def test_precedence():
    env = {"ASSIST_BUDGET_LANG": "ko", "LC_ALL": "en_US.UTF-8", "LC_MESSAGES": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
    assert resolve_lang("en", env) == "en"  # --lang beats everything
    assert resolve_lang(None, env) == "ko"  # then ASSIST_BUDGET_LANG
    del env["ASSIST_BUDGET_LANG"]
    assert resolve_lang(None, env) == "en"
    assert resolve_lang(None, {"LC_ALL": "ko_KR.UTF-8", "LANG": "en_US.UTF-8"}) == "ko"  # LC_ALL beats LANG
    assert resolve_lang(None, {"LC_MESSAGES": "ko_KR.UTF-8", "LANG": "en_US.UTF-8"}) == "ko"
    assert resolve_lang(None, {"LANG": "ko_KR.UTF-8"}) == "ko"
    assert resolve_lang(None, {"LC_ALL": "", "LANG": "ko_KR.UTF-8"}) == "ko"  # empty means unset
    assert resolve_lang(None, {"LANG": "fr_FR.UTF-8"}) == "en"  # anything but Korean is English
    assert resolve_lang(None, {}) == "en"


def test_precedence_in_the_cli(monkeypatch, capsys):
    for name in ("ASSIST_BUDGET_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    main(["report", str(HOUSE)])
    assert "판정" in capsys.readouterr().out
    monkeypatch.setenv("ASSIST_BUDGET_LANG", "en")
    main(["report", str(HOUSE)])
    assert "Verdict" in capsys.readouterr().out
    main(["--lang", "ko", "report", str(HOUSE)])
    assert "판정" in capsys.readouterr().out


def test_help_ko_en(capsys):
    for lang, needle, absent in (("en", "Measure what Home Assistant Assist sends", "컨텍스트 창"),
                                 ("ko", "프롬프트를 재구성해", "Measure what")):
        with pytest.raises(SystemExit) as exit_info:
            main_help = build_parser(lang)
            main_help.parse_args(["--help"])
        assert exit_info.value.code == 0
        out = capsys.readouterr().out
        assert needle in out and absent not in out
    assert main(["--lang", "ko", "report", "--help"]) == 0
    assert "컨텍스트 창" in capsys.readouterr().out
    assert main(["--lang=en", "suggest", "--help"]) == 0
    assert "Never hide entities" in capsys.readouterr().out


def test_every_command_help_builds_in_both_languages(capsys):
    for lang in ("en", "ko"):
        for command in ("report", "suggest", "apply", "undo", "demo"):
            assert main(["--lang", lang, command, "--help"]) == 0
            assert capsys.readouterr().out.strip()


def test_report_headings_switch_language(capsys):
    main(["--lang", "en", "report", str(HOUSE), "--ctx", "4096"])
    english = capsys.readouterr().out
    main(["--lang", "ko", "report", str(HOUSE), "--ctx", "4096"])
    korean = capsys.readouterr().out
    assert "Verdict" in english and "over" in english and "판정" not in english
    assert "판정" in korean and "초과(over)" in korean and "Verdict" not in korean


def test_locale_files_are_valid_utf8_json_objects():
    for lang in ("en", "ko"):
        data = json.loads((SRC / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(isinstance(v, str) for v in data.values())


@pytest.mark.parametrize("extra, fragment", [
    (["--ctx", "0"], "0보다 커야"),
    (["--ctx", "abc"], "정수가 아닙니다"),
    (["--margin", "150"], "100 미만"),
    (["--margin", "x"], "숫자가 아닙니다"),
])
def test_argument_errors_are_translated(extra, fragment, capsys):
    with pytest.raises(SystemExit):
        build_parser("ko").parse_args(["report", str(HOUSE), *extra])
    assert fragment in capsys.readouterr().err


def test_argument_error_english_via_main(capsys):
    code = main(["--lang", "en", "report", str(HOUSE), "--ctx", "0"], env={})
    assert code != 0
    assert "must be greater than 0" in capsys.readouterr().err


def test_korean_report_columns_align():
    from assist_budget.report import _cells
    out = main_output_ko()
    # summary block lines (before the first table) share one value column
    summary = out.split("\n\n")[1].splitlines()
    cols = {_cells(l[:len(l) - len(l.split("  ", 1)[1].lstrip())]) for l in summary}
    assert len(cols) == 1, cols


def main_output_ko() -> str:
    import io
    buf = io.StringIO()
    main(["--lang", "ko", "report", str(HOUSE)], env={}, stdout=buf, stderr=io.StringIO())
    return buf.getvalue()
