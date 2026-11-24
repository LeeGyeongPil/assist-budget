"""AC-2 (exposure): the default rules give the same set as Home Assistant."""

from __future__ import annotations

from assist_budget import expose
from assist_budget.storage import load_storage
from conftest import DEFAULTS, HOUSE, golden_json


def test_default_rules_match_ha():
    storage = load_storage(DEFAULTS)
    assert storage.expose_new is True
    truth = golden_json(DEFAULTS, "should_expose.json")  # computed by HA itself for every state
    assert len(truth) == 257
    for entity_id, expected in truth.items():
        assert expose.should_expose(entity_id, storage) is expected, entity_id
    # the fixture really exercises both outcomes
    assert 0 < sum(truth.values()) < len(truth)


def test_explicit_settings_match_ha():
    storage = load_storage(HOUSE)
    assert storage.expose_new is False
    truth = golden_json(HOUSE, "should_expose.json")
    for entity_id, expected in truth.items():
        assert expose.should_expose(entity_id, storage) is expected, entity_id


def test_default_rules_cover_edge_cases():
    storage = load_storage(DEFAULTS)
    assert not expose.should_expose("sensor.uptime_legacy", storage)  # no device class
    assert expose.should_expose("binary_sensor.front_door_legacy", storage)  # door
    assert not expose.should_expose("weather.home", storage)  # domain not in the default list
    assert expose.should_expose("light.porch_lamp_legacy", storage)
    assert not expose.should_expose("sensor.does_not_exist", storage)  # unknown entity: no device class known
    diagnostic = [e for e, entry in storage.entities.items() if entry.get("entity_category")]
    assert diagnostic and not any(expose.should_expose(e, storage) for e in diagnostic)


def test_stored_setting_wins_over_defaults():
    storage = load_storage(DEFAULTS)
    storage.expose_new = True
    storage.legacy_exposed["weather.home"] = {"assistants": {"conversation": {"should_expose": True}}}
    assert expose.should_expose("weather.home", storage)
    storage.legacy_exposed["light.porch_lamp_legacy"] = {"assistants": {"conversation": {"should_expose": False}}}
    assert not expose.should_expose("light.porch_lamp_legacy", storage)
