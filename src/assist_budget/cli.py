"""Command line interface: report, suggest, apply, undo, demo."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from . import EXIT_INPUT, EXIT_OK, EXIT_OVER, __version__
from .apply import load_undo, run_apply, run_undo
from .context import reconstruct
from .demo import DEFAULT_CTX, run_demo
from .errors import AssistBudgetError
from .ha_ws import HAClient, validate_url
from .i18n import ENV_VAR, LANGUAGES, resolve_lang, translate
from .profiles import select_profile
from .report import budget_target, build_report, render, render_warnings
from .storage import Storage, load_storage
from .suggest import load_plan, make_plan, plan_to_yaml, write_plan
from .tokenize import TOKENIZERS, get_tokenizer

DEFAULT_URL = "ws://homeassistant.local:8123/api/websocket"


def _find_lang(argv: Sequence[str]) -> str | None:
    """Read ``--lang`` before argparse runs, so --help itself is translated."""
    for index, arg in enumerate(argv):
        if arg == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def _positive_int_for(lang: str):
    """Return an argparse type that accepts whole numbers above 0, with errors in ``lang``."""
    def convert(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(translate(lang, "err_arg_not_int", value=repr(text))) from None
        if value <= 0:
            raise argparse.ArgumentTypeError(translate(lang, "err_arg_positive"))
        return value
    convert.__name__ = "int"  # argparse shows the type name in some messages
    return convert


def _percent_for(lang: str):
    """Return an argparse type for a percentage from 0 up to 100, with errors in ``lang``."""
    def convert(text: str) -> float:
        try:
            value = float(text)
        except ValueError:
            raise argparse.ArgumentTypeError(translate(lang, "err_arg_not_number", value=repr(text))) from None
        if not 0 <= value < 100:
            raise argparse.ArgumentTypeError(translate(lang, "err_arg_margin_range"))
        return value
    convert.__name__ = "percent"
    return convert


def build_parser(lang: str) -> argparse.ArgumentParser:
    """Build the argument parser with help text in ``lang``."""
    t = lambda key, **kw: translate(lang, key, **kw)  # noqa: E731
    _positive_int = _positive_int_for(lang)
    _percent = _percent_for(lang)
    parser = argparse.ArgumentParser(prog="assist-budget", description=t("help_description"),
                                     epilog=t("help_epilog"))
    parser.add_argument("--lang", choices=LANGUAGES, help=t("help_lang", env=ENV_VAR))
    parser.add_argument("--version", action="version", version=f"assist-budget {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def analysis_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("path", help=t("help_path"))
        p.add_argument("--ha-version", metavar="VERSION", help=t("help_ha_version"))
        p.add_argument("--ctx", type=_positive_int, default=8192, metavar="TOKENS", help=t("help_ctx"))
        p.add_argument("--reserve", type=int, default=0, metavar="TOKENS", help=t("help_reserve"))
        p.add_argument("--margin", type=_percent, default=10.0, metavar="PERCENT", help=t("help_margin"))
        p.add_argument("--tokenizer", choices=TOKENIZERS, default="approx", help=t("help_tokenizer"))
        p.add_argument("--instructions", metavar="FILE", help=t("help_instructions"))

    rep = sub.add_parser("report", help=t("help_report"), description=t("help_report"))
    analysis_options(rep)
    rep.add_argument("--top", type=_positive_int, default=10, metavar="N", help=t("help_top"))
    rep.add_argument("--format", choices=("table", "json", "md"), default="table", help=t("help_format"))
    rep.add_argument("--fail-over", action="store_true", help=t("help_fail_over"))

    sug = sub.add_parser("suggest", help=t("help_suggest"), description=t("help_suggest"))
    analysis_options(sug)
    sug.add_argument("--target", type=_positive_int, metavar="TOKENS", help=t("help_target"))
    sug.add_argument("--keep", action="append", default=[], metavar="GLOB", help=t("help_keep"))
    sug.add_argument("--drop", action="append", default=[], metavar="GLOB", help=t("help_drop"))
    sug.add_argument("--out", metavar="FILE", help=t("help_out"))

    for name in ("apply", "undo"):
        p = sub.add_parser(name, help=t(f"help_{name}"), description=t(f"help_{name}"))
        p.add_argument("file", help=t(f"help_{name}_file"))
        p.add_argument("--url", default=DEFAULT_URL, help=t("help_url", default=DEFAULT_URL))
        p.add_argument("--token-env", default="HA_TOKEN", metavar="NAME", help=t("help_token_env"))
        p.add_argument("--yes", action="store_true", help=t(f"help_{name}_yes"))
        if name == "apply":
            p.add_argument("--force", action="store_true", help=t("help_force"))
            p.add_argument("--undo-dir", default=".", metavar="DIR", help=t("help_undo_dir"))

    dem = sub.add_parser("demo", help=t("help_demo"), description=t("help_demo"))
    dem.add_argument("--ctx", type=_positive_int, default=DEFAULT_CTX, metavar="TOKENS", help=t("help_ctx"))
    return parser


def _analyze(args: argparse.Namespace):
    """Shared by report and suggest: load, pick the profile, rebuild, tokenize."""
    storage: Storage = load_storage(args.path)
    version = args.ha_version or storage.ha_version
    if not version:
        raise AssistBudgetError("err_no_version", path=args.path)
    profile, profile_warnings = select_profile(version)
    instructions = None
    if args.instructions:
        try:
            instructions = Path(args.instructions).read_text(encoding="utf-8")
        except OSError as exc:
            raise AssistBudgetError("err_path_not_found", path=args.instructions) from exc
    tokenizer = get_tokenizer(args.tokenizer)
    rec = reconstruct(storage, profile, instructions)
    rec.warnings = [*storage.warnings, *profile_warnings, *rec.warnings]
    return storage, rec, tokenizer, version, instructions


def _cmd_report(args: argparse.Namespace, lang: str, out: TextIO) -> int:
    _, rec, tokenizer, version, _ = _analyze(args)
    report = build_report(rec, tokenizer, ha_version=version, ctx=args.ctx, reserve=args.reserve,
                          margin_pct=args.margin, top=args.top)
    print(render(report, lang, args.format), file=out)
    return EXIT_OVER if args.fail_over and report["verdict"] == "over" else EXIT_OK


def _cmd_suggest(args: argparse.Namespace, lang: str, out: TextIO) -> int:
    storage, rec, tokenizer, version, instructions = _analyze(args)
    target = args.target if args.target else budget_target(args.ctx, args.margin, args.reserve)
    plan = make_plan(storage, rec, tokenizer, target=target, ctx=args.ctx, keep=args.keep,
                     drop=args.drop, instructions=instructions, ha_version=version)
    t = lambda key, **kw: translate(lang, key, **kw)  # noqa: E731
    # With --out the summary goes to stdout; without it stdout carries the plan itself.
    info = out if args.out else sys.stderr
    for line in render_warnings(lang, rec.warnings):
        print(f"{t('warn_prefix')}: {line}", file=info)
    if args.out:
        write_plan(plan, Path(args.out))
    else:
        print(plan_to_yaml(plan), end="", file=out)
    print(t("suggest_summary", count=len(plan.changes), before=f"{plan.before_tokens:,}",
            after=f"{plan.after_tokens:,}", target=f"{target:,}", tokenizer=tokenizer.name), file=info)
    if not plan.target_reached:
        print(t("suggest_target_missed", target=f"{target:,}"), file=info)
    if args.out:
        print(t("suggest_written", path=args.out), file=info)
    return EXIT_OK


def _token(args: argparse.Namespace, env: Mapping[str, str]) -> str:
    token = env.get(args.token_env, "")
    if not token:
        raise AssistBudgetError("err_no_token", name=args.token_env)
    return token


def _cmd_apply(args: argparse.Namespace, lang: str, out: TextIO, env: Mapping[str, str]) -> int:
    plan = load_plan(Path(args.file))
    validate_url(args.url)
    token = _token(args, env)
    emit = lambda text: print(text, file=out)  # noqa: E731
    with HAClient(args.url, token) as client:
        return run_apply(plan, client, url=args.url, lang=lang, out=emit, yes=args.yes, force=args.force,
                         undo_dir=Path(args.undo_dir))


def _cmd_undo(args: argparse.Namespace, lang: str, out: TextIO, env: Mapping[str, str]) -> int:
    load_undo(Path(args.file))  # check the file before touching the network
    validate_url(args.url)
    token = _token(args, env)
    emit = lambda text: print(text, file=out)  # noqa: E731
    with HAClient(args.url, token) as client:
        return run_undo(Path(args.file), client, lang=lang, out=emit, yes=args.yes)


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None,
         stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    """Entry point; returns the process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    lang = resolve_lang(_find_lang(argv), env)
    if lang not in LANGUAGES:  # defensive: resolve_lang only returns en/ko
        lang = "en"
    parser = build_parser(lang)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version or a usage error
        return int(exc.code) if isinstance(exc.code, int) else EXIT_INPUT
    try:
        if args.command == "report":
            return _cmd_report(args, lang, out)
        if args.command == "suggest":
            return _cmd_suggest(args, lang, out)
        if args.command == "apply":
            return _cmd_apply(args, lang, out, env)
        if args.command == "undo":
            return _cmd_undo(args, lang, out, env)
        return run_demo(args.ctx, lang, lambda text: print(text, file=out))
    except AssistBudgetError as exc:
        print(f"{translate(lang, 'error_prefix')}: {translate(lang, exc.key, **exc.params)}", file=err)
        return exc.exit_code
    except KeyboardInterrupt:
        print(translate(lang, "interrupted"), file=err)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
