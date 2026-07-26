"""Stable Phase 0 command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from .contracts import Capability, OperationRequest, OperationResult, ProvenanceRecord
from .kernel import (
    FixedClock, MalformedProviderOutput, ProviderError, ProviderRegistry,
    RatiocinatusError, SystemClock, Workspace, canonical_bytes,
    canonical_hash, export_schemas, load_contract, resolve_configuration,
)
from .version import (
    __version__, CONTRACT_VERSION, REPORT_VERSION, SERIALIZATION_VERSION,
    WORKSPACE_VERSION,
)

EXIT_SUCCESS = 0
EXIT_INVALID = 2
EXIT_MISSING = 3
EXIT_UNAVAILABLE = 4
EXIT_INTEGRITY = 5
EXIT_INTERNAL = 10


def _clock(deterministic: bool):
    return (
        FixedClock(datetime(2000, 1, 1, tzinfo=timezone.utc))
        if deterministic else SystemClock()
    )


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _emit(value: Any, structured: bool) -> None:
    if structured:
        print(json.dumps(_plain(value), sort_keys=True, indent=2))
    elif isinstance(value, BaseModel):
        for key, item in value.model_dump(mode="json").items():
            print(f"{key}: {item}")
    elif isinstance(value, (list, tuple)):
        if not value:
            print("(none)")
        for item in value:
            if isinstance(item, BaseModel):
                identity = next(
                    (getattr(item, key) for key in (
                        "source_id", "artifact_id", "provider_id", "operation_id",
                        "provenance_id", "report_id",
                    ) if hasattr(item, key)), None,
                )
                print(identity or str(item))
            else:
                print(item)
    else:
        print(value)


def _find_operation(workspace: Workspace, operation_id: str) -> dict[str, Any]:
    requests = workspace._records("operations/requests.jsonl", OperationRequest)
    results = workspace._records("operations/results.jsonl", OperationResult)
    provenance = workspace._records("provenance/records.jsonl", ProvenanceRecord)
    return {
        "request": next((r.model_dump(mode="json") for r in requests if r.operation_id == operation_id), None),
        "result": next((r.model_dump(mode="json") for r in results if r.operation_id == operation_id), None),
        "provenance": [p.model_dump(mode="json") for p in provenance if p.operation_id == operation_id],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ratiocinatus")
    parser.add_argument("--json", action="store_true", help="structured JSON output")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version")
    schemas = sub.add_parser("schema-export")
    schemas.add_argument("destination", type=Path)

    workspace = sub.add_parser("workspace")
    wsub = workspace.add_subparsers(dest="action", required=True)
    for action in ("inspect", "validate"):
        p = wsub.add_parser(action); p.add_argument("workspace", type=Path)
    p = wsub.add_parser("init"); p.add_argument("workspace", type=Path)
    p.add_argument("--deterministic", action="store_true")
    p.add_argument("--copy-sources", action="store_true")
    p = wsub.add_parser("export"); p.add_argument("workspace", type=Path); p.add_argument("destination", type=Path)

    source = sub.add_parser("source")
    ssub = source.add_subparsers(dest="action", required=True)
    p = ssub.add_parser("register"); p.add_argument("workspace", type=Path); p.add_argument("source", type=Path)
    p = ssub.add_parser("list"); p.add_argument("workspace", type=Path)
    p = ssub.add_parser("verify"); p.add_argument("workspace", type=Path); p.add_argument("source_id")

    artifact = sub.add_parser("artifact")
    asub = artifact.add_subparsers(dest="action", required=True)
    p = asub.add_parser("list"); p.add_argument("workspace", type=Path)
    p = asub.add_parser("inspect"); p.add_argument("workspace", type=Path); p.add_argument("artifact_id")

    provider = sub.add_parser("provider")
    psub = provider.add_subparsers(dest="action", required=True)
    psub.add_parser("list")
    p = psub.add_parser("inspect"); p.add_argument("provider_id")
    p = psub.add_parser("invoke"); p.add_argument("workspace", type=Path)
    p.add_argument("provider_id"); p.add_argument("capability", choices=[c.value for c in Capability])
    p.add_argument("input"); p.add_argument("--mode", choices=["success", "failure", "malformed"], default="success")

    operation = sub.add_parser("operation")
    osub = operation.add_subparsers(dest="action", required=True)
    p = osub.add_parser("inspect"); p.add_argument("workspace", type=Path); p.add_argument("operation_id")

    replay = sub.add_parser("replay")
    replay.add_argument("workspace", type=Path); replay.add_argument("operation_id")

    report = sub.add_parser("report")
    report.add_argument("workspace", type=Path)

    config = sub.add_parser("config")
    csub = config.add_subparsers(dest="action", required=True)
    p = csub.add_parser("inspect"); p.add_argument("workspace", type=Path)
    return parser


def run(args: argparse.Namespace) -> int:
    structured = args.json
    registry = ProviderRegistry.with_mocks()
    if args.command == "version":
        _emit({
            "application": __version__, "contracts": CONTRACT_VERSION,
            "serialization": SERIALIZATION_VERSION,
            "workspace": WORKSPACE_VERSION, "reports": REPORT_VERSION,
        }, structured)
        return EXIT_SUCCESS
    if args.command == "schema-export":
        _emit([str(p) for p in export_schemas(args.destination)], structured)
        return EXIT_SUCCESS
    if args.command == "workspace" and args.action == "init":
        config = resolve_configuration(
            str(args.workspace),
            cli_values={"deterministic": args.deterministic, "copy_sources": args.copy_sources},
        )
        result = Workspace.initialize(args.workspace, config, _clock(args.deterministic))
        _emit(result.manifest, structured); return EXIT_SUCCESS
    if args.command == "provider" and args.action in {"list", "inspect"}:
        if args.action == "list":
            _emit(registry.list(), structured)
        else:
            _emit(registry.get(args.provider_id).descriptor, structured)
        return EXIT_SUCCESS

    workspace_path = getattr(args, "workspace", None)
    workspace = Workspace.open(workspace_path)
    clock = _clock(workspace.config.deterministic)
    if args.command == "workspace":
        if args.action == "inspect": _emit(workspace.manifest, structured)
        elif args.action == "validate":
            report = workspace.validate(clock); _emit(report, structured)
            return EXIT_SUCCESS if report.valid else EXIT_INTEGRITY
        elif args.action == "export": _emit(str(workspace.export(args.destination)), structured)
    elif args.command == "source":
        if args.action == "register": _emit(workspace.register_source(args.source, clock), structured)
        elif args.action == "list": _emit(workspace.list_sources(), structured)
        elif args.action == "verify":
            valid = workspace.verify_source(args.source_id); _emit({"valid": valid}, structured)
            return EXIT_SUCCESS if valid else EXIT_INTEGRITY
    elif args.command == "artifact":
        artifacts = workspace.list_artifacts()
        if args.action == "list": _emit(artifacts, structured)
        else:
            artifact = next((a for a in artifacts if a.artifact_id == args.artifact_id), None)
            if artifact is None: raise FileNotFoundError(args.artifact_id)
            _emit(artifact, structured)
    elif args.command == "provider":
        provider = registry.get(args.provider_id)
        result = workspace.invoke_provider(
            provider, Capability(args.capability), args.input, clock, args.mode
        )
        _emit(result, structured)
    elif args.command == "operation":
        result = _find_operation(workspace, args.operation_id)
        if result["request"] is None: raise FileNotFoundError(args.operation_id)
        _emit(result, structured)
    elif args.command == "replay":
        result = workspace.replay(args.operation_id, registry, clock)
        _emit(result, structured)
        return EXIT_SUCCESS if result.status.value == "match" else EXIT_INTEGRITY
    elif args.command == "report":
        report = workspace.validate(clock)
        destination = workspace.root / "reports" / "workspace-report.json"
        destination.write_bytes(canonical_bytes(report))
        human = workspace.root / "reports" / "workspace-report.txt"
        human.write_text(
            f"Ratiocinatus workspace report\nWorkspace: {workspace.manifest.workspace_id}\n"
            f"Valid: {report.valid}\nFindings: {len(report.findings)}\n",
            encoding="utf-8",
        )
        _emit({"machine": str(destination), "human": str(human)}, structured)
    elif args.command == "config":
        _emit(workspace.config, structured)
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if "fixture" in arguments:
        from .fixture_cli import main as fixture_main
        return fixture_main(arguments)
    try:
        return run(build_parser().parse_args(arguments))
    except (ValidationError, ValueError) as exc:
        print(f"invalid request: {exc}", file=sys.stderr); return EXIT_INVALID
    except FileNotFoundError as exc:
        print(f"missing input: {exc}", file=sys.stderr); return EXIT_MISSING
    except (ProviderError, MalformedProviderOutput) as exc:
        print(f"provider failure: {exc}", file=sys.stderr); return EXIT_UNAVAILABLE
    except RatiocinatusError as exc:
        print(f"{exc.kind.value}: {exc}", file=sys.stderr); return EXIT_INTEGRITY
    except Exception as exc:
        print(f"internal failure: {exc}", file=sys.stderr); return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())

