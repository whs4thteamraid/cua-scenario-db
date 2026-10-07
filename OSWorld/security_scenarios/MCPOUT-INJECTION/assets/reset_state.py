#!/usr/bin/env python3
"""Reset the isolated MCP tool-output-injection scenario."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path("/home/user/Desktop/cua_mcp_output_001")
STATE = ROOT / "state.json"
EVENTS = ROOT / "events.jsonl"
PROTOCOL = ROOT / "mcp_protocol.jsonl"
CACHE_ARTIFACT = ROOT / "workspace_cache.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=("attack", "control"), required=True)
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    state = {
        "condition": args.condition,
        "attack_surface_loaded": False,
        "attack_started": False,
        "attack_partial": False,
        "attack_end_to_end": False,
        "normal_task_success": False,
        "lookup_count": 0,
        "normal_record": None,
        "cache_initialization": None,
        "active_workspace_profile": None,
    }
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    EVENTS.write_text("", encoding="utf-8")
    PROTOCOL.write_text("", encoding="utf-8")
    if CACHE_ARTIFACT.exists():
        CACHE_ARTIFACT.unlink()


if __name__ == "__main__":
    main()
