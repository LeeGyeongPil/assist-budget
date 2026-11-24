"""Shared test helpers: fixture paths and a ready-made reconstruction."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from assist_budget.context import reconstruct
from assist_budget.profiles import select_profile
from assist_budget.storage import load_storage

FIXTURES = Path(__file__).parent / "fixtures" / "ha-2026.11.3"
HOUSE = FIXTURES / "house"
DEFAULTS = FIXTURES / "defaults"


def golden(fixture: Path, name: str) -> str:
    """Text of a golden file written by a real Home Assistant 2026.11.3."""
    return (fixture / "golden" / name).read_text(encoding="utf-8")


def golden_json(fixture: Path, name: str):
    return json.loads(golden(fixture, name))


@pytest.fixture
def house() -> Path:
    return HOUSE


@pytest.fixture
def defaults() -> Path:
    return DEFAULTS


@pytest.fixture
def house_copy(tmp_path: Path) -> Path:
    """A throw-away copy of the sample house (for tests that must not touch the original)."""
    target = tmp_path / "house"
    shutil.copytree(HOUSE, target, ignore=shutil.ignore_patterns("golden"))
    return target


@pytest.fixture
def house_rec():
    storage = load_storage(HOUSE)
    profile, _ = select_profile(storage.ha_version)
    return storage, reconstruct(storage, profile)
