"""Token breakdown, verdict and the table / JSON / Markdown output."""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from typing import Any

from .context import Reconstruction
from .i18n import translate
from .storage import Warn
from .tokenize import Tokenizer

NO_AREA = ""  # key used in the data for entities without an area; shown translated


def verdict_for(used: int, ctx: int, margin_pct: float) -> str:
    """``over`` when the prompt does not fit, ``tight`` inside the safety margin, else ``fits``."""
    if used > ctx:
        return "over"
    if used > ctx * (1 - margin_pct / 100):
        return "tight"
    return "fits"


def budget_target(ctx: int, margin_pct: float, reserve: int) -> int:
    """Largest system prompt that still leaves the safety margin and the reserve."""
    return int(ctx * (1 - margin_pct / 100)) - reserve


def build_report(
    rec: Reconstruction,
    tokenizer: Tokenizer,
    *,
    ha_version: str,
    ctx: int,
    reserve: int = 0,
    margin_pct: float = 10.0,
    top: int = 10,
) -> dict[str, Any]:
    """Count tokens and group them by domain, area and entity."""
    count = tokenizer.count
    system_tokens = count(rec.system_prompt)
    static_tokens = count(rec.static_yaml) if rec.static_yaml else 0
    per_entity = [(item, count(item.fragment)) for item in rec.items]

    by_domain: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_area: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for item, tokens in per_entity:
        for table, key in ((by_domain, item.domain), (by_area, item.area or NO_AREA)):
            table[key][0] += 1
            table[key][1] += tokens

    def rows(table: dict[str, list[int]]) -> list[dict[str, Any]]:
        ordered = sorted(table.items(), key=lambda pair: (-pair[1][1], pair[0]))
        return [{"name": name, "entities": values[0], "tokens": values[1]} for name, values in ordered]

    used = system_tokens + reserve
    entities = sorted(per_entity, key=lambda pair: (-pair[1], pair[0].entity_id))
    return {
        "ha_version": ha_version,
        "profile": rec.profile.name,
        "verified_profile": rec.profile.verified,
        "tokenizer": tokenizer.name,
        "estimate": "upper",  # offline: entities that HA does not load right now are still counted
        "ctx": ctx,
        "reserve": reserve,
        "margin_pct": margin_pct,
        "exposed": len(rec.items),
        "system_prompt_tokens": system_tokens,
        "static_context_tokens": static_tokens,
        "used_tokens": used,
        "usage_pct": round(100 * used / ctx, 1) if ctx else 0.0,
        "headroom_tokens": ctx - used,
        "verdict": verdict_for(used, ctx, margin_pct),
        "target_tokens": budget_target(ctx, margin_pct, reserve),
        "by_domain": rows(by_domain),
        "by_area": rows(by_area),
        "top_entities": [{"entity_id": item.entity_id, "tokens": tokens} for item, tokens in entities[:top]],
        "entities": [{"entity_id": item.entity_id, "domain": item.domain, "area": item.area, "tokens": tokens}
                     for item, tokens in entities],
        "warnings": [{"key": key, "params": params} for key, params in rec.warnings],
    }


def verdict_label(lang: str, verdict: str) -> str:
    """The verdict word; Korean keeps the English word in parentheses for searching."""
    return translate(lang, f"verdict_{verdict}")


def _cells(text: str) -> int:
    """Terminal width of ``text``: wide (Hangul, CJK) characters take two cells."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _ljust(text: str, width: int) -> str:
    return text + " " * (width - _cells(text))


def _rjust(text: str, width: int) -> str:
    return " " * (width - _cells(text)) + text


def _bar(pct: float, width: int = 30) -> str:
    filled = min(width, round(width * pct / 100))
    return "#" * filled + "." * (width - filled)


def render_warnings(lang: str, warnings: list[Warn]) -> list[str]:
    """Translate warnings into one line each."""
    return [translate(lang, key, **params) for key, params in warnings]


def render(report: dict[str, Any], lang: str, fmt: str, extra_warnings: list[Warn] | None = None) -> str:
    """Format the report as ``table``, ``md`` or ``json``."""
    if fmt == "json":
        return json.dumps(report, indent=2, ensure_ascii=False)
    markdown = fmt == "md"
    t = lambda key, **kw: translate(lang, key, **kw)  # noqa: E731
    lines: list[str] = []
    verdict = verdict_label(lang, report["verdict"])
    title = t("report_title")
    lines.append(f"## {title}" if markdown else title)
    lines.append("")
    facts = [
        (t("report_ha_version"), f"{report['ha_version']}  ({report['profile']})"),
        (t("report_tokenizer"), report["tokenizer"]),
        (t("report_exposed"), f"{report['exposed']}  ({t('report_upper_estimate')})"),
        (t("report_prompt_tokens"), f"{report['system_prompt_tokens']:,}"),
        (t("report_static_tokens"), f"{report['static_context_tokens']:,}"),
    ]
    if report["reserve"]:
        facts.append((t("report_reserve"), f"{report['reserve']:,}"))
    facts += [
        (t("report_usage"), f"{report['used_tokens']:,} / {report['ctx']:,} = {report['usage_pct']}%"),
        (t("report_bar"), f"[{_bar(report['usage_pct'])}]"),
        (t("report_verdict"), f"{verdict}  ({t('report_margin', pct=report['margin_pct'])})"),
    ]
    width = max(_cells(label) for label, _ in facts)
    for label, value in facts:
        lines.append(f"- **{label}**: {value}" if markdown else f"{_ljust(label, width)}  {value}")
    if report["verdict"] != "fits":
        lines.append("")
        lines.append(t("report_hint_trim", target=report["target_tokens"]))
    for heading_key, rows_key in (("report_by_domain", "by_domain"), ("report_by_area", "by_area")):
        lines += ["", f"### {t(heading_key)}" if markdown else t(heading_key)]
        lines += _table([(t("col_name"), t("col_entities"), t("col_tokens"))] + [
            (t("no_area") if row["name"] == NO_AREA else row["name"], str(row["entities"]), f"{row['tokens']:,}")
            for row in report[rows_key][:10]
        ], markdown)
    lines += ["", f"### {t('report_top_entities')}" if markdown else t("report_top_entities")]
    lines += _table([(t("col_entity"), t("col_tokens"))] + [
        (row["entity_id"], f"{row['tokens']:,}") for row in report["top_entities"]
    ], markdown)
    all_warnings = render_warnings(lang, [(w["key"], w["params"]) for w in report["warnings"]]
                                   + (extra_warnings or []))
    all_warnings.append(t("warn_not_counted"))
    lines.append("")
    for text in all_warnings:
        lines.append(f"> {t('warn_prefix')}: {text}" if markdown else f"{t('warn_prefix')}: {text}")
    return "\n".join(lines)


def _table(rows: list[tuple[str, ...]], markdown: bool) -> list[str]:
    if markdown:
        head, body = rows[0], rows[1:]
        out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
        out += ["| " + " | ".join(row) + " |" for row in body]
        return out
    widths = [max(_cells(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    for index, row in enumerate(rows):
        cells = [_ljust(row[0], widths[0])] + [_rjust(cell, widths[i]) for i, cell in enumerate(row) if i]
        out.append("  " + "  ".join(cells))
        if index == 0:
            out.append("  " + "  ".join("-" * w for w in widths))
    return out
