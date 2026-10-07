from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .database import add_document, audit_records, create_experiment, serialize_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local administration for the Orbit lab")
    parser.add_argument("--db", type=Path, default=Path("data/orbit.db"))
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "init",
        help="create and activate a new run; earlier runs and logs are retained",
    )

    export = commands.add_parser("export-audit", help="export audit records")
    export.add_argument("--run-id")
    export.add_argument("--format", choices=("json", "jsonl"), default="jsonl")
    export.add_argument("--output", type=Path, help="file path; omit to print to stdout")

    add = commands.add_parser("add-document", help="add local test material to the active run")
    add.add_argument("--project", choices=("A", "B"), required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--content", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "init":
        print(json.dumps(create_experiment(args.db), ensure_ascii=False, indent=2))
        return
    if args.command == "add-document":
        result = add_document(args.db, args.project, args.title, args.content)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    records = audit_records(args.db, args.run_id)
    output = serialize_audit(records, args.format)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"exported {len(records)} events to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
