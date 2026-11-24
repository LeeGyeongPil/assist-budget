"""AC-7: the offline Tekken tokenizer (optional extra) and the exit-2 path without it."""

from __future__ import annotations

import sys

import pytest

from assist_budget.cli import main
from assist_budget.errors import AssistBudgetError
from assist_budget.tokenize import get_tokenizer
from conftest import HOUSE

# Measured with mistral-common 1.13.1 on the sample house: see build-notes.md.
TEKKEN_SYSTEM_PROMPT_TOKENS = 5382
TEKKEN_STATIC_TOKENS = 5030


def test_approx_is_characters_over_four_rounded_up():
    count = get_tokenizer("approx").count
    assert count("") == 0
    assert count("abcd") == 1 and count("abcde") == 2
    assert count("거실" * 4) == 2  # counts characters, not bytes


def test_unknown_tokenizer_is_rejected():
    with pytest.raises(AssistBudgetError) as error:
        get_tokenizer("gpt-5")
    assert error.value.exit_code == 2 and "approx, tekken" in str(error.value)


def test_missing_extra_exit2(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mistral_common", None)  # makes the import fail like a missing package
    code = main(["--lang", "en", "report", str(HOUSE), "--tokenizer", "tekken"])
    assert code == 2
    assert "pip install 'assist-budget[tekken]'" in capsys.readouterr().err


def test_missing_extra_message_in_korean(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mistral_common", None)
    assert main(["--lang", "ko", "report", str(HOUSE), "--tokenizer", "tekken"]) == 2
    err = capsys.readouterr().err
    assert "선택 패키지" in err and "pip install 'assist-budget[tekken]'" in err


def test_tekken_counts_system_prompt_offline(house_rec):
    pytest.importorskip("mistral_common")
    from assist_budget.report import build_report

    storage, rec = house_rec
    tokenizer = get_tokenizer("tekken")
    report = build_report(rec, tokenizer, ha_version="2026.11.3", ctx=8192)
    assert report["tokenizer"] == "tekken"
    assert report["system_prompt_tokens"] == TEKKEN_SYSTEM_PROMPT_TOKENS
    assert report["static_context_tokens"] == TEKKEN_STATIC_TOKENS
    # Tekken never merges tokens across entries, so the per-entity counts add up exactly.
    assert sum(row["tokens"] for row in report["entities"]) == report["static_context_tokens"]
    # The rough estimate is lower than the real tokenizer, which is why the default margin is 10%.
    approx = build_report(rec, get_tokenizer("approx"), ha_version="2026.11.3", ctx=8192)
    assert approx["system_prompt_tokens"] < report["system_prompt_tokens"]
