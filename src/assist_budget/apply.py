"""Apply a plan to a running Home Assistant, and undo it.

Safety rules, in order:

1. Read-only first: connect, read the HA version and the current exposure.
2. Refuse to write on an HA version outside the range where the WebSocket
   commands were verified (exit code 4).
3. Refuse if exposure changed since the plan was made (exit code 5), unless ``force``.
4. Dry-run unless ``yes``: nothing is written to HA.
5. With ``yes``: write the undo file *first*, then send the change, then read
   the exposure again and check the result.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from . import EXIT_CONFLICT, EXIT_CONNECTION, EXIT_OK
from .context import dump_yaml
from .errors import AssistBudgetError
from .ha_ws import HAClient
from .i18n import translate
from .profiles import parse_version
from .suggest import Plan, load_yaml_document

UNDO_SCHEMA = "assist-budget/undo@1"
WRITE_RANGE = ((2024, 6), (2026, 11))  # versions whose source contains the expose_entity command
CHUNK = 100  # entity ids per command

Emit = Callable[[str], None]


def check_write_version(version: str) -> None:
    """Raise exit code 4 unless ``version`` is inside the verified range."""
    low, high = WRITE_RANGE
    try:
        parsed = parse_version(version)
    except AssistBudgetError:
        parsed = None
    if parsed is None or not (low <= parsed <= high):
        raise AssistBudgetError("err_write_version", EXIT_CONNECTION, version=version or "?",
                                low=f"{low[0]}.{low[1]}", high=f"{high[0]}.{high[1]}")


def _undo_path(directory: Path, now: datetime) -> Path:
    return directory / f"undo-{now.strftime('%Y%m%dT%H%M%S')}.yaml"


def write_undo(path: Path, ha_version: str, url: str, entries: list[tuple[str, bool]], now: datetime) -> None:
    """Write the file that restores the previous exposure (never contains the token)."""
    document: dict[str, Any] = {
        "schema": UNDO_SCHEMA,
        "ha_version": ha_version,
        "applied_at": now.isoformat(timespec="seconds"),
        "url": url,
        "entities": [{"entity_id": eid, "should_expose": value} for eid, value in entries],
    }
    try:
        path.write_text("# assist-budget undo file: run `assist-budget undo` with it.\n" + dump_yaml(document),
                        encoding="utf-8")
    except OSError as exc:
        raise AssistBudgetError("err_cannot_write", path=str(path), reason=str(exc)) from exc


def load_undo(path: Path) -> list[tuple[str, bool]]:
    """Read and validate an undo file; returns ``(entity_id, should_expose)`` pairs."""
    document = load_yaml_document(path, UNDO_SCHEMA)
    entries = document.get("entities")
    if not isinstance(entries, list) or not all(
        isinstance(e, dict) and isinstance(e.get("entity_id"), str) and isinstance(e.get("should_expose"), bool)
        for e in entries
    ):
        raise AssistBudgetError("err_bad_file", path=str(path), reason="'entities' needs entity_id and should_expose")
    return [(e["entity_id"], e["should_expose"]) for e in entries]


def _send(client: HAClient, changes: list[tuple[str, bool]]) -> None:
    """Send changes grouped by target value, in chunks."""
    for target in (False, True):
        ids = [eid for eid, value in changes if value is target]
        for start in range(0, len(ids), CHUNK):
            client.set_exposed(ids[start:start + CHUNK], target)


def run_apply(
    plan: Plan,
    client: HAClient,
    *,
    url: str,
    lang: str,
    out: Emit,
    yes: bool = False,
    force: bool = False,
    undo_dir: Path = Path("."),
    list_limit: int = 20,
    now: Callable[[], datetime] = datetime.now,
) -> int:
    """Dry-run (default) or apply ``plan`` through an open ``client``; returns the exit code."""
    t = lambda key, **kw: translate(lang, key, **kw)  # noqa: E731
    version = client.get_version()
    check_write_version(version)
    if plan.ha_version and plan.ha_version != version:
        out(t("apply_version_differs", plan=plan.ha_version, live=version))
    live = client.exposed_entities()
    wanted = [(c["entity_id"], bool(c["after"])) for c in plan.changes]

    conflicts = [c["entity_id"] for c in plan.changes if live.get(c["entity_id"], False) != bool(c["before"])]
    out(t("apply_header_dry" if not yes else "apply_header_yes", count=len(wanted), version=version))
    for change in plan.changes[:list_limit]:
        out(t("apply_change_hide" if not change["after"] else "apply_change_show", entity=change["entity_id"],
              tokens=change.get("tokens", 0), reasons=", ".join(change.get("reasons", []))))
    if len(plan.changes) > list_limit:
        out(t("apply_more", count=len(plan.changes) - list_limit))
    out(t("apply_estimate", before=f"{plan.before_tokens:,}", after=f"{plan.after_tokens:,}",
          saved=f"{plan.before_tokens - plan.after_tokens:,}", tokenizer=plan.tokenizer))

    if conflicts and not force:
        out(t("apply_conflict", count=len(conflicts), sample=", ".join(conflicts[:5])))
        return EXIT_CONFLICT
    if conflicts:
        out(t("apply_conflict_forced", count=len(conflicts)))
    if not yes:
        out(t("apply_dry_run_done"))
        return EXIT_OK

    stamp = now()
    undo_file = _undo_path(undo_dir, stamp)
    write_undo(undo_file, version, url, [(eid, live.get(eid, False)) for eid, _ in wanted], stamp)  # before any write
    out(t("apply_undo_written", path=str(undo_file)))
    _send(client, wanted)
    after = client.exposed_entities()
    wrong = [eid for eid, value in wanted if after.get(eid, False) != value]
    if wrong:
        out(t("apply_verify_failed", count=len(wrong), sample=", ".join(wrong[:5]), path=str(undo_file)))
        return EXIT_CONNECTION
    out(t("apply_done", count=len(wanted), path=str(undo_file)))
    return EXIT_OK


def run_undo(
    undo_path: Path,
    client: HAClient,
    *,
    lang: str,
    out: Emit,
    yes: bool = False,
) -> int:
    """Restore the exposure saved in an undo file (dry-run unless ``yes``)."""
    t = lambda key, **kw: translate(lang, key, **kw)  # noqa: E731
    wanted = load_undo(undo_path)
    version = client.get_version()
    check_write_version(version)
    live = client.exposed_entities()
    todo = [(eid, value) for eid, value in wanted if live.get(eid, False) != value]
    out(t("undo_header_yes" if yes else "undo_header_dry", count=len(todo), total=len(wanted)))
    if not yes:
        out(t("apply_dry_run_done"))
        return EXIT_OK
    _send(client, todo)
    after = client.exposed_entities()
    wrong = [eid for eid, value in wanted if after.get(eid, False) != value]
    if wrong:
        out(t("undo_verify_failed", count=len(wrong), sample=", ".join(wrong[:5])))
        return EXIT_CONNECTION
    out(t("undo_done", count=len(todo)))
    return EXIT_OK
