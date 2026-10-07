#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCPOUT-INJECTION — MCP 도구가 돌려준 값 속 지시를 새 작업으로 받아들이는지 본다.

이 파일은 이게 전부다. 실제 실행은 공용 드라이버(`security_scenarios/osw_task.py`)가 한다.
무엇을 재는지는 ABOUT.md, 어떻게 판정하는지는 task.json 에 적는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from osw_task import run_task                                          # noqa: E402

KIND = "probe"
ARMS = ("ATTACK", "CONTROL")
ARMS_LABEL = "공격 유무"

if __name__ == "__main__":
    raise SystemExit(run_task(Path(__file__).resolve().parent))
