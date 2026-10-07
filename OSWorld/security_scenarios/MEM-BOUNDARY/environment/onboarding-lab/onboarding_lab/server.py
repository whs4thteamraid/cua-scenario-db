from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .app import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Orbit authorization lab")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", type=Path, default=Path("data/orbit.db"))
    parser.add_argument(
        "--policy",
        choices=("observe", "enforce"),
        default="enforce",
        help="cross-project share policy (default: enforce)",
    )
    parser.add_argument("--log-level", default="info")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    app = create_app(db_path=args.db, policy_mode=args.policy)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
