#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VISUAL-INJECTION — 화면에 심어진 가짜 버튼을 사용자 지시로 받아들이는지 본다.

이 파일은 이게 전부다. 실제 실행은 공용 드라이버(`security_scenarios/probe.py`)가 한다.
무엇을 재는지는 ABOUT.md, 어떻게 판정하는지는 probe.json 에 적는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from probe import run_probe                                            # noqa: E402

KIND = "probe"
ARMS = ("baseline", "defense")
ARMS_LABEL = "사용자 경고"

if __name__ == "__main__":
    raise SystemExit(run_probe(Path(__file__).resolve().parent))
