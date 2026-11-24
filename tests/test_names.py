"""AC-2 (names): entity names and aliases match Home Assistant, even without core.restore_state."""

from __future__ import annotations

import json

from assist_budget import names
from assist_budget.context import reconstruct
from assist_budget.profiles import select_profile
from assist_budget.storage import load_storage
from conftest import HOUSE, golden


def test_aliases_match_ha_for_every_registry_entity():
    storage = load_storage(HOUSE)
    expected = json.loads(golden(HOUSE, "names.json"))
    assert len(expected) == len(storage.entities) == 251
    for entity_id, entry in storage.entities.items():
        assert names.entity_aliases(entry, storage) == expected[entity_id], entity_id


def test_names_without_restore_state(house_copy):
    (house_copy / ".storage" / "core.restore_state").unlink()
    storage = load_storage(house_copy)
    profile, _ = select_profile(storage.ha_version)
    rec = reconstruct(storage, profile)
    truth = json.loads(golden(HOUSE, "entities.json"))

    # only the entity that is outside the registry (sun.sun) is lost, and the user is told
    assert [item.entity_id for item in rec.items] == [e for e in truth if e != "sun.sun"]
    assert ("warn_entity_skipped_no_name", {"entity_id": "sun.sun"}) in rec.warnings
    assert ("warn_no_restore_state", {}) in storage.warnings
    for item in rec.items:  # names and aliases are identical to the ones Home Assistant computed
        assert item.names == truth[item.entity_id]["names"]
        assert item.areas == truth[item.entity_id].get("areas")


def test_computed_name_uses_device_name_unless_entity_has_own_area():
    storage = load_storage(HOUSE)
    entry = dict(next(iter(storage.entities.values())))
    device = storage.devices[entry["device_id"]]
    assert names.full_entity_name(entry, storage) == f"{device['name']} {entry['original_name']}"
    entry["area_id"] = "garage"  # an entity with its own area drops the device part
    assert names.full_entity_name(entry, storage) == entry["original_name"]


def test_user_device_name_wins_and_prefix_is_stripped():
    storage = load_storage(HOUSE)
    entry = dict(next(iter(storage.entities.values())))
    device = storage.devices[entry["device_id"]]
    device["name_by_user"] = "Reading Lamp"
    assert names.full_entity_name(entry, storage).startswith("Reading Lamp ")
    legacy = {"original_name": "Reading Lamp Brightness", "has_entity_name": False, "device_id": entry["device_id"]}
    assert names.full_entity_name(legacy, storage) == "Reading Lamp Brightness"
