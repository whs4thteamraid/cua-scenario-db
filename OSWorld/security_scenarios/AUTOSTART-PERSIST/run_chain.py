#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AUTOSTART-PERSIST — 로그인 자동실행 항목을 심어 재부팅을 넘기는지 본다.

이 파일은 이게 전부다. 실제 실행은 공용 드라이버(`security_scenarios/probe.py`)가 한다.
무엇을 재는지는 ABOUT.md, 어떻게 판정하는지는 probe.json 에 적는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from probe import run_probe                                            # noqa: E402

KIND = "probe"

if __name__ == "__main__":
    raise SystemExit(run_probe(Path(__file__).resolve().parent))
