#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VISUAL-INJECTION 의 공격 페이지 서버. 표준 라이브러리만 쓴다.

**페이지를 서빙하고 페이지가 보내는 사건을 hits.jsonl 에 기록한다.** 판정은 그 기록으로
한다. 비율·집계는 내지 않는다.

  PORT=8002 python3 serve.py        (웹 UI 는 알아서 띄운다)

★ 게스트(VM)가 접속해야 해서 0.0.0.0 에 붙는다. 이 포트를 터널·프록시로 내보내지 말 것.
"""
from __future__ import annotations

import json
import os
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "webroot"
HITS = HERE / "hits.jsonl"
PORT = int(os.environ.get("PORT", "8002"))


def log(event: str, **kw) -> None:
    row = {"ts": time.time(), "event": event, **kw}
    with HITS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[{PORT}] {event} {kw}", flush=True)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):                                                  # noqa: N802
        if self.path.split("?", 1)[0] in ("/", "/index.html"):
            log("SERVED", path=self.path)
        return super().do_GET()

    def do_POST(self):                                                 # noqa: N802
        # 페이지가 보내는 사건: injection_visible / cta_clicked / task_completed
        if self.path.split("?", 1)[0] != "/api/event":
            self.send_error(404); return
        try:
            n = int(self.headers.get("content-length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:                                              # noqa: BLE001
            data = {}
        event = str(data.get("event") or "unknown")
        log(event, run_id=str(data.get("run_id") or ""))
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):                                              # noqa: N802
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"[serve] {ROOT} -> http://0.0.0.0:{PORT}  (기록 {HITS.name})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
