#!/usr/bin/env python3
"""Idempotently rebuild the controlled development workspace from templates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


HARNESS_ROOT = Path("/home/user/Desktop/cua_doc_ipi_004_harness")
TEMPLATE_ROOT = HARNESS_ROOT / "templates"
PROJECT_ROOT = Path("/home/user/Desktop/readme_dev_task")
STATE_PATH = HARNESS_ROOT / "state.json"
EXPOSURE_MARKER = HARNESS_ROOT / "test_output_surface_seen.json"
EXPECTED_PROJECT_ROOT = Path("/home/user/Desktop/readme_dev_task")
IGNORED_PARTS = {".git", ".pytest_cache", ".mypy_cache", "__pycache__"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS or part.endswith(".pyc") for part in relative.parts):
            continue
        result[relative.as_posix()] = sha256(path)
    return result


def atomic_write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=("attack", "control"), required=True)
    args = parser.parse_args()

    if PROJECT_ROOT != EXPECTED_PROJECT_ROOT:
        raise RuntimeError(f"refusing unexpected reset target: {PROJECT_ROOT}")

    common_template = TEMPLATE_ROOT / "common"
    condition_template = TEMPLATE_ROOT / args.condition
    if not common_template.is_dir() or not condition_template.is_dir():
        raise FileNotFoundError("scenario templates are incomplete")

    if PROJECT_ROOT.exists():
        shutil.rmtree(PROJECT_ROOT)
    EXPOSURE_MARKER.unlink(missing_ok=True)
    shutil.copytree(common_template, PROJECT_ROOT)
    shutil.copytree(condition_template, PROJECT_ROOT, dirs_exist_ok=True)

    state = {
        "schema_version": 1,
        "condition": args.condition,
        "attack_surface_loaded": False,
        "baseline_manifest": manifest(PROJECT_ROOT),
        "events": [],
    }
    atomic_write_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
