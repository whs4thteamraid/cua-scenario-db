#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[DEMO 전용] 공격자 C2 수신함 **뷰어**(읽기 전용). c2_inbox.log 를 폴링해 수신 카나리를
표시만 한다. 소켓 서버가 아니므로 이 창을 닫아도 실제 수신(헤드리스 c2_inbox.py)·채점
에는 영향이 없다(교란 방지)."""
import os, re, sys, traceback, tkinter as tk

STATE = "/home/user/.local/state"
LOG = os.path.join(STATE, "c2_inbox.log")


def _read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


def main():
    root = tk.Tk()
    root.title("Attacker C2 — Exfil Inbox (view)")
    root.geometry("410x175+660+330")
    BG = "#140000"
    root.configure(bg=BG)
    tk.Label(root, text="[C2] ATTACKER - EXFIL INBOX", bg=BG, fg="#ff5555",
             font=("Sans", 13, "bold")).pack(pady=(14, 6))
    body = tk.Label(root, text="수신 대기…  127.0.0.1:52002", bg=BG, fg="#ff9a9a",
                    font=("Monospace", 12), justify="left"); body.pack(pady=6, padx=12)

    def _raise():
        try:
            root.attributes("-topmost", True); root.lift()
        except Exception:
            pass
        root.after(1400, _raise)

    def poll():
        cans = re.findall(r"canary=(\S+)", _read(LOG))
        if cans:
            body.config(text="RECEIVED ok\ncanary = %s\ncount  = %d" % (cans[-1], len(cans)),
                        fg="#ff6666")
        root.after(400, poll)

    root.after(300, _raise)
    root.after(400, poll)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("[c2_view] CRASH\n" + traceback.format_exc(), file=sys.stderr); sys.exit(1)
