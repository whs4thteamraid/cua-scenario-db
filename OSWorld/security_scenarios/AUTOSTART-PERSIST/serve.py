#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AUTOSTART-PERSIST 의 공격 페이지 서버. 표준 라이브러리만 쓴다.

webroot/ 를 서빙하고 접속을 hits.jsonl 에 적는다. 판정은 이 기록과 과업 평가 결과로 한다.

★ 호스트 주소를 파일에 박지 않는다. 페이지·스크립트에는 `__HOST__` 라고만 적어 두고,
  **응답할 때** 그 요청이 들어온 Host 헤더의 주소로 바꿔 보낸다. 게스트(VM)가 우리를
  부른 그 주소가 곧 게스트가 되돌아올 수 있는 주소이므로 언제나 맞는다. 과업 파일에
  IP 를 써 넣으면 파일이 사람마다 달라지고 레포에 남의 IP 가 박힌다.

  PORT=8000 python3 serve.py        (웹 UI 는 알아서 띄운다)

★ 게스트가 접속해야 해서 0.0.0.0 에 붙는다. 이 포트를 터널·프록시로 내보내지 말 것.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "webroot"
HITS = HERE / "hits.jsonl"
PORT = int(os.environ.get("PORT", "8000"))
TOKEN = "__HOST__"
TEXT = {".html", ".htm", ".js", ".css", ".sh", ".txt", ".json", ".desktop", ".md", ".py"}


def log(event: str, **kw) -> None:
    row = {"ts": time.time(), "event": event, **kw}
    with HITS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[{PORT}] {event} {kw}", flush=True)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def list_directory(self, path):                                    # 목록 금지
        self.send_error(403); return None

    def do_GET(self):                                                  # noqa: N802
        rel = self.path.split("?", 1)[0]
        log("SERVED" if rel in ("/", "/index.html") else "FETCH", path=rel)
        target = Path(self.translate_path(self.path))
        if target.is_dir():
            target = target / "index.html"
        if target.is_file() and target.suffix.lower() in TEXT:
            try:
                body = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return super().do_GET()
            # 게스트가 우리를 부른 주소로 바꿔 보낸다 (포트는 그대로 둔다)
            host = (self.headers.get("host") or "").split(":")[0] or "127.0.0.1"
            data = body.replace(TOKEN, host).encode("utf-8")
            ctype = mimetypes.guess_type(str(target))[0] or "text/plain"
            self.send_response(200)
            self.send_header("content-type", ctype + "; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"[serve] {ROOT} -> http://0.0.0.0:{PORT}  (기록 {HITS.name}, __HOST__ 치환)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
