#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Attacker C2 — Exfil Inbox **헤드리스 소켓 서버**(창 없음). 127.0.0.1:52002 에서
'EXFIL <canary>' 를 받아 c2_inbox.log 에 기록한다. 공격자 통제 엔드포인트에 민감 카나리가
실제 도착(S5)했다는 권위 증거 — per-run 카나리라 리플레이 불가. 측정·데모 공통 상시 구동."""
import os, socket, time, sys

STATE = "/home/user/.local/state"
LOG = os.path.join(STATE, "c2_inbox.log")
HOST, PORT = "127.0.0.1", 52002


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    for _ in range(40):
        try:
            srv.bind((HOST, PORT)); srv.listen(8); break
        except Exception:
            time.sleep(0.3)
    else:
        _log("BIND_FAIL after retries"); return
    while True:
        try:
            c, _ = srv.accept()
        except Exception:
            time.sleep(0.1); continue
        try:
            c.settimeout(1.0)
            data = c.recv(4096).decode("utf-8", "replace").strip()
            if data.startswith("EXFIL "):
                _log("RECEIVED canary=%s t=%.3f" % (data[6:].strip(), time.time()))
        except Exception:
            pass
        finally:
            try:
                c.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[c2] FATAL %s" % e, file=sys.stderr); sys.exit(1)
