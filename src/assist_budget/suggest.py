"""Pick entities to hide from Assist so the prompt fits a token budget, and the plan file.

Rules decide *who may be dropped*; a greedy pass drops the most expensive
candidates first until the prompt fits. The same input always gives the same
plan bytes (no timestamps, fixed ordering).
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .context import Item, Reconstruction, assemble, dump_yaml
from .errors import AssistBudgetError
from .expose import DEFAULT_BINARY_SENSOR_CLASSES, DEFAULT_EXPOSED_DOMAINS, DEFAULT_SENSOR_CLASSES, device_class
from .storage import Storage
from .tokenize import Tokenizer

PLAN_SCHEMA = "assist-budget/plan@1"
REASONS = ("diagnostic", "no_area", "duplicate_name", "long_names",
           "non_default_domain", "non_default_device_class", "manual")
LONG_NAMES_CHARS = 60


@dataclass
class Plan:
    """A reviewed-by-a-human list of exposure changes."""

    ha_version: str
    tokenizer: str
    ctx: int | None
    target: int
    before_tokens: int
    after_tokens: int
    changes: list[dict[str, Any]]
    target_reached: bool = True


def reasons_for(item: Item, storage: Storage, name_counts: dict[str, int]) -> list[str]:
    """Why an exposed entity is a candidate to hide (empty list: keep it)."""
    reasons = []
    entry = storage.entities.get(item.entity_id) or {}
    if entry.get("entity_category") is not None:
        reasons.append("diagnostic")
    if item.areas is None:
        reasons.append("no_area")
    if name_counts[item.names.casefold()] > 1:
        reasons.append("duplicate_name")
    if len(item.names) > LONG_NAMES_CHARS:
        reasons.append("long_names")
    klass = device_class(item.entity_id, storage)
    if item.domain == "sensor":
        if klass not in DEFAULT_SENSOR_CLASSES:
            reasons.append("non_default_device_class")
    elif item.domain == "binary_sensor":
        if klass not in DEFAULT_BINARY_SENSOR_CLASSES:
            reasons.append("non_default_device_class")
    elif item.domain not in DEFAULT_EXPOSED_DOMAINS:
        reasons.append("non_default_domain")
    return reasons


def _matches(entity_id: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(entity_id, pattern) for pattern in patterns)


def make_plan(
    storage: Storage,
    rec: Reconstruction,
    tokenizer: Tokenizer,
    *,
    target: int,
    ctx: int | None = None,
    keep: Sequence[str] = (),
    drop: Sequence[str] = (),
    instructions: str | None = None,
    ha_version: str,
) -> Plan:
    """Choose changes so the system prompt has at most ``target`` tokens (if possible)."""
    count = tokenizer.count
    before = count(rec.system_prompt)
    tokens = {item.entity_id: count(item.fragment) for item in rec.items}
    counts: dict[str, int] = {}
    for item in rec.items:
        counts[item.names.casefold()] = counts.get(item.names.casefold(), 0) + 1

    chosen: dict[str, list[str]] = {}
    for item in rec.items:  # entities the user asked to drop always go first
        if _matches(item.entity_id, drop) and not _matches(item.entity_id, keep):
            chosen[item.entity_id] = ["manual"]
    candidates = []
    for item in rec.items:
        if item.entity_id in chosen or _matches(item.entity_id, keep):
            continue
        reasons = reasons_for(item, storage, counts)
        if reasons:
            candidates.append((item, reasons))
    candidates.sort(key=lambda pair: (-tokens[pair[0].entity_id], pair[0].entity_id))

    def exact_after() -> int:
        kept = [item for item in rec.items if item.entity_id not in chosen]
        return count(assemble(rec.profile, kept, instructions)[1])

    after = exact_after() if chosen else before
    queue = list(candidates)
    while after > target and queue:
        estimate = after
        while estimate > target and queue:  # cheap estimate from entity fragments
            item, reasons = queue.pop(0)
            chosen[item.entity_id] = reasons
            estimate -= tokens[item.entity_id]
        after = exact_after()  # exact recount; loop again if the estimate was too optimistic

    changes = [
        {"entity_id": item.entity_id, "before": True, "after": False,
         "tokens": tokens[item.entity_id], "reasons": chosen[item.entity_id]}
        for item in sorted(rec.items, key=lambda i: (-tokens[i.entity_id], i.entity_id))
        if item.entity_id in chosen
    ]
    return Plan(ha_version, tokenizer.name, ctx, target, before, after, changes, after <= target)


def plan_to_yaml(plan: Plan) -> str:
    """Serialize a plan (stable key order, readable by a human)."""
    document = {
        "schema": PLAN_SCHEMA,
        "ha_version": plan.ha_version,
        "assistant": "conversation",
        "tokenizer": plan.tokenizer,
        "ctx": plan.ctx,
        "target": plan.target,
        "before_tokens": plan.before_tokens,
        "after_tokens": plan.after_tokens,
        "changes": plan.changes,
    }
    return "# assist-budget plan: delete a change to keep that entity exposed.\n" + dump_yaml(document)


def write_plan(plan: Plan, path: Path) -> None:
    """Write the plan file."""
    try:
        path.write_text(plan_to_yaml(plan), encoding="utf-8")
    except OSError as exc:
        raise AssistBudgetError("err_cannot_write", path=str(path), reason=str(exc)) from exc


def load_yaml_document(path: Path, expected_schema: str) -> dict[str, Any]:
    """Read a plan or undo file and check its ``schema`` line."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AssistBudgetError("err_path_not_found", path=str(path)) from exc
    except yaml.YAMLError as exc:
        raise AssistBudgetError("err_bad_file", path=str(path), reason=str(exc).splitlines()[0]) from exc
    if not isinstance(document, dict) or document.get("schema") != expected_schema:
        raise AssistBudgetError("err_wrong_schema", path=str(path), expected=expected_schema)
    return document


def load_plan(path: Path) -> Plan:
    """Read and validate a plan file (exit code 2 with the reason on any problem)."""
    document = load_yaml_document(path, PLAN_SCHEMA)
    changes = document.get("changes")
    if not isinstance(changes, list):
        raise AssistBudgetError("err_bad_file", path=str(path), reason="'changes' must be a list")
    seen: set[str] = set()
    for index, change in enumerate(changes, start=1):
        if (not isinstance(change, dict) or not isinstance(change.get("entity_id"), str)
                or "." not in change["entity_id"]):
            raise AssistBudgetError("err_bad_change", path=str(path), index=index, reason="entity_id")
        if change["entity_id"] in seen:
            raise AssistBudgetError("err_bad_change", path=str(path), index=index, reason="duplicate entity_id")
        seen.add(change["entity_id"])
        if not isinstance(change.get("before"), bool) or not isinstance(change.get("after"), bool):
            raise AssistBudgetError("err_bad_change", path=str(path), index=index, reason="before/after must be true or false")
        if not isinstance(change.get("tokens", 0), int):
            raise AssistBudgetError("err_bad_change", path=str(path), index=index, reason="tokens must be a number")
    return Plan(
        ha_version=str(document.get("ha_version", "")),
        tokenizer=str(document.get("tokenizer", "approx")),
        ctx=document.get("ctx"),
        target=int(document.get("target") or 0),
        before_tokens=int(document.get("before_tokens") or 0),
        after_tokens=int(document.get("after_tokens") or 0),
        changes=changes,
    )
