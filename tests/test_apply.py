"""AC-5: apply/undo against the in-process fake Home Assistant.

``MockHA.received`` records every message, so the tests can prove what was
(and was not) sent.
"""

from __future__ import annotations

import yaml
import pytest

from assist_budget import EXIT_CONFLICT, EXIT_CONNECTION, EXIT_OK
from assist_budget.apply import run_apply, run_undo
from assist_budget.cli import main
from assist_budget.errors import AssistBudgetError
from assist_budget.expose import should_expose
from assist_budget.ha_ws import HAClient
from assist_budget.mockha import TOKEN, MockHA
from assist_budget.suggest import make_plan, write_plan
from assist_budget.tokenize import get_tokenizer


@pytest.fixture
def scenario(house_rec, tmp_path):
    """A plan for the sample house plus a fake HA that exposes what the storage says."""
    storage, rec = house_rec
    plan = make_plan(storage, rec, get_tokenizer("approx"), target=3686, ctx=4096, ha_version="2026.11.3")
    exposed = {eid for eid in [*storage.entities, *storage.legacy_exposed] if should_expose(eid, storage)}
    with MockHA(exposed) as ha:
        yield plan, ha, exposed, tmp_path


def apply(plan, ha, tmp_path, **kwargs):
    lines: list[str] = []
    with HAClient(ha.url, TOKEN) as client:
        code = run_apply(plan, client, url=ha.url, lang="en", out=lines.append, undo_dir=tmp_path, **kwargs)
    return code, "\n".join(lines)


def test_dry_run_sends_no_writes(scenario):
    plan, ha, exposed, tmp_path = scenario
    code, text = apply(plan, ha, tmp_path)
    assert code == EXIT_OK and "DRY RUN" in text and "Nothing was sent" in text
    assert ha.write_commands == []  # not one expose_entity message reached the server
    assert {m["type"] for m in ha.received} == {"get_config", "homeassistant/expose_entity/list"}
    assert ha.exposed == exposed
    assert list(tmp_path.glob("undo-*.yaml")) == []  # a dry run leaves no files behind


def test_apply_then_undo_restores(scenario, monkeypatch):
    plan, ha, exposed, tmp_path = scenario
    dropped = {c["entity_id"] for c in plan.changes}
    seen_before_write: list[bool] = []
    original = HAClient.set_exposed

    def spy(self, entity_ids, should_expose):
        seen_before_write.append(bool(list(tmp_path.glob("undo-*.yaml"))))  # undo file must already exist
        return original(self, entity_ids, should_expose)

    monkeypatch.setattr(HAClient, "set_exposed", spy)
    code, text = apply(plan, ha, tmp_path, yes=True)
    assert code == EXIT_OK and "Applied" in text
    assert seen_before_write and all(seen_before_write)
    assert ha.exposed == exposed - dropped
    assert len(ha.write_commands) == 1
    assert ha.write_commands[0]["should_expose"] is False and set(ha.write_commands[0]["entity_ids"]) == dropped

    (undo_file,) = tmp_path.glob("undo-*.yaml")
    document = yaml.safe_load(undo_file.read_text(encoding="utf-8"))
    assert document["schema"] == "assist-budget/undo@1" and document["ha_version"] == "2026.11.3"
    assert TOKEN not in undo_file.read_text(encoding="utf-8")  # the token never reaches a file
    assert {e["entity_id"] for e in document["entities"]} == dropped
    assert all(e["should_expose"] is True for e in document["entities"])

    lines: list[str] = []
    with HAClient(ha.url, TOKEN) as client:
        assert run_undo(undo_file, client, lang="en", out=lines.append, yes=True) == EXIT_OK
    assert ha.exposed == exposed  # exactly the state from before the apply
    assert "Restored" in "\n".join(lines)


def test_undo_dry_run_changes_nothing(scenario):
    plan, ha, exposed, tmp_path = scenario
    apply(plan, ha, tmp_path, yes=True)
    (undo_file,) = tmp_path.glob("undo-*.yaml")
    after_apply = set(ha.exposed)
    writes = len(ha.write_commands)
    with HAClient(ha.url, TOKEN) as client:
        assert run_undo(undo_file, client, lang="en", out=lambda _: None) == EXIT_OK
    assert ha.exposed == after_apply and len(ha.write_commands) == writes


def test_conflict_aborts_exit5(scenario):
    plan, ha, exposed, tmp_path = scenario
    ha.exposed.discard(plan.changes[0]["entity_id"])  # someone hid it after the plan was made
    code, text = apply(plan, ha, tmp_path, yes=True)
    assert code == EXIT_CONFLICT and "nothing was sent" in text
    assert ha.write_commands == [] and list(tmp_path.glob("undo-*.yaml")) == []

    code, text = apply(plan, ha, tmp_path, yes=True, force=True)  # --force goes ahead, and says so
    assert code == EXIT_OK and "--force" in text
    assert len(ha.write_commands) == 1


@pytest.mark.parametrize("version", ["2024.5.4", "2026.12.0", "2027.1.1", ""])
def test_unsupported_version_aborts_exit4(house_rec, tmp_path, version):
    storage, rec = house_rec
    plan = make_plan(storage, rec, get_tokenizer("approx"), target=3686, ha_version="2026.11.3")
    with MockHA({c["entity_id"] for c in plan.changes}, version=version) as ha:
        with pytest.raises(AssistBudgetError) as error:
            apply(plan, ha, tmp_path, yes=True)
        assert error.value.exit_code == EXIT_CONNECTION
        assert "nothing was sent" in str(error.value)
        assert ha.write_commands == []
        assert list(tmp_path.glob("undo-*.yaml")) == []


def test_supported_range_edges_are_accepted(house_rec, tmp_path):
    storage, rec = house_rec
    plan = make_plan(storage, rec, get_tokenizer("approx"), target=3686, ha_version="2026.11.3")
    for version in ("2024.6.0", "2026.11.9"):
        with MockHA({c["entity_id"] for c in plan.changes}, version=version) as ha:
            code, _ = apply(plan, ha, tmp_path)
            assert code == EXIT_OK


def test_wrong_token_exit4_and_no_traffic():
    with MockHA([]) as ha:
        with pytest.raises(AssistBudgetError) as error:
            HAClient(ha.url, "wrong").__enter__()
        assert error.value.exit_code == EXIT_CONNECTION and "rejected the access token" in str(error.value)
        assert ha.received == []


def test_unreachable_server_exit4():
    with pytest.raises(AssistBudgetError) as error:
        HAClient("ws://127.0.0.1:9/api/websocket", "x").__enter__()
    assert error.value.exit_code == EXIT_CONNECTION and "Cannot connect" in str(error.value)


def test_cli_end_to_end(scenario, monkeypatch, capsys):
    plan, ha, exposed, tmp_path = scenario
    plan_file = tmp_path / "trim.yaml"
    write_plan(plan, plan_file)
    monkeypatch.setenv("HA_TOKEN", TOKEN)
    base = ["--lang", "en", "apply", str(plan_file), "--url", ha.url, "--undo-dir", str(tmp_path)]
    assert main(base) == 0 and ha.write_commands == []
    assert main([*base, "--yes"]) == 0
    assert ha.exposed == exposed - {c["entity_id"] for c in plan.changes}
    (undo_file,) = tmp_path.glob("undo-*.yaml")
    assert main(["--lang", "en", "undo", str(undo_file), "--url", ha.url]) == 0  # dry run
    assert ha.exposed != exposed
    assert main(["--lang", "en", "undo", str(undo_file), "--url", ha.url, "--yes"]) == 0
    assert ha.exposed == exposed
    assert "Restored" in capsys.readouterr().out


def test_cli_input_errors(tmp_path, monkeypatch, capsys):
    plan_file = tmp_path / "p.yaml"
    plan_file.write_text("schema: assist-budget/plan@1\nchanges: []\n", encoding="utf-8")
    monkeypatch.delenv("HA_TOKEN", raising=False)
    assert main(["--lang", "en", "apply", str(plan_file)]) == 2  # no token
    assert "HA_TOKEN" in capsys.readouterr().err
    monkeypatch.setenv("HA_TOKEN", "x")
    assert main(["--lang", "en", "apply", str(plan_file), "--url", "http://homeassistant.local:8123"]) == 2
    assert "WebSocket URL" in capsys.readouterr().err
    assert main(["--lang", "en", "apply", str(tmp_path / "missing.yaml")]) == 2
    assert main(["--lang", "en", "undo", str(plan_file), "--url", "ws://127.0.0.1:9/x"]) == 2  # a plan is not an undo file
    assert "assist-budget/undo@1" in capsys.readouterr().err
    assert main(["--lang", "en", "apply", str(plan_file), "--url", "ws://127.0.0.1:9/x"]) == EXIT_CONNECTION


def test_server_is_cleaned_up():
    with MockHA([]) as ha:
        url = ha.url
    with pytest.raises(AssistBudgetError):  # the port is closed after the with-block
        HAClient(url, TOKEN).__enter__()
