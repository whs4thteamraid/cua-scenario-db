#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""<시나리오 이름> — 한 줄 설명.

이 파일은 이게 전부다. 실제 실행은 공용 드라이버(`security_scenarios/probe.py`)가 한다.
무엇을 재는지는 ABOUT.md, 어떻게 판정하는지는 probe.json 에 적는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from probe import run_probe                                           # noqa: E402

KIND = "probe"                      # 목록에서 '단일 표면' 으로 묶인다
ARMS = ("lure", "no-lure")          # 조건이 없으면 이 두 줄을 지운다
ARMS_LABEL = "페이지 유인"

if __name__ == "__main__":
    raise SystemExit(run_probe(Path(__file__).resolve().parent))
