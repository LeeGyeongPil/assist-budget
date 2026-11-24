"""AC-8: the mock-mode demo runs offline, is honest about being a mock, and really restores."""

from __future__ import annotations

import hashlib
import socket
import time
from pathlib import Path

import pytest

import assist_budget
from assist_budget.cli import main
from conftest import HOUSE


def run(argv, capsys):
    started = time.monotonic()
    code = main(argv)
    return code, capsys.readouterr().out, time.monotonic() - started


def test_demo_offline(capsys, monkeypatch):
    # no real network: any attempt to connect outside the loopback interface fails the test
    real_connect = socket.socket.connect

    def loopback_only(self, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"demo tried to reach {address}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    code, out, seconds = run(["--lang", "en", "demo", "--ctx", "4096"], capsys)
    assert code == 0
    assert seconds < 10
    assert out.splitlines()[0].startswith("MOCK practice run")  # the very first line says it is a mock
    for word in ("MOCK", "over", "fits", "restored"):
        assert word in out
    assert out.index("over") < out.index("fits") < out.index("restored")
    assert "write commands the fake server received: 0" in out  # dry run sent nothing


def test_demo_numbers_come_from_a_real_reconstruction(capsys):
    _, out, _ = run(["--lang", "en", "demo", "--ctx", "4096"], capsys)
    # the figures printed are the real ones for the bundled house, not canned text
    assert "207 exposed entities, system prompt 4,840 tokens = 118.2% of the window -> over" in out
    assert "restored: the fake Home Assistant exposes exactly the same" in out


def test_demo_with_a_roomy_window_has_nothing_to_trim(capsys):
    code, out, _ = run(["--lang", "en", "demo", "--ctx", "8192"], capsys)
    assert code == 0 and "Nothing to trim" in out
    assert "-> fits" in out and "-> over" not in out


def test_demo_korean_keeps_the_mock_notice(capsys):
    code, out, _ = run(["--lang", "ko", "demo", "--ctx", "4096"], capsys)
    assert code == 0 and out.splitlines()[0].startswith("MOCK 연습 실행") and "복구 완료" in out


def test_bundled_house_equals_the_test_fixture():
    """The sample house shipped inside the package is the one written by Home Assistant."""
    bundled = Path(assist_budget.__file__).parent / "data" / "house"
    for name in (".HA_VERSION", ".storage/core.entity_registry", ".storage/core.device_registry",
                 ".storage/core.area_registry", ".storage/core.restore_state",
                 ".storage/homeassistant.exposed_entities"):
        assert hashlib.sha256((bundled / name).read_bytes()).digest() == \
            hashlib.sha256((HOUSE / name).read_bytes()).digest(), name


def test_demo_leaves_no_files_behind(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    run(["demo", "--ctx", "4096"], capsys)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("ctx", ["0", "-5", "abc"])
def test_demo_rejects_bad_ctx(ctx, capsys):
    assert main(["demo", "--ctx", ctx]) == 2
