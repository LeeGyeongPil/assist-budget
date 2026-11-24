"""AC-4: plans meet the target, carry reasons, respect --keep and are deterministic."""

from __future__ import annotations

import fnmatch
import hashlib

import pytest
import yaml

from assist_budget.cli import main
from assist_budget.context import reconstruct
from assist_budget.errors import AssistBudgetError
from assist_budget.suggest import REASONS, load_plan, make_plan, plan_to_yaml
from assist_budget.tokenize import get_tokenizer
from conftest import HOUSE


def plan_for(house_rec, **kwargs):
    storage, rec = house_rec
    options = {"target": 3686, "ctx": 4096, "ha_version": "2026.11.3", **kwargs}
    return make_plan(storage, rec, get_tokenizer("approx"), **options)


def test_plan_meets_target_and_is_deterministic(house_rec, tmp_path, capsys):
    plan = plan_for(house_rec, keep=["light.*"])
    assert plan.after_tokens <= plan.target and plan.target_reached
    assert plan.before_tokens > plan.target
    assert plan.changes
    for change in plan.changes:
        assert change["reasons"] and set(change["reasons"]) <= set(REASONS)
        assert change["before"] is True and change["after"] is False
        assert not fnmatch.fnmatchcase(change["entity_id"], "light.*")  # --keep wins

    # two runs write the same bytes
    first, second = tmp_path / "a.yaml", tmp_path / "b.yaml"
    args = ["--lang", "en", "suggest", str(HOUSE), "--ctx", "4096", "--keep", "light.*"]
    assert main([*args, "--out", str(first)]) == 0
    assert main([*args, "--out", str(second)]) == 0
    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(second.read_bytes()).hexdigest()
    assert "Plan: hide" in capsys.readouterr().out


def test_after_tokens_is_the_real_recount(house_rec):
    storage, rec = house_rec
    plan = plan_for(house_rec)
    dropped = {change["entity_id"] for change in plan.changes}
    again = reconstruct(storage, rec.profile, exclude=dropped)
    assert get_tokenizer("approx").count(again.system_prompt) == plan.after_tokens


def test_plan_is_ordered_by_tokens_and_ids_are_unique(house_rec):
    plan = plan_for(house_rec)
    tokens = [change["tokens"] for change in plan.changes]
    assert tokens == sorted(tokens, reverse=True)
    ids = [change["entity_id"] for change in plan.changes]
    assert len(ids) == len(set(ids))


def test_drop_is_manual_and_keep_beats_drop(house_rec):
    plan = plan_for(house_rec, target=10_000, drop=["sun.*", "button.*"], keep=["button.office_*"])
    reasons = {c["entity_id"]: c["reasons"] for c in plan.changes}
    assert reasons["sun.sun"] == ["manual"]
    assert all(r == ["manual"] for e, r in reasons.items() if e.startswith("button."))
    assert not any(e.startswith("button.office_") for e in reasons)
    assert all(r == ["manual"] for r in reasons.values())  # already under target: nothing else is dropped


def test_already_under_target_gives_empty_plan(house_rec):
    plan = plan_for(house_rec, target=10_000)
    assert plan.changes == [] and plan.after_tokens == plan.before_tokens and plan.target_reached


def test_unreachable_target_is_reported(house_rec, tmp_path, capsys):
    plan = plan_for(house_rec, target=200)
    assert not plan.target_reached and plan.after_tokens > 200
    assert main(["--lang", "en", "suggest", str(HOUSE), "--target", "200", "--out", str(tmp_path / "p.yaml")]) == 0
    assert "cannot be reached" in capsys.readouterr().out


def test_plan_roundtrip_and_stdout_mode(house_rec, tmp_path, capsys):
    plan = plan_for(house_rec)
    path = tmp_path / "plan.yaml"
    path.write_text(plan_to_yaml(plan), encoding="utf-8")
    loaded = load_plan(path)
    assert loaded.changes == plan.changes and loaded.after_tokens == plan.after_tokens
    assert main(["suggest", str(HOUSE), "--ctx", "4096"]) == 0  # no --out: the plan goes to stdout
    document = yaml.safe_load(capsys.readouterr().out)
    assert document["schema"] == "assist-budget/plan@1" and document["assistant"] == "conversation"


@pytest.mark.parametrize(("text", "needle"), [
    ("not: a plan", "plan@1"),
    ("schema: assist-budget/plan@1\nchanges: nope\n", "'changes' must be a list"),
    ("schema: assist-budget/plan@1\nchanges:\n- {entity_id: lightx, before: true, after: false}\n", "entity_id"),
    ("schema: assist-budget/plan@1\nchanges:\n- {entity_id: light.a, before: yes please, after: false}\n", "before/after"),
    ("schema: assist-budget/plan@1\nchanges:\n- {entity_id: light.a, before: true, after: false}\n- {entity_id: light.a, before: true, after: false}\n", "duplicate"),
    (": : :\n\t- bad", "not a valid file"),
])
def test_invalid_plan_files_exit_2(tmp_path, text, needle):
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(AssistBudgetError) as error:
        load_plan(path)
    assert error.value.exit_code == 2 and needle in str(error.value)


def test_suggest_needs_no_target_flag_but_uses_margin(house_rec, tmp_path, capsys):
    out = tmp_path / "p.yaml"
    assert main(["suggest", str(HOUSE), "--ctx", "4096", "--margin", "20", "--out", str(out)]) == 0
    document = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert document["target"] == 3276  # 4096 * 0.8, rounded down
    assert document["after_tokens"] <= 3276
