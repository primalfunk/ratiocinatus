"""CLI operations for the controlled proof corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .fixture_tools import (
    DEFAULT_FIXTURE_ROOT, compare_fixtures, export_fixture, inspect_fixture,
    read_json, run_generator, validate_fixture, write_checksums,
)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="ratiocinatus")
    top.add_argument("--json", action="store_true")
    fixture = top.add_subparsers(dest="group", required=True).add_parser("fixture")
    sub = fixture.add_subparsers(dest="action", required=True)
    for name in ("list", "inspect", "validate", "checksum", "license-report"):
        item = sub.add_parser(name)
        if name != "list":
            item.add_argument("--root", type=Path, default=DEFAULT_FIXTURE_ROOT)
        if name == "validate":
            item.add_argument("--no-media", action="store_true")
    for name in ("generate", "render"):
        item = sub.add_parser(name)
        item.add_argument("variant", choices=["clean", "naturalized", "adversarial", "all"])
        item.add_argument("--root", type=Path, default=DEFAULT_FIXTURE_ROOT)
        item.add_argument("--provider", default="kokoro-onnx", choices=["kokoro-onnx"])
        item.add_argument("--dry-run", action="store_true")
        item.add_argument("--replace", action="store_true")
    item = sub.add_parser("regenerate-line")
    item.add_argument("variant", choices=["clean", "naturalized", "adversarial"])
    item.add_argument("line_id")
    item.add_argument("--root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    item.add_argument("--replace", action="store_true")
    item = sub.add_parser("export")
    item.add_argument("destination", type=Path)
    item.add_argument("--root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    item.add_argument("--replace", action="store_true")
    item = sub.add_parser("compare")
    item.add_argument("left", type=Path); item.add_argument("right", type=Path)
    return top


def emit(value, structured: bool) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if structured:
        print(json.dumps(value, indent=2, sort_keys=True))
    elif isinstance(value, dict):
        for key, item in value.items(): print(f"{key}: {item}")
    else:
        print(value)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "list":
            emit([inspect_fixture()], args.json); return 0
        if args.action == "inspect":
            emit(inspect_fixture(args.root), args.json); return 0
        if args.action == "validate":
            report = validate_fixture(args.root, media=not args.no_media)
            emit(report, args.json); return 0 if report.valid else 5
        if args.action == "checksum":
            emit({"checksum_file": str(write_checksums(args.root))}, args.json); return 0
        if args.action == "license-report":
            emit(read_json(args.root / "manifests" / "license_manifest.json"), args.json); return 0
        if args.action in {"generate", "render"}:
            variants = (
                ["clean", "naturalized", "adversarial"]
                if args.variant == "all" else [args.variant]
            )
            results = {
                variant: run_generator(
                    args.root, variant, dry_run=args.dry_run,
                    replace=args.replace, render_only=args.action == "render",
                )
                for variant in variants
            }
            emit(results, args.json); return 0 if all(code == 0 for code in results.values()) else 10
        if args.action == "regenerate-line":
            code = run_generator(
                args.root, args.variant, replace=args.replace, line_id=args.line_id
            )
            emit({"exit_code": code}, args.json); return code
        if args.action == "export":
            emit({"export": str(export_fixture(args.root, args.destination, replace=args.replace))}, args.json)
            return 0
        if args.action == "compare":
            result = compare_fixtures(args.left, args.right)
            emit(result, args.json); return 0 if result["equal"] else 5
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr); return 2
    return 10

