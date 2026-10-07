#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RUNBOOK-TRUST — 비신뢰 문서를 증거가 아니라 실행 권한으로 읽는지 본다.

이 파일은 이게 전부다. 실제 실행은 공용 드라이버(`security_scenarios/osw_task.py`)가 한다.
무엇을 재는지는 ABOUT.md, 어떻게 판정하는지는 task.json 에 적는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from osw_task import run_task                                          # noqa: E402

KIND = "probe"

if __name__ == "__main__":
    raise SystemExit(run_task(Path(__file__).resolve().parent))
