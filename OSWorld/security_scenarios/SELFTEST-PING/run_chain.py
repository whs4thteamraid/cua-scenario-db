#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest_ping — 파이프라인 자체점검. 공격 시나리오가 아니다.

에이전트에게 터미널에서 한 줄을 실행하게 하고, 판정은 **호스트에서** 한다
(Session.shell 로 VM 파일을 읽는다). 모델 자기보고를 믿지 않는 것은 실제
시나리오와 같다 — 체인이 짧을 뿐이다.

  S1 파일 생성  → S2 이번 실행 토큰 일치 → S3 ping 응답
  (S3 는 환경에 따라 막힐 수 있다. 막혀도 S1·S2 가 되면 도구는 정상 → PARTIAL)

사용:
  python3 OSWorld/security_scenarios/selftest_ping/run_chain.py --model haiku --trials 1
  python3 OSWorld/security_scenarios/selftest_ping/run_chain.py --smoke --model haiku --trials 1
"""
import sys, os, json, argparse, secrets, traceback
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]      # 하네스 루트 자가탐색
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent                      # .../cua-scenario-db


def _rel(p) -> str:
    """로그에 호스트 절대경로(=사용자 계정명)를 찍지 않는다. 레포 기준으로 줄인다."""
    if not p:
        return "(미지정)"
    try:
        q = Path(str(p)).resolve()
    except Exception:                                              # noqa: BLE001
        return str(p)
    try:
        return q.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return ".../" + "/".join(q.parts[-2:]) if len(q.parts) >= 2 else str(q)

STEPS = 20
VM_FILE = "/home/user/selftest.txt"
TASK = json.loads((HERE / "task.json").read_text(encoding="utf-8"))
_WORDS = ("RIVER", "TIGER", "MAPLE", "COBALT", "ORBIT", "LEMON",
          "DELTA", "NORTH", "PIXEL", "AMBER", "QUARTZ", "VIVID")


def _token() -> str:
    """매 실행 새 토큰. 고정 문자열이면 '지난 판 잔재'와 구분이 안 된다.
       랜덤 hex 는 에이전트가 화면에서 오독하므로 읽기 쉬운 단어로 만든다."""
    return f"{secrets.choice(_WORDS)}-{secrets.choice(_WORDS)}-{secrets.randbelow(90) + 10}"


def _resolve_vmx(given: str) -> str:
    if given and Path(given).exists():
        return given
    if given and (ROOT / given).exists():
        return str(ROOT / given)
    found = sorted(ROOT.glob("vmware_vm_data/*/*.vmx"))
    if found:
        return str(found[0])
    # 없으면 빈 값 → Session 이 자동 다운로드 경로를 탄다(첫 실행).
    return ""


def read_state(s, token: str) -> dict:
    """호스트측 판정 — VM 파일을 직접 읽는다. 에이전트 발언은 쓰지 않는다."""
    body = s.shell(f"cat {VM_FILE} 2>/dev/null || true") or ""
    low = body.lower()
    return {
        "file_exists": bool(body.strip()),
        "token_ok": token in body,
        "ping_ok": ("bytes from" in low) or ("0% packet loss" in low),
        "bytes": len(body),
        "excerpt": body.strip()[-300:],
    }


def classify(st: dict) -> tuple:
    if not st["file_exists"]:
        return "FAIL_no_file", "S0"
    if not st["token_ok"]:
        return "FAIL_stale_or_wrong_token", "S1"
    if not st["ping_ok"]:
        return "PARTIAL_no_network", "S2"
    return "PASS", "S3"


def host_rows(st: dict) -> list:
    """렌더러의 범용 대조 카드용 (라벨, 값, 강조여부)."""
    yn = lambda v: ("예", "hit") if v else ("아니오", "")
    return [["S1 파일 생성", *yn(st["file_exists"])],
            ["S2 이번 실행 토큰 일치", *yn(st["token_ok"])],
            ["S3 ping 응답", *yn(st["ping_ok"])],
            ["파일 크기", f"{st['bytes']}B", ""]]


def _dump(tdir: Path, summ: dict) -> None:
    (tdir / "summary.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=2), encoding="utf-8")


def trial(i: int, model: str, vmx: str, outdir: Path) -> dict:
    from redteam.run_cua import Session
    token = _token()
    summ = {"trial": i, "model": model, "arm": "default", "token": token,
            "steps": STEPS, "status": "started"}
    tdir = outdir / model / "default" / f"t{i}"
    if tdir.exists():
        import shutil; shutil.rmtree(tdir)
    tdir.mkdir(parents=True, exist_ok=True)

    task = dict(TASK)
    task["instruction"] = TASK["instruction"].replace("__TOKEN__", token)

    with Session(model=model, vmx=vmx, snapshot="init_state",
                 tools=("computer",), memory=False) as s:
        rd = tdir / "p1"
        s.prepare(task, result_dir=rd, restore="init_state")
        a = s.make_agent(result_dir=rd, max_steps=STEPS)
        r = s.execute(a, task["instruction"], max_steps=STEPS, result_dir=rd)
        st = read_state(s, token)

    verdict, stage = classify(st)
    summ.update(status="complete", p1_state=st, p1_hit_cap=bool(r.get("hit_cap")),
                p1_verdict=verdict, verdict=verdict, chain_stage=stage,
                host_rows=host_rows(st))
    _dump(tdir, summ)
    print(f"[=] {model}/t{i}: {verdict} | stage={stage}  "
          f"(file={st['file_exists']} token={st['token_ok']} ping={st['ping_ok']})")
    return summ


def smoke(model: str, vmx: str, outdir: Path) -> dict:
    """에이전트·API 없이 VM·셸·판정 경로만 점검한다. 키가 없어도 돈다."""
    from redteam.run_cua import Session
    token = _token()
    rd = outdir / "_smoke" / "p1"
    rd.mkdir(parents=True, exist_ok=True)
    print(f"[smoke] 토큰 {token}")
    with Session(model=model, vmx=vmx, snapshot="init_state",
                 tools=("computer",), memory=False, check_api_key=False) as s:
        s.prepare(dict(TASK), result_dir=rd, restore="init_state")
        before = read_state(s, token)
        s.shell(f"ping -c 2 8.8.8.8 > {VM_FILE} 2>&1; echo '{token}' >> {VM_FILE}")
        after = read_state(s, token)
        s.shell(f"rm -f {VM_FILE}")
        cleaned = read_state(s, token)
    ok = (not before["file_exists"]) and after["token_ok"] and (not cleaned["file_exists"])
    print(f"[smoke] 정리전={before['file_exists']} 기록후_토큰={after['token_ok']} "
          f"정리후={cleaned['file_exists']}  ping={after['ping_ok']}")
    print(f"[smoke] {'통과 — VM·셸·판정 경로 정상' if ok else '실패 — 위 세 값을 보십시오'}"
          + ("" if after["ping_ok"] else "  (네트워크는 막혀 있음 — 도구 문제 아님)"))
    return {"smoke_ok": ok, "before": before, "after": after, "cleaned": cleaned}


def main() -> None:
    ap = argparse.ArgumentParser(description="파이프라인 자체점검 시나리오")
    ap.add_argument("--vmx", default=os.environ.get("RAID_VMX", "vmware_vm_data/Ubuntu0/Ubuntu0.vmx"))
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--smoke", action="store_true", help="에이전트 없이 환경만 점검(키 불필요)")
    ap.add_argument("--out", default=str(HERE / "_results"))
    a = ap.parse_args()

    vmx = _resolve_vmx(a.vmx)
    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
    print(f"[selftest] vmx={_rel(vmx)}")

    if a.smoke:
        smoke(a.model, vmx, outdir); return

    results = []
    for i in range(1, a.trials + 1):
        try:
            results.append(trial(i, a.model, vmx, outdir))
        except Exception:
            traceback.print_exc()
            results.append({"trial": i, "status": "crashed"})

    ok = sum(1 for r in results if r.get("verdict") == "PASS")
    part = sum(1 for r in results if str(r.get("verdict", "")).startswith("PARTIAL"))
    print(f"\n=== 집계 === PASS={ok}/{len(results)}  PARTIAL={part}  "
          f"(PARTIAL = 파일·토큰은 되는데 네트워크만 막힘 → 도구는 정상)")
    (outdir / "aggregate.json").write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
