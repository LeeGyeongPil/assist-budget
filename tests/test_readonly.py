"""AC-6: no command ever modifies the input .storage folder."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from assist_budget.cli import main
from assist_budget.mockha import TOKEN, MockHA
from assist_budget.suggest import make_plan, write_plan
from assist_budget.tokenize import get_tokenizer


def snapshot(root: Path) -> dict[str, tuple[str, int]]:
    """SHA-256 and mtime of every file below ``root``."""
    result = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        result[str(path.relative_to(root))] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    return result


def test_storage_untouched(house_copy, house_rec, tmp_path, monkeypatch):
    # make the files old and read-only, so any write attempt would fail loudly or change the mtime
    for path in house_copy.rglob("*"):
        if path.is_file():
            os.utime(path, (1_700_000_000, 1_700_000_000))
            path.chmod(0o444)
    before = snapshot(house_copy)
    assert len(before) >= 6  # five .storage files and .HA_VERSION

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    plan_file = out_dir / "trim.yaml"
    commands = [
        ["report", str(house_copy), "--ctx", "4096"],
        ["report", str(house_copy), "--format", "json"],
        ["report", str(house_copy), "--format", "md", "--fail-over"],
        ["report", str(house_copy / ".storage")],
        ["suggest", str(house_copy), "--ctx", "4096", "--out", str(plan_file)],
        ["suggest", str(house_copy), "--ctx", "4096"],
        ["demo", "--ctx", "4096"],
    ]
    for argv in commands:
        main(["--lang", "en", *argv])
        assert snapshot(house_copy) == before, argv

    storage, rec = house_rec
    plan = make_plan(storage, rec, get_tokenizer("approx"), target=3686, ha_version="2026.11.3")
    write_plan(plan, plan_file)
    with MockHA({c["entity_id"] for c in plan.changes}) as ha:
        monkeypatch.setenv("HA_TOKEN", TOKEN)
        assert main(["apply", str(plan_file), "--url", ha.url, "--yes", "--undo-dir", str(out_dir)]) == 0
        (undo_file,) = out_dir.glob("undo-*.yaml")
        assert main(["undo", str(undo_file), "--url", ha.url, "--yes"]) == 0
    assert snapshot(house_copy) == before


def test_source_never_opens_files_for_writing_in_storage_module():
    import assist_budget.storage as storage_module

    source = Path(storage_module.__file__).read_text(encoding="utf-8")
    assert "write_text" not in source and "'w'" not in source and '"w"' not in source
