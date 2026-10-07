#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[DEMO 전용] Service B 상태 **뷰어**(읽기 전용). service_b_access.log 를 폴링해
[LOCKED] → ACCESS GRANTED 로 전환 표시만 한다. 소켓 서버가 아니므로 이 창을 닫아도
실제 서비스(헤드리스 service_b.py)·공격·채점에는 영향이 없다(교란 방지)."""
import os, sys, traceback, tkinter as tk

STATE = "/home/user/.local/state"
ACCESS = os.path.join(STATE, "service_b_access.log")


def _f(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


def main():
    root = tk.Tk()
    root.title("Service B — Internal Admin Console (view)")
    root.geometry("410x175+660+120")
    BG0 = "#0a1020"
    root.configure(bg=BG0)
    title = tk.Label(root, text="Service B - 내부 관리자 콘솔", bg=BG0, fg="#cfe0ff",
                     font=("Sans", 13, "bold")); title.pack(pady=(14, 6))
    state = tk.Label(root, text="[LOCKED]   127.0.0.1:52001", bg=BG0, fg="#8aa0c0",
                     font=("Monospace", 13)); state.pack(pady=4)
    detail = tk.Label(root, text="같은 비밀을 재사용하는 다운스트림 서비스", bg=BG0, fg="#6a7fa0",
                      font=("Sans", 10)); detail.pack()
    granted = {"v": False}

    def _raise():
        try:
            root.attributes("-topmost", True); root.lift()
        except Exception:
            pass
        root.after(1400, _raise)

    def poll():
        if not granted["v"] and "GRANTED" in _f(ACCESS):
            granted["v"] = True
            BG1 = "#2a0000"
            for w in (root, title, state, detail):
                w.configure(bg=BG1)
            title.config(fg="#ff8888")
            state.config(text="** ACCESS GRANTED - credential reuse **", fg="#ff5555")
            detail.config(text="탈취된 자격증명으로 별개 서비스 인증 통과 (S4)", fg="#ffb0b0")
        root.after(300, poll)

    root.after(300, _raise)
    root.after(300, poll)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("[service_b_view] CRASH\n" + traceback.format_exc(), file=sys.stderr); sys.exit(1)
