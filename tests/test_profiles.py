"""AC-10: version routing, unverified-profile warnings and the unsupported-version exit code."""

from __future__ import annotations

import pytest

from assist_budget import EXIT_UNSUPPORTED
from assist_budget.cli import main
from assist_budget.errors import AssistBudgetError
from assist_budget.profiles import parse_version, select_profile
from conftest import HOUSE


def test_version_routing():
    with pytest.raises(AssistBudgetError) as old:
        select_profile("2025.4.4")
    assert old.value.exit_code == EXIT_UNSUPPORTED

    for version in ("2025.5.0", "2025.12.1", "2026.7.3"):
        profile, warnings = select_profile(version)
        assert profile.name == "2025.5-2026.7" and profile.legacy_layout and not profile.verified
        assert [key for key, _ in warnings] == ["warn_unverified_profile"]

    for version in ("2026.8.0", "2026.10.2"):
        profile, warnings = select_profile(version)
        assert profile.name == "2026.8-2026.10" and not profile.verified
        assert [key for key, _ in warnings] == ["warn_unverified_profile"]

    profile, warnings = select_profile("2026.11.3")
    assert profile.verified and warnings == []

    profile, warnings = select_profile("2027.2.0b1")  # unknown future: closest profile + warning
    assert profile.name == "2026.11"
    assert [key for key, _ in warnings] == ["warn_newer_version"]


def test_parse_version_accepts_betas_and_rejects_text():
    assert parse_version("2026.12.0b3") == (2026, 12)
    assert parse_version("2026.1") == (2026, 1)
    with pytest.raises(AssistBudgetError):
        parse_version("latest")


def test_old_version_exits_3_with_guidance(capsys):
    code = main(["--lang", "en", "report", str(HOUSE), "--ha-version", "2025.3.0"])
    assert code == EXIT_UNSUPPORTED
    assert "2025.5" in capsys.readouterr().err


def test_unverified_profile_warning_is_printed_with_the_result(capsys):
    code = main(["--lang", "en", "report", str(HOUSE), "--ha-version", "2026.6.0"])
    captured = capsys.readouterr()
    assert code == 0
    assert "unverified profile" in captured.out  # the result is still shown
    assert "Exposed entities" in captured.out


def test_legacy_profile_orders_the_prompt_like_the_old_assist_api(house_rec):
    from assist_budget.context import reconstruct

    storage, _ = house_rec
    profile, _ = select_profile("2026.6.0")
    prompt = reconstruct(storage, profile).system_prompt
    assert prompt.index("When controlling Home Assistant") < prompt.index("Static Context")
    assert "Use HassTurnOn" in prompt  # the old text had no intent__ prefix
