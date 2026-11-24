"""``assist-budget demo``: the whole flow without Home Assistant, a token or a network.

Real: the sample house (``.storage`` files written by Home Assistant 2026.11.3),
the prompt reconstruction, the token counts, the plan, the undo file.
Fake: only the Home Assistant server on the other end of the WebSocket
(``mockha.MockHA``, running inside this process).
"""

from __future__ import annotations

import tempfile
from importlib import resources
from pathlib import Path

from .apply import Emit, run_apply, run_undo
from .context import reconstruct
from .expose import should_expose
from .ha_ws import HAClient
from .i18n import translate
from .mockha import TOKEN, MockHA
from .profiles import select_profile
from .report import budget_target, build_report, verdict_label
from .storage import load_storage
from .suggest import make_plan, write_plan, load_plan
from .tokenize import get_tokenizer

DEFAULT_CTX = 4096


def house_path() -> Path:
    """Folder of the bundled sample house."""
    return Path(str(resources.files("assist_budget").joinpath("data", "house")))


def run_demo(ctx: int, lang: str, out: Emit, margin_pct: float = 10.0) -> int:
    """Run report -> suggest -> dry-run -> apply -> undo against the fake HA; returns the exit code."""
    t = lambda key, **kw: translate(lang, key, **kw)  # noqa: E731
    out(t("demo_banner"))
    storage = load_storage(house_path())
    version = storage.ha_version or "2026.11.3"
    profile, _ = select_profile(version)
    tokenizer = get_tokenizer("approx")

    # 1. measure
    rec = reconstruct(storage, profile)
    before = build_report(rec, tokenizer, ha_version=version, ctx=ctx, margin_pct=margin_pct)
    out("")
    out(t("demo_step_report", ctx=f"{ctx:,}"))
    out(t("demo_report_line", exposed=before["exposed"], tokens=f"{before['system_prompt_tokens']:,}",
          pct=before["usage_pct"], verdict=verdict_label(lang, before["verdict"])))
    top_domain = before["by_domain"][0]
    out(t("demo_report_top", domain=top_domain["name"], tokens=f"{top_domain['tokens']:,}"))

    # 2. plan
    target = budget_target(ctx, margin_pct, 0)
    plan = make_plan(storage, rec, tokenizer, target=target, ctx=ctx, ha_version=version)
    out("")
    out(t("demo_step_plan", target=f"{target:,}"))
    out(t("demo_plan_line", count=len(plan.changes), before=f"{plan.before_tokens:,}", after=f"{plan.after_tokens:,}"))
    if not plan.changes:
        out(t("demo_nothing_to_trim"))
        return 0

    initially_exposed = {eid for eid in [*storage.entities, *storage.legacy_exposed] if should_expose(eid, storage)}
    with tempfile.TemporaryDirectory(prefix="assist-budget-demo-") as tmp, MockHA(initially_exposed, version) as ha:
        plan_file = Path(tmp) / "trim.yaml"
        write_plan(plan, plan_file)
        loaded = load_plan(plan_file)

        # 3. dry run: HA is read, never written
        out("")
        out(t("demo_step_dry"))
        with HAClient(ha.url, TOKEN) as client:
            run_apply(loaded, client, url=ha.url, lang=lang, out=out, undo_dir=Path(tmp), list_limit=5)
        out(t("demo_writes_received", count=len(ha.write_commands)))

        # 4. apply for real (against the fake)
        out("")
        out(t("demo_step_apply"))
        with HAClient(ha.url, TOKEN) as client:
            code = run_apply(loaded, client, url=ha.url, lang=lang, out=out, yes=True, undo_dir=Path(tmp), list_limit=5)
        if code:
            return code
        dropped = {c["entity_id"] for c in loaded.changes}
        after_rec = reconstruct(storage, profile, exclude=dropped)
        after = build_report(after_rec, tokenizer, ha_version=version, ctx=ctx, margin_pct=margin_pct)
        out(t("demo_after_line", tokens=f"{after['system_prompt_tokens']:,}", pct=after["usage_pct"],
              verdict=verdict_label(lang, after["verdict"])))

        # 5. undo
        out("")
        out(t("demo_step_undo"))
        undo_file = next(Path(tmp).glob("undo-*.yaml"))
        with HAClient(ha.url, TOKEN) as client:
            code = run_undo(undo_file, client, lang=lang, out=out, yes=True)
        if code:
            return code
        if ha.exposed == initially_exposed:
            out(t("demo_restored", count=len(initially_exposed)))
        else:  # should never happen; say so instead of pretending
            out(t("demo_not_restored"))
            return 4
    out("")
    out(t("demo_next"))
    return 0
