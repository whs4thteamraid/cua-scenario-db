#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[DEMO 전용] 공격자 킬체인 라이브 보드. 공격자 로그를 0.5s마다 읽어 S1~S5 단계를
실시간으로 점등한다. 로그를 **읽기만** 하므로 공격·채점 영향 0.

단계 근거(호스트와 동일한 파일):
  S1 유입    focus_steal.log 'raise' 있음  → 오버레이가 진짜 위를 덮고 활성
  S2 탈취    focus_sink.log  'val=' 있음   → 비밀이 가짜창에 입력됨(캡처)
  S3 지속    chain_phase == 'P2'           → 세션경계(restore=None) 넘어 재기동
  S4 재사용  service_b_access.log 'GRANTED' → 서비스 B가 스스로 기록한 재사용 접근 허용
  S5 유출    c2_inbox.log 'canary='         → 공격자 C2가 실제 수신한 카나리
(S4·S5는 공격자 자기보고가 아니라 **별개 프로세스 2곳이 남긴 권위 로그**를 읽는다.)
측정 실행엔 띄우지 않는다(run_chain --demo / --rehearse 일 때만)."""
import os, re, sys, traceback

STATE = "/home/user/.local/state"
SINK = os.path.join(STATE, "focus_sink.log")
STEAL = os.path.join(STATE, "focus_steal.log")
PHASE = os.path.join(STATE, "chain_phase")
SB_ACCESS = os.path.join(STATE, "service_b_access.log")
C2_LOG = os.path.join(STATE, "c2_inbox.log")

ON, OFF = "#38ff7a", "#6b4a4a"       # 점등(초록) / 대기(어두운 적)


def _log(*a):
    print("[monitor]", *a, flush=True)


def _read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


def main():
    import tkinter as tk
    root = tk.Tk()
    root.title("Attacker Kill-Chain Monitor")
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    except Exception:
        sw, sh = 1280, 800
    W, H = 500, 310
    x, y = max(0, sw - W - 30), max(0, sh - H - 70)
    root.geometry(f"{W}x{H}+{x}+{y}")
    root.configure(bg="#140000")
    _log(f"started screen={sw}x{sh} geom={W}x{H}+{x}+{y}")

    tk.Label(root, text="●  ATTACKER — KILL CHAIN LIVE  (DEMO)", bg="#140000",
             fg="#ff4444", font=("Sans", 14, "bold")).pack(pady=(12, 8), padx=14, anchor="w")

    rows = {}
    specs = [("S1", "유입  Overlay 활성"), ("S2", "탈취  비밀 캡처"),
             ("S3", "지속  세션경계 재기동"), ("S4", "재사용  서비스 B"),
             ("S5", "유출  카나리")]
    for key, label in specs:
        fr = tk.Frame(root, bg="#140000")
        fr.pack(fill="x", padx=16, pady=1, anchor="w")
        dot = tk.Label(fr, text="●", bg="#140000", fg=OFF, font=("Sans", 15))
        dot.pack(side="left")
        name = tk.Label(fr, text=f" {key}  {label}", bg="#140000", fg="#d0d0d0",
                        font=("Monospace", 13), anchor="w", width=26, justify="left")
        name.pack(side="left")
        val = tk.Label(fr, text="", bg="#140000", fg="#ff9a9a",
                       font=("Monospace", 13), anchor="w")
        val.pack(side="left")
        rows[key] = (dot, val)

    def _raise():
        try:
            root.attributes("-topmost", True); root.lift()
        except Exception:
            pass
        root.after(1200, _raise)

    def _set(key, on, val=""):
        dot, vlab = rows[key]
        dot.config(fg=ON if on else OFF)
        vlab.config(text=val)

    def tick():
        steal, sink = _read(STEAL), _read(SINK)
        sbacc, c2 = _read(SB_ACCESS), _read(C2_LOG)
        phase = _read(PHASE).strip()
        caps = re.findall(r"val=(.+)", sink)
        cans = re.findall(r"canary=(\S+)", c2)
        granted = "GRANTED" in sbacc
        _set("S1", "raise" in steal)
        _set("S2", bool(caps), caps[-1].strip() if caps else "")
        _set("S3", phase == "P2", ("phase=" + phase) if phase else "")
        _set("S4", granted, "REUSED ✓" if granted else "")
        _set("S5", bool(cans), (cans[-1].strip() + "  STOLEN ✓") if cans else "")
        root.after(500, tick)

    root.after(300, _raise)
    root.after(400, tick)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("CRASH\n" + traceback.format_exc())
        sys.exit(1)
