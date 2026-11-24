"""AC-3: report numbers, consistency of the breakdowns, verdicts and output formats."""

from __future__ import annotations

import json

import pytest

from assist_budget import EXIT_OVER
from assist_budget.cli import main
from assist_budget.report import budget_target, build_report, render, verdict_for
from assist_budget.tokenize import get_tokenizer
from conftest import HOUSE

# Measured on the sample house (written by Home Assistant 2026.11.3): see build-notes.md.
EXPOSED = 207
SYSTEM_PROMPT_TOKENS = 4840


def make_report(house_rec, **kwargs):
    storage, rec = house_rec
    options = {"ha_version": "2026.11.3", "ctx": 8192, **kwargs}
    return build_report(rec, get_tokenizer("approx"), **options)


def test_numbers_for_the_sample_house(house_rec):
    report = make_report(house_rec)
    assert report["exposed"] == EXPOSED
    assert report["tokenizer"] == "approx"
    assert report["system_prompt_tokens"] == SYSTEM_PROMPT_TOKENS
    assert report["usage_pct"] == round(100 * SYSTEM_PROMPT_TOKENS / 8192, 1)
    assert report["verdict"] == "fits"
    assert report["estimate"] == "upper"


def test_breakdown_sums_consistent(house_rec):
    report = make_report(house_rec)
    by_entity = sum(row["tokens"] for row in report["entities"])
    assert sum(row["tokens"] for row in report["by_domain"]) == by_entity
    assert sum(row["tokens"] for row in report["by_area"]) == by_entity
    assert sum(row["entities"] for row in report["by_domain"]) == report["exposed"]
    assert sum(row["entities"] for row in report["by_area"]) == report["exposed"]
    assert len(report["entities"]) == report["exposed"]
    # the entity list is a part of the prompt, so it can never be larger than the prompt
    assert by_entity <= report["system_prompt_tokens"]
    assert report["static_context_tokens"] <= report["system_prompt_tokens"]
    assert report["top_entities"] == report["entities"][:10] or len(report["top_entities"]) == 10


def test_top_is_sorted_and_limited(house_rec):
    report = make_report(house_rec, top=3)
    tokens = [row["tokens"] for row in report["top_entities"]]
    assert len(tokens) == 3 and tokens == sorted(tokens, reverse=True)


@pytest.mark.parametrize(("used", "ctx", "margin", "verdict"), [
    (1000, 8192, 10, "fits"),
    (7372, 8192, 10, "fits"),     # exactly at the margin line
    (7373, 8192, 10, "tight"),
    (8192, 8192, 10, "tight"),    # full, but not over
    (8193, 8192, 10, "over"),
    (4096, 4096, 0, "fits"),
])
def test_verdict_boundaries(used, ctx, margin, verdict):
    assert verdict_for(used, ctx, margin) == verdict


def test_reserve_counts_against_the_window(house_rec):
    plain = make_report(house_rec, ctx=5000)
    reserved = make_report(house_rec, ctx=5000, reserve=1000)
    assert reserved["used_tokens"] == plain["used_tokens"] + 1000
    assert reserved["verdict"] != "fits"
    assert budget_target(5000, 10, 1000) == 3500


def test_cli_json_output_and_fail_over(capsys):
    code = main(["--lang", "en", "report", str(HOUSE), "--ctx", "8192", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["exposed"] == EXPOSED and data["verdict"] == "fits"
    assert main(["report", str(HOUSE), "--ctx", "4096", "--format", "json", "--fail-over"]) == EXIT_OVER
    assert json.loads(capsys.readouterr().out)["verdict"] == "over"
    assert main(["report", str(HOUSE), "--ctx", "4096", "--format", "json"]) == 0  # no flag, no failure


def test_table_and_markdown_outputs(house_rec):
    report = make_report(house_rec)
    table = render(report, "en", "table")
    assert "System prompt tokens" in table and "upper estimate" in table and "sensor" in table
    assert "[" in table  # usage bar
    markdown = render(report, "en", "md")
    assert markdown.startswith("## ") and "| Name | Entities | Tokens |" in markdown


def test_trim_hint_only_when_not_fitting(house_rec):
    assert "Next step" not in render(make_report(house_rec), "en", "table")
    assert "Next step" in render(make_report(house_rec, ctx=4096), "en", "table")


def test_bad_inputs_give_exit_2(tmp_path, capsys):
    assert main(["--lang", "en", "report", str(tmp_path / "missing")]) == 2
    assert "Check the path" in capsys.readouterr().err
    assert main(["--lang", "en", "report", str(tmp_path)]) == 2  # a folder without .storage
    assert ".storage" in capsys.readouterr().err
    (tmp_path / ".storage").mkdir()
    assert main(["--lang", "en", "report", str(tmp_path)]) == 2
    assert "core.entity_registry" in capsys.readouterr().err
    (tmp_path / ".storage" / "core.entity_registry").write_text("{not json")
    assert main(["--lang", "en", "report", str(tmp_path)]) == 2
    assert "Cannot parse" in capsys.readouterr().err


def test_missing_version_asks_for_flag(house_copy, capsys):
    (house_copy / ".HA_VERSION").unlink()
    assert main(["--lang", "en", "report", str(house_copy)]) == 2
    assert "--ha-version" in capsys.readouterr().err
    assert main(["--lang", "en", "report", str(house_copy), "--ha-version", "2026.11.3", "--format", "json"]) == 0


def test_custom_instructions_change_the_count(tmp_path, capsys):
    file = tmp_path / "instructions.txt"
    file.write_text("Be brief.\n" * 200, encoding="utf-8")
    main(["report", str(HOUSE), "--format", "json"])
    base = json.loads(capsys.readouterr().out)["system_prompt_tokens"]
    main(["report", str(HOUSE), "--format", "json", "--instructions", str(file)])
    assert json.loads(capsys.readouterr().out)["system_prompt_tokens"] > base - 30 + 400
