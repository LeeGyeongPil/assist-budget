"""AC-1: the rebuilt prompt is byte-identical to what a real Home Assistant 2026.11.3 builds."""

from __future__ import annotations

import hashlib
import json

from conftest import HOUSE, golden


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_matches_ha_2026_11_3_golden(house_rec):
    _, rec = house_rec
    assert sha(rec.static_yaml) == sha(golden(HOUSE, "static_context.yaml"))
    assert rec.static_yaml == golden(HOUSE, "static_context.yaml")
    assert sha(rec.system_prompt) == sha(golden(HOUSE, "system_prompt.txt"))
    assert rec.system_prompt == golden(HOUSE, "system_prompt.txt")


def test_golden_contains_non_ascii_alias(house_rec):
    _, rec = house_rec
    assert "거실" in rec.static_yaml  # a Korean area alias survives the YAML dump unescaped


def test_item_order_and_fields_match_golden(house_rec):
    _, rec = house_rec
    expected = json.loads(golden(HOUSE, "entities.json"))
    assert [item.entity_id for item in rec.items] == list(expected)
    for item in rec.items:
        assert item.names == expected[item.entity_id]["names"]
        assert item.areas == expected[item.entity_id].get("areas")


def test_fragments_concatenate_to_static_yaml(house_rec):
    _, rec = house_rec
    assert "".join(item.fragment for item in rec.items) == rec.static_yaml
