#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CUA 시나리오 실행 웹 UI.

표준 라이브러리만 쓴다(설치 단계를 0 으로 둔다). 동시 사용자 1명·VM 1대 전제.

  python3 webui/app.py --vmx vmware_vm_data/Ubuntu0/Ubuntu0.vmx

설계 원칙
  · 판정은 run_chain(코드)이 호스트측 파일로 한다. 이 서버는 **표시만** 한다.
  · 라이브 화면은 시행이 이미 저장하는 step_*.png 를 서브한다 → VM 에 부하·설치 0
    (FOCUS-MISDELIVERY 처럼 창 z-order 가 측정 대상인 시나리오에서는 게스트를
     건드리는 순간 측정이 망가진다).
  · 게스트 :5000 으로 일반 프록시를 열지 않는다 — 그 서버에는 명령 실행 엔드포인트가 있다.
"""
from __future__ import annotations
import ast, base64, hmac, json, os, re, shutil, subprocess, sys, threading, time, argparse, html, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # 이 UI 레포의 루트


def locate_osworld(explicit: Optional[str] = None) -> Path:
    """하네스(OSWorld 포크)의 위치를 찾는다.

    ★ 하네스는 보통 이 레포의 OSWorld/ 에 같이 들어있다. 시나리오는
      `security_scenarios/<이름>/` 에 두어야 하는데, run_chain.py 가 레포 루트를
      `Path(__file__).resolve().parents[2]` 로 자가탐색하기 때문이다. `.resolve()` 가
      심링크를 따라가므로 **실제 파일이 그 트리 안에 있어야** 한다 — 밖에 두고
      링크만 걸면 ROOT 가 엉뚱한 데를 가리켜 import 가 깨진다(실측 2026-10-04).

    우선순위: --osworld-root → $OSWORLD_ROOT → 레포 안 OSWorld/

    ★ 명시된 경로(플래그·환경변수)는 **폴백하지 않는다.** 틀렸으면 그대로 돌려주고
      호출자가 거부하게 한다. 예전엔 틀린 경로를 주면 조용히 형제 디렉터리의 다른
      포크를 잡았다 — 사용자는 A 를 재는 줄 알고 B 를 재게 된다. 로그는 정상으로
      보이고 숫자만 바뀌는, 이 저장소가 경고하는 바로 그 종류의 고장이다.
    """
    given = explicit or os.environ.get("OSWORLD_ROOT")
    if given:
        return Path(given).expanduser().resolve()
    c = ROOT / "OSWorld"                                   # 레포에 같이 들어있는 하네스
    return c.resolve() if (c / "security_scenarios").is_dir() else c


OSW = locate_osworld()
SCEN = OSW / "security_scenarios"


# ── 화면에 호스트 절대경로(=계정명)를 흘리지 않는다 ────────────────────────────
#  우리 코드는 상대경로로 찍지만, 파이썬 경고·트레이스백·하네스 내부 출력처럼
#  우리가 고칠 수 없는 자리도 절대경로를 뱉는다. 그래서 "보여 주기 직전"에 한 번 더
#  지운다. 로그 파일 원본은 그대로 둔다(디버깅은 절대경로가 있어야 한다).
def _build_scrub():
    pats = []
    for base, repl in ((OSW, "OSWorld/"), (ROOT, "./")):       # 긴 것(OSW) 먼저
        try:
            b = str(Path(base).resolve())
        except Exception:                                      # noqa: BLE001
            continue
        if len(b) > 3:
            pats.append((re.compile(re.escape(b) + r"[/\\]?"), repl))
    pats.append((re.compile(r"(?:/Users|/home)/[^/\s:'\"]+/"), "~/"))
    #  치환문자열이 역슬래시로 끝나면 re.sub 가 escape 로 읽다가 터진다 → 함수로 준다.
    pats.append((re.compile(r"[A-Za-z]:\\Users\\[^\\\s:'\"]+\\"), lambda m: "~\\"))
    return pats


_SCRUB = _build_scrub()


def scrub(text: str) -> str:
    """표시용 문자열에서 호스트 절대경로를 상대경로/~ 로 줄인다."""
    if not text:
        return text
    for rx, repl in _SCRUB:
        text = rx.sub(repl, text)
    return text


def load_env_files(*paths: Path) -> List[str]:
    """.env 를 직접 읽는다 (python-dotenv 의존 없이).

    ★ 왜 여기서 읽나: `load_dotenv()` 는 `run_cua.main()` 안에만 있고,
      시나리오의 run_chain.py 는 `Session` 을 직접 import 하므로 main() 을 거치지 않는다
      = **.env 가 아무도 로드하지 않는다**(실측 2026-10-04). webui 가 자식 프로세스의
      환경을 만드는 쪽이므로 여기서 채운다. 이미 설정된 변수는 덮지 않는다.
    """
    loaded = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:   # 셸에서 준 값이 우선
                os.environ[k] = v
                n += 1
        if n:
            loaded.append(f"{path} ({n})")
    return loaded
sys.path.insert(0, str(HERE))
import render as R                       # noqa: E402
import analyze as A                      # noqa: E402

MAX_TRIALS = 2                           # 비용 상한 — 시행 하나가 입력 토큰 수십만
FALLBACK_MODELS = {
    "haiku": {"model_id": "claude-haiku-4-5", "family": "claude",
              "arms": ["faithful", "controlled", "inject"]},
    "luna":  {"model_id": "gpt-5.6-luna",     "family": "gpt",
              "arms": ["neutral", "controlled", "inject"]},
    "kimi":  {"model_id": "kimi-k2.6",        "family": "kimi",
              "arms": ["neutral", "controlled", "inject"]},
}
# 임시 모델 표기 — 실행기의 resolve_model_key 가 받는 형식과 같아야 한다
ADHOC = re.compile(r"^(claude|gpt|kimi):\S+$")
_DUMP = ("import json;from mm_agents.adapters.agents import MODEL_SPECS;"
         "print(json.dumps({k:{'model_id':v['model_id'],'family':v.get('family',''),"
         "'arms':list(v.get('arms',())),"
         "'native':sorted(v.get('native',())),'emulable':sorted(v.get('emulable',()))}"
         " for k,v in MODEL_SPECS.items()},ensure_ascii=False))")


DEPS_HINT = ""


def find_python() -> Optional[Path]:
    """하네스를 돌릴 파이썬. **절대 만들지 않는다 — 있는 것만 찾는다.**

    ★ 예전엔 폴백으로 `uv run` 을 불렀다. 그런데 uv 는 환경이 없으면 **만든다**
      (`--no-sync` 를 줘도 venv 자체는 생성한다). 그 결과 웹 UI 를 띄우기만 해도
      하네스 트리에 빈 .venv 가 생기고, 이미 있던 venv 를 덮어쓴다 — 실측으로
      멀쩡하던 작업 환경 하나를 이렇게 날렸다. 그래서 uv 는 부르지 않는다.
    """
    env = os.environ.get("RAID_PYTHON")
    cands = [Path(env).expanduser()] if env else []
    # venv 의 인터프리터 위치는 OS 마다 다르다 — POSIX 는 bin/python,
    # 윈도우는 Scripts/python.exe. 하네스는 Windows/Linux/Darwin 을 모두 다루므로
    # 여기서 한쪽만 보면 이 UI 때문에 윈도우에서 못 돈다.
    for vd in (".venv", ".venv.uvpy"):
        cands += [OSW / vd / "bin" / "python",
                  OSW / vd / "Scripts" / "python.exe"]
    for c in cands:
        try:
            if c.is_file() and os.access(c, os.X_OK):
                return c
        except OSError:
            pass
    return None


def discover_models() -> Dict[str, Any]:
    """MODEL_SPECS 를 단일 출처로 읽는다 → 표에 sonnet/opus 를 추가하면 버튼이 자동 생김.

    ★ 의존성이 깔려 있을 때만 시도한다. 예전엔 `uv run` 을 무조건 불렀는데, 그러면
      **웹 UI 를 띄우는 것만으로 하네스 가상환경을 새로 만들고 의존성을 설치한다**
      (실측: 레포 안에 .venv 가 조용히 생김). 클론한 사람은 버튼을 누르기도 전에
      몇 분짜리 설치가 말없이 도는 셈이라, 깔려 있지 않으면 기본값을 쓰고 알린다.
    """
    global DEPS_HINT
    py = find_python()
    if py is None:
        DEPS_HINT = (f"하네스 파이썬을 못 찾음 — 모델 목록은 기본값입니다.\n"
                     f"           찾아본 곳: {OSW}/.venv/(bin/python | Scripts/python.exe) 및 .venv.uvpy\n"
                     f"           RAID_PYTHON=<파이썬 경로> 로 지정하거나 "
                     f"`cd {OSW} && uv sync` 하십시오.")
        return FALLBACK_MODELS
    try:
        out = subprocess.run([str(py), "-c", _DUMP], cwd=OSW,
                             capture_output=True, text=True, timeout=90)
        line = [l for l in out.stdout.splitlines() if l.startswith("{")]
        if line:
            return json.loads(line[-1])
        err = (out.stderr or out.stdout or "").strip().splitlines()
        why = f"rc={out.returncode}: " + (" / ".join(err[-3:]) if err else "출력 없음")
    except Exception as exc:                                       # noqa: BLE001
        why = f"{type(exc).__name__}: {exc}"
    DEPS_HINT = f"MODEL_SPECS 를 읽지 못했습니다 — 모델 목록은 기본값.\n           {py}\n           {why}"
    return FALLBACK_MODELS


_FLAG = re.compile(r"""add_argument\(\s*["'](--[a-z0-9][a-z0-9-]*)["']""")
# ★ 공격 팔 이름은 시나리오마다 다르다. 하드코딩하면 두 번째 시나리오에 엉뚱한
#   --arm 값이 들어간다. 모듈 수준 `ARMS = (...)` 를 소스에서 읽는다.
_ARMS = re.compile(r"""^ARMS\s*=\s*[\(\[]([^)\]]*)[\)\]]""", re.M)
# ★ 팔이 무엇을 뜻하는지는 시나리오마다 다르다. 공격 조건(VULN/DEFENSE)인 것도 있고
#   기억·정책 조건, 후속 과업인 것도 있다. 고정 라벨을 쓰면 어딘가는 반드시 틀린다.
_ARMLBL = re.compile(r"""^ARMS_LABEL\s*=\s*["']([^"']+)["']""", re.M)
_STR = re.compile(r"""["']([^"']+)["']""")
# 시나리오 종류 — 목록을 묶는 데 쓴다. 소스에 `KIND = "probe"` 한 줄이면 되고,
# 없으면 폴더 모양으로 추정한다.
_KIND = re.compile(r"""^KIND\s*=\s*["']([a-z]+)["']""", re.M)
KIND_LABEL = {"chain": "풀체인", "probe": "단일 표면", "selftest": "점검"}
# 공통 축(지침 §3) → 칩에 붙일 한 단어. 조건 이름은 시나리오마다 다르지만 축은 같다.
_AXIS_WORD = {"VULN": "처치", "CONTROL": "대조", "VARIANT": "변형", "BASELINE": "기준선"}
_GMAP = re.compile(r"^GUIDE_ARM_MAP\s*=\s*(\{.*?\})", re.M | re.S)


def _decl(folder: Path) -> Dict[str, Any]:
    """단일 표면 시나리오의 판정 선언(task.json / probe.json). 없으면 빈 dict."""
    for name in ("task.json", "probe.json"):
        try:
            d = json.loads((folder / name).read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:                                              # noqa: BLE001
            continue
    return {}


def arm_axis(folder: Path, arms: List[str]) -> Dict[str, str]:
    """조건 칩에 붙일 축 꼬리표 {조건 이름: '처치'|'대조'|'변형'|'기준선'|'보조'}.

    ★ 사상은 `run_chain.py` 의 `GUIDE_ARM_MAP = {...}` 한 줄에서 읽는다(리터럴만, 실행하지 않음).
      단일 표면 시나리오는 판정 선언(task.json / probe.json)의 `guide_arm_map` 을 쓴다.
    ★ 사상이 없으면 **아무 꼬리표도 붙이지 않는다.** 처치/대조 축이 아닌 조건(예: 후속 과업
      두 종류를 조건으로 두는 시나리오)에 억지로 붙이면 틀린 표시가 된다.
    """
    gmap = None
    try:
        m = _GMAP.search((folder / "run_chain.py").read_text(encoding="utf-8"))
        gmap = ast.literal_eval(m.group(1)) if m else None
    except Exception:                      # 없거나 리터럴이 아니면 조용히 포기
        gmap = None
    if not gmap:                           # 단일 표면 시나리오는 판정 선언에 적는다
        gmap = _decl(folder).get("guide_arm_map")
    if not isinstance(gmap, dict) or not gmap:
        return {}
    out: Dict[str, str] = {}
    for a in arms:
        g = str(gmap.get(a) or "").upper()
        # 사상에 없는 조건 = 세 축 밖(집계기가 확률 표에서 제외하는 보조 조건)
        out[a] = _AXIS_WORD.get(g, g) if g else "보조"
    return out


def arm_label_ui(arm_label: str, found: bool) -> str:
    """조건 라벨을 '조건 — <축>' 한 형식으로 맞춘다 (시나리오 문구는 그대로 쓴다).

    시나리오가 준 문구 끝의 '조건' 은 떼고 붙인다 — "기억·정책 조건" → "조건 — 기억·정책".
    문구가 없으면 축을 모르므로 "조건" 만 쓴다(없는 설명을 지어내지 않는다).
    """
    if not found:
        return "조건"
    t = re.sub(r"\s*조건$", "", arm_label).strip()
    return f"조건 — {t}" if t else "조건"


def scenario_kind(rc: Path, src: Optional[str] = None) -> str:
    """풀체인 / 단일 표면 / 점검. 목록이 길어지면 이걸로 묶는다.

    ★ src 를 안 넘기면 여기서 읽는다. 빈 문자열을 넘기면 `KIND = "probe"` 선언을 못 찾아
      전부 풀체인으로 묶여 버린다(실측 — 설명 페이지에서 11개가 풀체인으로 나왔다).
    """
    if src is None:
        try:
            src = rc.read_text(encoding="utf-8")
        except OSError:
            src = ""
    m = _KIND.search(src)
    if m and m.group(1) in KIND_LABEL:
        return m.group(1)
    if rc.parent.name.upper().startswith("SELFTEST"):
        return "selftest"
    # 공용 드라이버가 읽는 판정 선언 파일이 있으면 단일 표면이다.
    if any((rc.parent / n).is_file() for n in ("probe.json", "task.json")):
        return "probe"
    return "chain"


# 팀 공격 표면 분류의 계층 순서. 시나리오가 적어 둔 계층을 이 순서로 묶는다.
_LAYERS = ("인식", "판단", "실행", "권한·승인", "환경", "기억")
_LAYER_ORDER = {name: i for i, name in enumerate(_LAYERS)}


_SURF_L = re.compile(r"""^SURFACE_LAYER\s*=\s*["']([^"']+)["']""", re.M)
_SURF_N = re.compile(r"""^SURFACE_NAME\s*=\s*["']([^"']+)["']""", re.M)


def scenario_surface(folder: Path) -> Dict[str, str]:
    """이 시나리오가 **어느 공격 표면을 노리는지**. 판정 선언 파일에 적어 둔 것을 읽는다.

    ★ 코드에 표를 박아 두지 않는다. 시나리오를 넣는 사람이 자기 폴더의
      `task.json`/`probe.json` 에 적으면 UI 가 알아서 제자리에 묶는다.

        "surface": { "layer": "환경", "name": "팝업/광고/오버레이" }
    """
    for name in ("task.json", "probe.json"):
        f = folder / name
        if not f.is_file():
            continue
        try:
            spec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                              # noqa: BLE001
            continue
        sur = spec.get("surface")
        if isinstance(sur, dict):
            return {"layer": str(sur.get("layer") or ""), "name": str(sur.get("name") or "")}
    # 풀체인처럼 판정 선언 파일이 없는 시나리오는 run_chain.py 의 상수에서 읽는다.
    try:
        src = (folder / "run_chain.py").read_text(encoding="utf-8")
    except OSError:
        return {"layer": "", "name": ""}
    ml, mn = _SURF_L.search(src), _SURF_N.search(src)
    return {"layer": ml.group(1) if ml else "", "name": mn.group(1) if mn else ""}


def scenario_summary(folder: Path) -> str:
    """목록에 붙일 한 줄. ABOUT.md 의 **한 줄.** 문단에서 가져온다 (없으면 빈 문자열)."""
    for name in ("ABOUT.md", "SCENARIO.md"):
        try:
            text = (folder / name).read_text(encoding="utf-8")
        except OSError:
            continue
        for para in text.split("\n\n"):
            p = " ".join(para.split())
            if p.startswith("**한 줄"):
                p = p.split(".", 1)[-1] if p.startswith("**한 줄.**") else p
                p = p.replace("**한 줄.**", "").replace("**", "").strip()
                return p[:160]
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "|", ">", "-", "*", "`")):
                return line.replace("**", "")[:160]
    return ""


_DRIVER = re.compile(r"^\s*from\s+([a-z_][a-z0-9_]*)\s+import\b", re.M)


def _driver_flags(rc: Path) -> List[str]:
    """run_chain.py 가 공용 드라이버를 부르는 경우, 플래그는 그 드라이버에 있다.

    ★ 폴더당 10줄짜리 run_chain.py 는 `from probe import run_probe` 처럼 옆 모듈에
      실행을 넘긴다. run_chain.py 만 긁으면 add_argument 가 하나도 안 나와서 UI 가
      "플래그형 CLI 가 아님" 으로 잘못 판단한다(실측). 같은 폴더(security_scenarios/)
      안의 모듈만 따라간다 — 바깥으로는 안 나간다.
    """
    out: List[str] = []
    try:
        src = rc.read_text(encoding="utf-8")
    except Exception:
        return out
    for mod in set(_DRIVER.findall(src)):
        cand = rc.parent.parent / f"{mod}.py"
        if cand.is_file():
            try:
                out += _FLAG.findall(cand.read_text(encoding="utf-8"))
            except Exception:
                pass
    return out


def scan_scenario(rc: Path) -> Dict[str, Any]:
    """시나리오의 run_chain.py 에서 **실제로 받는 플래그**를 읽는다.

    ★ 시나리오마다 CLI 가 다르다 — 위치 인자(`<arm> <model> <N>`)를 받는 실행기도 있고
      플래그를 받는 실행기도 있다. 가정하고 실행하면 엉뚱한 자리에 값이 꽂혀
      ValueError 가 난다(실측 2026-10-04). 그래서 소스에서 읽어 UI 를 맞춘다.
    """
    try:
        flags = sorted(set(_FLAG.findall(rc.read_text(encoding="utf-8")) + _driver_flags(rc)))
    except Exception:
        flags = []
    try:
        src = rc.read_text(encoding="utf-8")
        m = _ARMS.search(src)
        arms = _STR.findall(m.group(1)) if m else []
        ml = _ARMLBL.search(src)
        arm_label = ml.group(1) if ml else "실행 조건"
        label_ui = arm_label_ui(arm_label, ml is not None)
        kind = scenario_kind(rc, src)
    except Exception:
        arms, arm_label, label_ui, kind = [], "실행 조건", "조건", "chain"
    # ★ 보조 서버 — 시나리오에 serve.py 가 있으면 UI 가 같이 띄운다.
    #   MEM-FALSEFAIL 처럼 호스트 서버(세계 서버·수집기)가 필요한 시나리오는, 그게 안 떠 있으면
    #   run_chain 이 그냥 죽는다. 웹에서 누른 사람에게는 영문 모를 실패로 보인다.
    helper = "serve.py" if (rc.parent / "serve.py").is_file() else ""
    need = {"--model", "--trials"}
    runnable = need.issubset(flags)
    # ★ 모델 경로마다 줄 수 있는 도구가 다르다(MCP·editor 는 claude 경로만). 정책 프롬프트를
    #   얹는 조건도 claude 경로만 받는다. 판정 선언에서 요구 사항만 넘기고, 막을지는 화면이
    #   모델 표(native/emulable)를 보고 정한다 — 실행기도 같은 이유로 VM 전에 거부한다.
    decl = _decl(rc.parent)
    needs_tools = [t for t in (decl.get("tools") or []) if t != "computer"]
    aopt = decl.get("arm_options") or {}
    policy_arms = (["*"] if decl.get("system_prompt_file") else
                   [a for a, o in aopt.items() if isinstance(o, dict) and o.get("system_prompt_file")])
    return {"name": rc.parent.name, "flags": flags, "arms": arms,
            "arm_label": arm_label, "helper": helper,
            # 조건 이름은 시나리오의 것을 그대로 쓰고(--arm 으로 그 값이 간다),
            # 표시만 공통 축으로 맞춘다 — 어느 칩이 처치군인지 UI 에서 보이게.
            "arm_axis": arm_axis(rc.parent, arms),
            "arm_label_ui": label_ui,
            "kind": kind, "kind_label": KIND_LABEL.get(kind, kind),
        "surface": scenario_surface(rc.parent),
            "summary": scenario_summary(rc.parent),
            "needs_tools": needs_tools, "policy_arms": policy_arms,
            "runnable": runnable,
            "why": "" if runnable else "이 UI 는 플래그형 CLI(--model/--trials)만 지원 — "
                                       "위치 인자형 시나리오는 터미널에서 실행"}


_KIND_ORDER = {"chain": 0, "probe": 1, "selftest": 2}


def _card_sort(d: Dict[str, Any]):
    """종류 → 공격 표면 계층 → 이름. 계층을 안 적은 시나리오는 그 종류의 끝으로."""
    layer = (d.get("surface") or {}).get("layer", "")
    return (_KIND_ORDER.get(d.get("kind", ""), 9), _LAYER_ORDER.get(layer, 99), d.get("name", ""))


def discover_scenarios() -> List[Dict[str, Any]]:
    # ★ `_` 로 시작하는 폴더는 건너뛴다 — `_TEMPLATE` 같은 틀은 시나리오가 아니다.
    got = [scan_scenario(p) for p in SCEN.glob("*/run_chain.py")
           if not p.parent.name.startswith("_")]
    return sorted(got, key=lambda d: (not d["runnable"], *_card_sort(d)))


class Helper:
    """시나리오의 보조 서버(serve.py)를 자식 프로세스로 띄우고 로그를 남긴다.

    ★ 게스트가 호스트의 이 포트로 접속해야 하므로 serve.py 는 0.0.0.0 에 붙는다.
      터널(cloudflared)로 내보내는 것은 웹 UI 포트뿐이고 이 포트는 절대 내보내지
      않는다 — 수집 엔드포인트가 그대로 열린다.
    """
    def __init__(self, scenario: str, script: Path, port: int = 8000):
        self.scenario, self.script, self.port = scenario, script, port
        self.log = HERE / "_logs" / f"helper-{scenario}.log"
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.proc: Optional[subprocess.Popen] = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> Dict[str, Any]:
        if self.running():
            return {"ok": True, "already": True, "pid": self.proc.pid}
        py = find_python() or Path(sys.executable)
        env = dict(os.environ, PORT=str(self.port))
        fh = open(self.log, "w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen(
                [str(py), str(self.script)], cwd=str(self.script.parent),
                stdout=fh, stderr=subprocess.STDOUT, env=env)
        except Exception as exc:                                   # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        time.sleep(1.2)                       # 포트 점유 실패를 바로 잡아내기 위해
        if not self.running():
            return {"ok": False, "error": self.tail(6) or "즉시 종료됨"}
        return {"ok": True, "pid": self.proc.pid, "port": self.port}

    def stop(self) -> Dict[str, Any]:
        if not self.running():
            return {"ok": True, "already": True}
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:                                          # noqa: BLE001
            self.proc.kill()
        return {"ok": True}

    def tail(self, n: int = 40) -> str:
        try:
            return scrub("\n".join(self.log.read_text(encoding="utf-8",
                                                      errors="replace").splitlines()[-n:]))
        except OSError:
            return ""


class Job:
    def __init__(self, scenario: str, model: str, arm: str, trials: int,
                 read_mode: str, phase1_only: bool, vmx: str, smoke: bool,
                 flags: Optional[List[str]] = None):
        flags = set(flags or [])
        self.id = time.strftime("%Y%m%d-%H%M%S")
        self.scenario, self.model, self.arm = scenario, model, arm
        self.trials, self.read_mode = trials, read_mode
        self.results = SCEN / scenario / "_results"
        self.log = HERE / "_logs" / f"{self.id}.log"
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.proc: Optional[subprocess.Popen] = None
        self.started = time.time()
        self.finished: Optional[float] = None
        # ★ 요약은 **사용자 API 키로 과금되는 호출**이다. 한 실행에 한 번만 부른다.
        #   브라우저 쪽 플래그로만 막으면 **새로고침 한 번에 다시 과금된다**(실측).
        #   탭을 여러 개 열어도, 다른 기기에서 접속해도 마찬가지다. 그래서 서버가 들고 있는다.
        self.digest: Optional[Dict[str, Any]] = None
        self.digest_lock = threading.Lock()
        py = find_python()
        if py is None:                       # uv 로 폴백하지 않는다(환경을 만들어버린다)
            raise RuntimeError(
                f"하네스 파이썬을 못 찾음 — {OSW}/.venv (bin/python 또는 Scripts/python.exe), "
                f"아니면 RAID_PYTHON 을 지정하십시오.")
        head = [str(py)]
        argv = head + [f"security_scenarios/{scenario}/run_chain.py"]
        # ★ 시나리오가 실제로 받는 플래그만 넣는다(없는 플래그를 주면 위치 인자로 먹힌다)
        def add(flag, *vals):
            if flag in flags:
                argv.append(flag); argv.extend(str(v) for v in vals)
        add("--vmx", vmx)
        add("--model", model)
        add("--trials", trials)
        if smoke:
            add("--smoke")
        else:
            add("--arm", arm)
            if phase1_only:
                add("--phase1-only")
            if read_mode:
                add("--read-mode", read_mode)
        self.argv = argv

    def start(self):
        # (메모리 팔은 위 argv 조립에서 --read-mode 로 전달된다. 시나리오가 그
        #  플래그를 선언한 경우에만 붙는다.)
        env = dict(os.environ, PYTHONPATH=".", PYTHONUNBUFFERED="1")
        self.fh = open(self.log, "wb")
        self.proc = subprocess.Popen(self.argv, cwd=OSW, env=env,
                                     stdout=self.fh, stderr=subprocess.STDOUT)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def latest_frame(self) -> Optional[Path]:
        pats = [f"{self.model}/*/t*/p?/step_*.png", "_smoke/p?/step_*.png"]
        best, bt = None, -1.0
        for pat in pats:
            for p in self.results.glob(pat):
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if m > bt and m >= self.started - 5:
                    best, bt = p, m
        return best

    def tail(self, n: int = 40) -> str:
        try:
            lines = self.log.read_bytes().decode("utf-8", "replace").splitlines()
        except Exception:
            return ""
        return scrub("\n".join(lines[-n:]))

    def state(self) -> Dict[str, Any]:
        rc = None if self.alive() else (self.proc.returncode if self.proc else None)
        if rc is not None and self.finished is None:
            self.finished = time.time()
        f = self.latest_frame()
        return {"id": self.id, "scenario": self.scenario, "model": self.model,
                "arm": self.arm, "trials": self.trials, "running": self.alive(),
                "rc": rc, "elapsed": round((self.finished or time.time()) - self.started),
                "frame": f.name if f else None, "log": self.tail(),
                "cmd": scrub(" ".join(self.argv))}



def guide_docs() -> Dict[str, Any]:
    """설명 페이지가 보여 줄 마크다운을 모은다.

    ★ 시나리오 설명은 **그 폴더 안의 파일**이다 — `ABOUT.md`(소개), 없으면 `SCENARIO.md`(실행 방법).
      시나리오를 추가한 사람이 코드를 고치지 않아도 설명이 웹에 뜬다.
    """
    def _read(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8")[:200_000]
        except OSError:
            return ""

    out: Dict[str, Any] = {"common": "", "common_src": "", "scenarios": []}
    g = ROOT / "docs" / "GUIDE.md"
    out["common"] = _read(g) or "# 안내\n\n`docs/GUIDE.md` 가 없습니다."
    out["common_src"] = str(g.relative_to(ROOT)) if g.is_file() else ""
    # 루트 페이지와 **같은 순서·같은 분류**로 둔다. 한쪽만 알파벳순이면 같은 시나리오를
    # 두 화면에서 다른 자리에서 찾게 된다. _TEMPLATE 처럼 _ 로 시작하는 폴더는 시나리오가 아니다.
    cards = [rc for rc in sorted(SCEN.glob("*/run_chain.py")) if not rc.parent.name.startswith("_")]
    cards.sort(key=lambda rc: _card_sort({"kind": scenario_kind(rc), "name": rc.parent.name,
                                          "surface": scenario_surface(rc.parent)}))
    for rc in cards:
        d = rc.parent
        kind = scenario_kind(rc)
        meta = {"name": d.name, "kind": kind, "kind_label": KIND_LABEL.get(kind, kind),
                "surface": scenario_surface(d)}
        for name in ("ABOUT.md", "SCENARIO.md", "README.md"):
            md = _read(d / name)
            if md:
                out["scenarios"].append({**meta, "md": md,
                                         "src": f"OSWorld/security_scenarios/{d.name}/{name}"})
                break
        else:
            out["scenarios"].append({
                **meta, "src": "",
                "md": f"# {d.name}\n\n설명 파일이 없습니다 — 그 폴더에 `ABOUT.md` 를 두면 여기에 나옵니다."})
    return out


class State:
    def __init__(self, vmx: str):
        self.vmx = vmx
        self.lock = threading.Lock()
        self.job: Optional[Job] = None
        self.models = discover_models()
        self.scenarios = discover_scenarios()
        self.helpers: Dict[str, Helper] = {}
        self.runs = 0

    def helper_for(self, scenario: str) -> Optional[Helper]:
        spec = next((d for d in self.scenarios if d["name"] == scenario), None)
        if not spec or not spec.get("helper"):
            return None
        h = self.helpers.get(scenario)
        if h is None:
            h = Helper(scenario, SCEN / scenario / spec["helper"])
            self.helpers[scenario] = h
        return h

    def submit(self, **kw) -> Dict[str, Any]:
        with self.lock:
            if self.job is not None and self.job.alive():
                return {"error": "이미 실행 중입니다 (VM 1대 — 동시 실행 불가)",
                        "busy": True}
            kw["trials"] = max(1, min(MAX_TRIALS, int(kw.get("trials") or 1)))
            # 보조 서버가 필요한 시나리오면 **실행 전에** 띄운다. 안 떠 있으면
            # run_chain 이 그냥 죽고, 웹에서는 영문 모를 실패로 보인다.
            h = self.helper_for(str(kw.get("scenario") or ""))
            if h is not None and not h.running():
                r = h.start()
                if not r.get("ok"):
                    return {"error": f"보조 서버({h.script.name}) 기동 실패 — {r.get('error')}"}
            self.job = Job(vmx=self.vmx, **kw)
            self.job.start()
            self.runs += 1
            if h is not None:
                self._watch_and_stop(self.job, h)
            return self.job.state()

    def _watch_and_stop(self, job: "Job", helper: Helper) -> None:
        """실행이 끝나면 보조 서버를 내린다.

        ★ 폴링(브라우저)에 기대지 않고 서버측 스레드로 한다 — 탭을 닫아도 포트가
          물려 있으면 다음 실행이 '포트 점유' 로 죽는다.
        ★ 분석기는 로그 **파일**을 읽으므로, 프로세스를 내려도 결과칸에는 영향이 없다.
        """
        def _wait():
            try:
                if job.proc is not None:
                    job.proc.wait()
            except Exception:                                      # noqa: BLE001
                pass
            # 사용자가 그 사이 새 실행을 시작했으면 건드리지 않는다
            if self.job is job and helper.running():
                helper.stop()
        threading.Thread(target=_wait, daemon=True).start()

    def kill(self) -> Dict[str, Any]:
        with self.lock:
            if self.job and self.job.alive():
                self.job.proc.terminate()
                return {"killed": True}
            return {"killed": False}



# ── 마크다운 렌더러 (실행 화면의 요약, 설명 페이지 둘 다 쓴다) ──────────────
#   의존성 0. 표·제목·목록·인라인 코드만 — 설명 문서에 필요한 만큼.
MD_JS = r"""const NL=String.fromCharCode(10);
/* 목록에서 묶는 이름. 단일 표면은 **공격 표면 계층**까지 내려서 묶는다 —
   "이 시나리오가 어느 표면을 노리는가"가 목록에서 바로 보이게. */
function grpLabel(kindLabel, surface){
  const L=(surface||{}).layer||"";
  return (kindLabel==="단일 표면" && L) ? (kindLabel+" · "+L) : (kindLabel||"시나리오");
}
/* ── 공용 고르기 컨트롤 ────────────────────────────────────────────────────
   ★ 목록을 탭이나 칩으로 늘어놓으면 **개수에 비례해 세로를 먹는다.** 시나리오가
     쉰 개가 되면 첫 화면이 이름 벽이 되고 정작 읽을 것이 화면 밖으로 밀린다.
     그래서 평소에는 고른 것 한 줄만 두고, 펼칠 때만 전부 보여 준다. 세로 비용이
     개수와 무관하게 **한 줄로 고정**된다. 안쪽에 스크롤을 두지 않으므로
     스크롤바는 페이지 하나로 끝난다.
   opt = {host, pick, box, find, rows, count, items(), group(d), title(d),
          badges(d), isCur(d), onPick(d), minFind} */
function makePicker(opt){
  const $=i=>document.getElementById(i);
  const st={open:false, filter:""};
  function head(){
    const d=opt.items().find(x=>opt.isCur(x));
    const bg=(opt.badges? opt.badges(d||{}) : []).map(x=>'<span class="bg">'+esc(x)+"</span>").join("");
    $(opt.pick).innerHTML='<span class="nm">'+esc(d?opt.title(d):"(없음)")+bg+"</span>"
                        + '<span class="chev">\u25bc</span>';
    $(opt.pick).setAttribute("aria-expanded", String(st.open));
    $(opt.box).style.display = st.open ? "" : "none";
    if(opt.count) $(opt.count).textContent = st.open ? "" : "("+opt.items().length+"개 중)";
  }
  function list(){
    const el=$(opt.rows); el.innerHTML="";
    const q=st.filter.trim().toLowerCase();
    const hit=opt.items().filter(d=>!q ||
      (opt.title(d)+" "+(opt.group(d)||"")).toLowerCase().includes(q));
    if(!hit.length){ el.innerHTML='<div class="none">걸린 항목이 없습니다.</div>'; return; }
    let g="";
    hit.forEach(d=>{
      const gg=opt.group(d)||"";
      if(gg!==g){ g=gg; const h=document.createElement("h4"); h.textContent=g; el.appendChild(h); }
      const b=document.createElement("button");
      b.className="opt"; b.setAttribute("aria-pressed", String(!!opt.isCur(d)));
      b.innerHTML='<span class="nm">'+esc(opt.title(d))+"</span>"
                + (opt.badges? opt.badges(d).map(x=>'<span class="bg">'+esc(x)+"</span>").join("") : "");
      b.onclick=()=>{ opt.onPick(d); api.close(); };
      el.appendChild(b);
    });
  }
  const api={
    paint(){ head(); if(st.open) list();
             if(opt.find) $(opt.find).style.display =
               opt.items().length > (opt.minFind||6) ? "" : "none"; },
    close(){ st.open=false; st.filter=""; if(opt.find) $(opt.find).value=""; api.paint();
             $(opt.pick).scrollIntoView({block:"nearest"}); },
  };
  $(opt.pick).onclick=()=>{ if(st.open){ api.close(); return; }
    st.open=true; api.paint();
    if(opt.find){ const f=$(opt.find); if(f.style.display!=="none") f.focus(); } };
  if(opt.find) $(opt.find).oninput=e=>{ st.filter=e.target.value; list(); };
  document.addEventListener("keydown",e=>{ if(e.key==="Escape" && st.open) api.close(); });
  return api;
}
function esc(t){return String(t).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function inl(t){                       // 이미 이스케이프된 텍스트에만 적용
  return t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function(m,txt,url){
            return /^https?:/.test(url) ? '<a href="'+url+'" target="_blank" rel="noopener">'+txt+"</a>"
                                        : (txt===url ? "<code>"+url+"</code>"
                                                     : txt+' <code>'+url+"</code>"); })
          .replace(/`([^`]+)`/g,"<code>$1</code>")
          .replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>")
          .replace(/^(통과|실패|확인불가|불일치)$/,'<span class="v-$1">$1</span>');
}
function cells(l){return l.trim().replace(/^\||\|$/g,"").split("|").map(c=>c.trim());}
function md(src){
  const L=esc(src).split(NL), out=[]; let i=0, buf=[];
  const flush=()=>{ if(buf.length){ out.push("<p>"+inl(buf.join(" "))+"</p>"); buf=[]; } };
  while(i<L.length){
    const l=L[i];
    if(/^\s*\|/.test(l) && i+1<L.length && /^\s*\|[\s:|-]+\|?\s*$/.test(L[i+1])){
      flush();
      const head=cells(l); i+=2; const rows=[];
      while(i<L.length && /^\s*\|/.test(L[i])){ rows.push(cells(L[i])); i++; }
      out.push("<table><thead><tr>"+head.map(c=>"<th>"+inl(c)+"</th>").join("")+"</tr></thead><tbody>"
        +rows.map(r=>"<tr>"+r.map(c=>"<td>"+inl(c)+"</td>").join("")+"</tr>").join("")+"</tbody></table>");
      continue;
    }
    let m=l.match(/^(#{1,4})\s+(.*)$/);
    if(m){ flush(); const h="h"+m[1].length; out.push("<"+h+">"+inl(m[2])+"</"+h+">"); i++; continue; }
    if(/^\s*\d+\.\s+/.test(l)){
      flush(); const nums=[];
      while(i<L.length && /^\s*\d+\.\s+/.test(L[i])){ nums.push("<li>"+inl(L[i].replace(/^\s*\d+\.\s+/,""))+"</li>"); i++; }
      out.push("<ol>"+nums.join("")+"</ol>"); continue;
    }
    if(/^\s*[-*]\s+/.test(l)){
      flush(); const items=[];
      while(i<L.length && /^\s*[-*]\s+/.test(L[i])){ items.push("<li>"+inl(L[i].replace(/^\s*[-*]\s+/,""))+"</li>"); i++; }
      out.push("<ul>"+items.join("")+"</ul>"); continue;
    }
    if(/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(l)){ flush(); i++; continue; }   // 구분선은 버린다(소제목으로 충분)
    if(!l.trim()){ flush(); i++; continue; }
    buf.push(l); i++;
  }
  flush();
  return out.join("");
}
"""

GUIDE_PAGE = """<!doctype html><meta charset="utf-8"><title>시나리오 설명 — CUA 시나리오 실행기</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
:root{--bg:#f7f7f5;--card:#fff;--line:#e4e7ec;--line2:#d6dbe3;--ink:#111827;--ink2:#475569;
 --ink3:#6b7280;--ink4:#9aa4b2;--accent:#1d4ed8}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14.5px/1.75 'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',system-ui,sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:22px 18px 72px}
.top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
 padding-bottom:14px;margin-bottom:16px;border-bottom:1px solid var(--line)}
h1{font-size:21px;margin:0;font-weight:700;letter-spacing:-.2px}
.sub{color:var(--ink3);font-size:12.5px;margin:0;flex:1 1 260px}
a.btn{font-size:12px;color:var(--accent);text-decoration:none;border:1px solid #c7d2fe;
 background:#eef2ff;border-radius:8px;padding:4px 10px;white-space:nowrap}
a.btn:hover{background:#e0e7ff}
/* ★ 문서 고르기 — 탭을 쓰지 않는다. 탭은 개수만큼 세로를 먹어서, DB 가 커지면
   첫 화면이 이름 벽이 되고 정작 읽을 글이 화면 밖으로 밀린다(실측 14개에서 네 줄).
   루트 페이지와 **같은 컨트롤**(/ui.js 의 makePicker)을 써서 한 줄로 고정한다. */
.plabel{display:block;font-size:12px;color:var(--ink2);margin:0 0 6px;font-weight:600}
.pick{display:flex;align-items:center;gap:8px;width:100%;border:1px solid var(--line2);
 border-radius:10px;background:#fff;padding:9px 12px;cursor:pointer;text-align:left;
 font:inherit;color:var(--ink)}
.pick:hover{background:#f8fafc}
.pick:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.pick[aria-expanded=true]{border-color:var(--ink3);background:#f8fafc}
.pick .nm{font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px;
 flex-wrap:wrap;min-width:0}
.pick .chev{margin-left:auto;flex:0 0 auto;font-size:10px;color:var(--ink3);
 transition:transform .12s ease}
.pick[aria-expanded=true] .chev{transform:rotate(180deg)}
.picker{border:1px solid var(--line);border-radius:10px;padding:8px;background:#fcfcfd;margin-top:8px}
.picker h4{font-size:10.5px;letter-spacing:.4px;color:var(--ink4);margin:10px 0 5px;font-weight:700}
.picker h4:first-child{margin-top:0}
.picker .opt{width:100%;text-align:left;display:flex;align-items:center;gap:5px;flex-wrap:wrap;
 margin-bottom:4px;padding:7px 10px;border:1px solid var(--line2);background:#fff;
 border-radius:8px;cursor:pointer;font:inherit;color:var(--ink)}
.picker .opt:hover{background:#f1f5f9}
.picker .opt[aria-pressed=true]{background:var(--ink);color:#fff;border-color:var(--ink)}
.picker .opt:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.picker .nm{font-weight:700;font-size:12.5px;flex:0 0 auto}
.picker .bg{font-size:10px;border:1px solid var(--line2);border-radius:999px;padding:0 6px;
 color:var(--ink3);font-weight:600;flex:0 0 auto}
.picker .opt[aria-pressed=true] .bg{border-color:#4b5563;color:#c7cdd6}
.picker .none{font-size:11.5px;color:var(--ink4);padding:6px 2px}
.find{width:100%;border:1px solid var(--line2);border-radius:8px;padding:7px 10px;
 font:inherit;font-size:12.5px;margin-bottom:8px;background:#fff;color:var(--ink)}
.find::placeholder{color:var(--ink4)}
.sheet{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:14px;
 padding:26px 30px 32px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.doc h1{font-size:20px;margin:0 0 16px;padding-bottom:10px;border-bottom:1px solid var(--line);
 letter-spacing:-.2px}
.doc h2{font-size:15.5px;margin:30px 0 10px;padding-left:10px;border-left:3px solid var(--ink);
 line-height:1.35}
.doc h3{font-size:13.5px;margin:20px 0 6px;color:var(--ink2)}
.doc h4{font-size:12.5px;margin:16px 0 6px;color:var(--ink3)}
.doc h2:first-child,.doc h1:first-child{margin-top:0}
.doc p{margin:0 0 12px}
.doc ul,.doc ol{margin:0 0 14px;padding-left:22px}.doc li{margin:5px 0}
.doc table{width:100%;border-collapse:collapse;margin:10px 0 16px;font-size:13px}
.doc th,.doc td{border:1px solid var(--line2);padding:7px 10px;text-align:left;vertical-align:top}
.doc th{background:#f6f7f9;color:var(--ink2);font-weight:600}
.doc code{background:#f1f5f9;border-radius:5px;padding:1px 5px;font-size:12.5px;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.doc b{font-weight:700}
.doc a{color:var(--accent)}
.foot{font-size:11.5px;color:var(--ink4);margin-top:14px}
@media(max-width:560px){.sheet{padding:20px 18px 26px}.wrap{padding:18px 12px 56px}}
</style>
<div class="wrap">
<div class="top">
 <h1>시나리오 설명</h1>
 <p class="sub">이 도구가 무엇인지, 옵션이 뭘 뜻하는지, 각 시나리오가 무엇을 재는지.</p>
 <a class="btn" href="/">← 실행기로</a>
</div>
<label class="plabel">문서 <span id="dcount" style="color:var(--ink4);font-weight:400"></span></label>
<button class="pick" id="pick" aria-expanded="false"></button>
<div class="picker" id="o-pick" style="display:none">
 <input id="find" class="find" placeholder="검색" autocomplete="off">
 <div id="rows"></div>
</div>
<div class="sheet"><div class="doc" id="doc">불러오는 중…</div>
 <p class="foot" id="foot"></p></div>
</div>
<script src="/ui.js"></script>
<script>
const $=i=>document.getElementById(i);
let DOCS=[], cur=0, picker=null;
function draw(){
  $("doc").innerHTML = md(DOCS[cur].md);
  $("foot").textContent = DOCS[cur].src ? ("출처: " + DOCS[cur].src) : "";
}
fetch("/api/guide").then(r=>r.json()).then(d=>{
  DOCS=[{title:"이 도구와 옵션", md:d.common, src:d.common_src, group:"안내"}]
       .concat(d.scenarios.map(s=>({title:s.name, md:s.md, src:s.src,
                                    surface:s.surface||{},
                                    group:grpLabel(s.kind_label, s.surface)})));
  picker = makePicker({
    pick:"pick", box:"o-pick", find:"find", rows:"rows", count:"dcount",
    items:()=>DOCS, group:d=>d.group, title:d=>d.title,
    badges:d=>((d.surface||{}).name ? [d.surface.name]
               : (d.group && d.group!=="안내" ? [d.group] : [])),
    isCur:d=>DOCS.indexOf(d)===cur,
    onPick:d=>{ cur=DOCS.indexOf(d); draw(); window.scrollTo({top:0,behavior:"smooth"}); },
  });
  picker.paint(); draw();
}).catch(e=>{ $("doc").textContent="설명을 불러오지 못했습니다: "+e; });
</script>"""

PAGE = """<!doctype html><meta charset="utf-8"><title>CUA 시나리오 실행기</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
:root{
 --bg:#f7f7f5; --card:#fff; --line:#e4e7ec; --line2:#d6dbe3;
 --ink:#111827; --ink2:#475569; --ink3:#6b7280; --ink4:#9aa4b2;
 --dark:#0b0e14; --run:#b42318; --run2:#981b12; --accent:#1d4ed8;
}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.6 'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',system-ui,sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto;padding:22px 18px 64px}

/* ── 머리 ─────────────────────────────────────────────── */
.top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
 padding-bottom:14px;margin-bottom:18px;border-bottom:1px solid var(--line)}
h1{font-size:21px;letter-spacing:-.2px;margin:0;font-weight:700}
.ver{font-size:11px;color:var(--ink4);border:1px solid var(--line2);border-radius:999px;padding:1px 8px}
.sub{color:var(--ink3);font-size:12.5px;margin:0;flex:1 1 320px;min-width:0}

/* ── 레이아웃 ──────────────────────────────────────────── */
.grid{display:grid;grid-template-columns:352px minmax(0,1fr);gap:18px;align-items:start}
/* ★ 그리드의 1fr 칼럼은 **내용의 고유 너비 아래로 줄지 않는다.** 결과칸에 표를
   넣은 뒤로 그 표가 칼럼을 밀어내 페이지가 넘치고 VM 화면까지 늘어났다(실측).
   minmax(0,1fr) + 자식 min-width:0 이 표준 해법. */
.grid > *{min-width:0}
/* .col-l 에 top sticky 를 걸지 않는다 — 칼럼이 뷰포트보다 길면 아무 효과도 없다. */
@media(max-width:900px){.grid{grid-template-columns:1fr}}

/* ── 카드 ─────────────────────────────────────────────── */
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:16px 18px 18px;margin-bottom:16px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card:last-child{margin-bottom:0}
.card-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:-2px 0 12px}
.card-h h2{font-size:12px;letter-spacing:.3px;text-transform:uppercase;
 color:var(--ink2);margin:0;font-weight:700}
.card-h .spacer{flex:1}
.meta{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--ink3)}
.meta b{font-weight:600;color:var(--ink2)}

/* ── 옵션 ─────────────────────────────────────────────── */
label{display:block;font-size:12px;color:var(--ink2);margin:14px 0 6px;font-weight:600}
/* 칩은 더 이상 흘려 쓰지 않는다 — 이름 길이가 제각각이라 줄바꿈이 들쭉날쭉해진다.
   짧은 선택지는 같은 너비의 격자, 긴 선택지(조건·시나리오)는 한 줄에 하나씩. */
.opts{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:6px}
.opts.rows{grid-template-columns:1fr}
.opts.two{grid-template-columns:repeat(2,minmax(0,1fr))}
.opt{border:1px solid var(--line2);background:#fff;border-radius:8px;padding:7px 10px;
 font-size:12.5px;line-height:1.35;color:var(--ink);cursor:pointer;user-select:none;
 text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
 transition:background .12s,border-color .12s,color .12s}
.opts.rows .opt{text-align:left;display:flex;align-items:center;gap:8px;white-space:normal}
.opt .tag{margin-left:auto;font-size:11px;color:var(--ink3);flex:0 0 auto}
.opt[aria-pressed=true] .tag{color:#c7cdd6}
.opt .sub{font-size:11px;color:var(--ink3);display:block}
.opt[aria-pressed=true] .sub{color:#c7cdd6}

/* 시나리오 목록 — 개수가 늘어도 읽히게 묶고 걸러 본다 */
.find{width:100%;border:1px solid var(--line2);border-radius:8px;padding:7px 10px;
 font:inherit;font-size:12.5px;margin-bottom:8px;background:#fff;color:var(--ink)}
.find::placeholder{color:var(--ink4)}
/* ★ 여기에 내부 스크롤을 두지 않는다. 패널 안에 또 다른 뷰포트가 생기면 바깥 스크롤과
   엉켜 고르기 어려워진다. 평소에는 **선택된 한 줄**만 두고, 펼칠 때만 전부 보여 준다
   (펼친 목록은 페이지와 같이 흐른다 = 스크롤바는 하나). */
.pick{display:flex;align-items:center;gap:8px;width:100%;border:1px solid var(--line2);
 border-radius:10px;background:#fff;padding:9px 12px;cursor:pointer;text-align:left;
 font:inherit;color:var(--ink)}
.pick:hover{background:#f8fafc}
.pick:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.pick .nm{font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px;
 flex-wrap:wrap;min-width:0}
/* 토글 글리프 하나로 끝낸다 — 글자("바꾸기")는 버튼이 하나 더 있는 것처럼 읽힌다 */
.pick .chev{margin-left:auto;flex:0 0 auto;font-size:10px;color:var(--ink3);
 transition:transform .12s ease}
.pick[aria-expanded=true] .chev{transform:rotate(180deg)}
.pick[aria-expanded=true]{border-color:var(--ink3);background:#f8fafc}
.scen{border:1px solid var(--line);border-radius:10px;padding:8px;background:#fcfcfd;margin-top:8px}
.scen h4{font-size:10.5px;letter-spacing:.4px;color:var(--ink4);margin:10px 0 5px;font-weight:700}
.scen h4:first-child{margin-top:2px}
.scen h4{font-size:10.5px;letter-spacing:.4px;color:var(--ink4);margin:10px 0 5px;font-weight:700}
.scen h4:first-child{margin-top:0}
/* 이름 한 줄이면 충분하다 — 설명은 /guide 에 전문이 있고, 여기서 잘라 붙이면 "..." 만 남는다 */
/* ★ 이름은 절대 자르지 않는다 — 배지(공격 표면·조건 수)가 밀면 배지가 줄을 바꾼다.
   nowrap + ellipsis 로 두면 긴 이름이 "README-HANDO…" 가 돼 무엇인지 알 수 없다. */
.scen .opt{width:100%;text-align:left;display:flex;align-items:center;gap:5px;
 flex-wrap:wrap;margin-bottom:4px;padding:7px 10px}
.scen .find{margin-bottom:8px}
.scen .nm{font-weight:700;font-size:12.5px;flex:0 0 auto}
.scen .bg{font-size:10px;border:1px solid var(--line2);border-radius:999px;padding:0 6px;
 color:var(--ink3);font-weight:600;flex:0 0 auto}
.scen .opt[aria-pressed=true] .bg{border-color:#4b5563;color:#c7cdd6}
.scen .none{font-size:11.5px;color:var(--ink4);padding:6px 2px}
.opt:hover{background:#f1f5f9}
.opt[aria-pressed=true]{background:var(--ink);color:#fff;border-color:var(--ink)}
.opt:focus-visible,.run:focus-visible,.kill:focus-visible,summary:focus-visible{
 outline:2px solid var(--accent);outline-offset:2px}
.adv{margin-top:10px;border-top:1px dashed var(--line);padding-top:10px}
.adv summary{font-size:11.5px;color:var(--ink3);cursor:pointer;list-style:none}
.adv summary::-webkit-details-marker{display:none}
.adv summary::before{content:"+ ";color:var(--ink4)}
.adv[open] summary::before{content:"− "}
.adv .in{display:flex;gap:6px;margin:8px 0 2px}
.adv select,.adv input{border:1px solid var(--line2);border-radius:8px;padding:5px 8px;
 font:inherit;font-size:12.5px;background:#fff;color:var(--ink);min-width:0}
.adv input{flex:1}
/* ★ 실행 버튼은 옵션 **맨 위**, 카드 머리줄에 둔다. 아래에 두면 시나리오를 펼쳤을 때
   화면 밖으로 밀리고, 바닥에 고정하면 그 밑 글을 덮는다. 페이지는 항상 맨 위에서
   시작하므로 여기 있으면 어느 경우에도 스크롤 없이 닿는다. */
.sumline:empty{display:none}
.sumline{margin-top:10px;padding:8px 11px;border:1px solid var(--line);border-radius:9px;
 background:#fafbfc;font-size:12px;color:var(--ink2);line-height:1.5}
.sumline b{color:var(--ink);font-weight:700}
.runbar{display:flex;gap:7px;margin-left:auto;flex:0 0 auto}
.run{padding:8px 22px;border:0;border-radius:9px;background:var(--run);color:#fff;
 font-size:13.5px;font-weight:700;cursor:pointer;transition:background .12s}
.run:hover:not(:disabled){background:var(--run2)}
.run:disabled{background:#dfe3e8;color:#98a2b3;cursor:not-allowed}
.kill{padding:8px 14px;border:1px solid var(--line2);border-radius:9px;background:#fff;
 color:var(--ink2);font-size:12.5px;cursor:pointer}
.kill:hover{background:#f1f5f9}

/* ── VM 화면 ───────────────────────────────────────────── */
#screen{position:relative;width:100%;aspect-ratio:16/9;max-height:min(520px,48vh);background:var(--dark);
 border-radius:10px;display:flex;align-items:center;justify-content:center;overflow:hidden;
 box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}
#screen img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
 opacity:0;transition:opacity .12s}
#screen img.on{opacity:1}
#screen .off{position:relative;z-index:2;color:#64748b;font-size:12.5px}
.dot{width:8px;height:8px;border-radius:50%;background:#94a3b8;display:inline-block;margin-right:6px}
.dot.on{background:#15803d;animation:p 1.2s infinite}@keyframes p{50%{opacity:.3}}

/* ── 로그 ─────────────────────────────────────────────── */
pre{background:var(--dark);color:#cbd5e1;font-size:11.5px;line-height:1.55;padding:13px 14px;
 border-radius:10px;max-height:320px;overflow:auto;margin:0;white-space:pre-wrap;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace;
 /* ★ pre-wrap 은 **공백에서만** 줄을 바꾼다. kimi 로그의 Response 덤프처럼 공백 없는
    초장문 한 줄이 오면 못 쪼개고, <pre> 의 최소 너비가 그만큼 커져 그리드 칼럼을
    밀어낸다 → 페이지가 넘치고 VM 화면까지 늘어난다(실측). 어디서든 끊게 한다. */
 overflow-wrap:anywhere;word-break:break-word;min-height:132px}
#hlog{max-height:160px;min-height:84px}

/* ── 결과 ─────────────────────────────────────────────── */
#res{background:var(--dark);color:#e2e8f0;font-size:13px;line-height:1.7;padding:15px 17px;
 border-radius:10px;overflow:auto;min-height:92px}
#res h1,#res h2,#res h3,#res h4{font-size:13px;margin:18px 0 8px;color:#93c5fd;font-weight:600}
#res h1:first-child,#res h2:first-child,#res h3:first-child{margin-top:0}
#res table{width:100%;table-layout:fixed;border-collapse:collapse;margin:8px 0 12px;font-size:12.5px}
#res td,#res th{overflow-wrap:anywhere}
#res th,#res td{border:1px solid #334155;padding:6px 9px;text-align:left;vertical-align:top}
#res th{background:#111827;color:#9ca3af;font-weight:600}
#res code{background:#1e293b;padding:1px 5px;border-radius:4px;font-size:12px}
#res ul,#res ol{margin:6px 0 12px;padding-left:20px} #res li{margin:3px 0}
#res p{margin:6px 0 12px}
#res .v-통과{color:#4ade80;font-weight:600} #res .v-실패{color:#f87171;font-weight:600}
#res .v-확인불가{color:#fbbf24;font-weight:600} #res .v-불일치{color:#fb923c;font-weight:600}

.note{font-size:11.5px;color:var(--ink4);margin:10px 0 0;line-height:1.55}
.note.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;
 color:#aab2bf;word-break:break-all}
.note code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:11px;color:var(--ink2)}
a.btn{font-size:12px;color:var(--accent);text-decoration:none;border:1px solid #c7d2fe;
 background:#eef2ff;border-radius:8px;padding:4px 10px}
a.btn:hover{background:#e0e7ff}
.warn{font-size:11.5px;color:var(--ink3);margin-top:8px;line-height:1.55;
 background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 10px}
</style>
<div class="wrap">
<div class="top">
 <h1>CUA 시나리오 실행기</h1><span class="ver">ui v17</span>
 <p class="sub">옵션을 고르고 실행하면 VM 이 헤드리스로 뜨고 화면·로그가 여기에 흐릅니다.
  판정은 호스트측 파일로만 하고, 끝나면 로그를 읽어 요약을 보여 줍니다.</p>
 <a class="btn" href="/guide">시나리오 설명 보기</a>
</div>
<div class="grid">
 <div class="col-l">
  <div class="card">
   <div class="card-h"><h2>실행 옵션</h2>
    <div class="runbar">
     <button class="run" id="run">실행</button>
     <button class="kill" id="kill">중단</button>
    </div>
   </div>
   <div class="sumline" id="sumline"></div>
   <label>시나리오 <span id="scount" style="color:var(--ink4);font-weight:400"></span></label>
   <button class="pick" id="pick" aria-expanded="false"></button>
   <div class="scen" id="o-scen" style="display:none">
    <input id="find" class="find" placeholder="검색" autocomplete="off">
    <div id="scenrows"></div>
   </div>
   <label>모델</label><div class="opts" id="o-model"></div>
   <details class="adv"><summary>모델 직접 추가 (벤더 문서의 모델 ID)</summary>
    <div class="in">
     <select id="fam"><option value="claude">claude</option>
      <option value="gpt">gpt</option><option value="kimi">kimi</option></select>
     <input id="mid" placeholder="예: claude-sonnet-4-5">
     <button class="opt" onclick="addModel()">추가</button></div>
    <div id="mnote" class="note"></div>
   </details>
   <label>메모리 조회 방식</label><div class="opts" id="o-read"></div>
   <label id="armlbl">조건</label><div class="opts" id="o-arm"></div>
   <label>시행 수 (상한 __MAXT__)</label><div class="opts" id="o-trials"></div>
   <label>실행 모드</label><div class="opts" id="o-mode"></div>
   <p class="note mono" id="why"></p>
   <p class="note">VM 1대 — 동시 실행 불가. 「테스트」는 API 키·에이전트 없이 메커니즘만 확인합니다.
    옵션은 시나리오의 <code>run_chain.py</code> 가 실제로 받는 플래그에서 만들어집니다.</p>
  </div>
 </div>
 <div>
  <div class="card">
   <div class="card-h"><h2>VM 화면</h2><span class="spacer"></span>
    <span class="meta"><span><span class="dot" id="dot"></span><b id="st">유휴</b></span>
     <span id="el"></span><span id="fr"></span></span></div>
   <div id="screen"><img id="fa" alt=""><img id="fb" alt="">
    <span class="off" id="offmsg">● 대기 — 실행 전</span></div>
  </div>
  <div class="card">
   <div class="card-h"><h2>실행 로그</h2><span class="spacer"></span>
    <span class="meta">1.5초마다 갱신</span></div>
   <pre id="log">(없음)</pre>
  </div>
  <div class="card" id="hcard" style="display:none">
   <div class="card-h"><h2>보조 서버</h2>
    <span class="meta"><code id="hname"></code></span><span class="spacer"></span>
    <span class="meta"><span><span class="dot" id="hdot"></span><b id="hst">중지됨</b></span></span>
    <button class="opt" onclick="helper('start')">시작</button>
    <button class="opt" onclick="helper('stop')">중지</button></div>
   <pre id="hlog">(없음)</pre>
   <div class="warn">게스트가 호스트의 이 포트로 접속해야 해서 0.0.0.0 에 붙습니다.
    <b>터널로 내보내지 마십시오</b> — 수집 엔드포인트가 그대로 열립니다.</div>
  </div>
  <div class="card">
   <div class="card-h"><h2>결과</h2><span class="spacer"></span>
    <a class="btn" href="/report" target="_blank" rel="noopener">화면·궤적 리포트 열기</a></div>
   <div id="res">(실행이 끝나면 여기에 나옵니다)</div>
  </div>
 </div>
</div></div>
<script>
window.addEventListener("error", function(ev){
  var b=document.getElementById("res");
  if(b) b.textContent="[UI 오류] "+(ev.message||ev.type)+"  ("+(ev.filename||"")+" 줄 "+(ev.lineno||"?")+")"
      + "  — 옵션 버튼이 비어 있으면 이것 때문입니다.";
});
</script>
<script src="/ui.js"></script>
<script>
let analyzed={};                      // 실행 ID 당 한 번만 분석한다
async function doAnalyze(id, cached){
  const o=$("res");
  o.textContent = cached ? "이미 만들어 둔 요약을 불러옵니다… (추가 과금 없음)"
                         : "실행이 끝났습니다. 로그를 읽어 분석 중… (내 API 키로 1회 호출)";
  try{
    const r=await fetch("/api/analyze",{method:"POST"});
    const j=await r.json();
    if(j.ok){ o.innerHTML = md(j.text) + '<p style="opacity:.55;font-size:11.5px">— 분석 모델: '
                                        + esc(j.model) + "</p>"; }
    else { o.textContent = "[분석 실패] "+(j.error||"알 수 없음")
                           +"  —  실행 자체는 위 로그를 보십시오."; }
    if(!j.ok) analyzed[id]=false;     // 실패는 다음 틱에 재시도하지 않되 수동 여지
  }catch(e){ o.textContent="[분석 실패] "+e; }
}
let S={}, sel={trials:"1", mode:"smoke"};   // 기본 = 테스트(무과금)
const $=i=>document.getElementById(i);
function chips(box,items,key,getLabel,cls){
  const el=$(box); el.innerHTML=""; el.className="opts"+(cls?" "+cls:"");
  items.forEach(v=>{const b=document.createElement("button");
    b.className="opt"; const t=getLabel?getLabel(v):v;
    if(t && t.html){ b.innerHTML=t.html; b.title=t.title||""; } else { b.textContent=t; b.title=t; }
    b.setAttribute("aria-pressed", String(sel[key]===v));
    b.onclick=()=>{sel[key]=v; paint();}; el.appendChild(b);});
}
// 시나리오는 개수가 늘어난다 — 평소엔 선택된 한 줄, 펼치면 종류별 목록 + 검색
let filter="", picking=false;
function scenPick(){
  const d=spec()||{};
  const badges=[];
  if(d.kind_label) badges.push(d.kind_label);
  if((d.surface||{}).name) badges.push((d.surface||{}).name);
  if(d.helper) badges.push("보조 서버");
  if((d.arms||[]).length) badges.push("조건 "+d.arms.length);
  if(d.runnable===false) badges.push("UI 미지원");
  $("pick").innerHTML='<span class="nm">'+esc(sel.scenario||"(없음)")
    + badges.map(x=>'<span class="bg">'+esc(x)+"</span>").join("")+"</span>"
    + '<span class="chev">\u25bc</span>';
  $("pick").setAttribute("aria-expanded", String(picking));
  $("o-scen").style.display = picking ? "" : "none";
  $("scount").textContent = picking ? "" : "("+S.scenarios.length+"개 중)";
}
function closePick(){            // 접을 때 긴 목록 중간에 시선이 남지 않도록 되돌린다
  picking=false; filter=""; $("find").value=""; paint();
  $("pick").scrollIntoView({block:"nearest"});
}
function scenList(){
  const el=$("scenrows"); el.innerHTML="";
  const q=filter.trim().toLowerCase();
  const hit=S.scenarios.filter(d=>!q || (d.name+" "+(d.kind_label||"")).toLowerCase().includes(q));
  if(!hit.length){ el.innerHTML='<div class="none">걸린 시나리오가 없습니다.</div>'; return; }
  let group="";
  hit.forEach(d=>{
    const g=grpLabel(d.kind_label, d.surface);
    if(g!==group){ group=g; const h=document.createElement("h4");
      h.textContent=group; el.appendChild(h); }
    const b=document.createElement("button");
    b.className="opt"; b.setAttribute("aria-pressed", String(sel.scenario===d.name));
    const badges=[];
    if(!d.runnable) badges.push("UI 미지원");
    if(claudeOnly(d)) badges.push("claude 전용");
    if((d.surface||{}).name) badges.push((d.surface||{}).name);   // 노리는 공격 표면
    if(d.helper) badges.push("보조 서버");
    if((d.arms||[]).length) badges.push("조건 "+d.arms.length);
    b.innerHTML='<span class="nm">'+esc(d.name)+"</span>"
      + badges.map(x=>'<span class="bg">'+esc(x)+"</span>").join("");
    b.onclick=()=>{ sel.scenario=d.name; closePick(); };
    el.appendChild(b);
  });
}
function addModel(){
  const fam=$("fam").value, mid=$("mid").value.trim();
  if(!mid){ $("mnote").textContent="모델 ID를 입력하세요."; return; }
  const ref=Object.keys(S.models).find(k=>S.models[k].family===fam && !S.models[k].adhoc);
  if(!ref){ $("mnote").textContent="패밀리 기준 모델을 못 찾음: "+fam; return; }
  const key=fam+":"+mid;
  S.models[key]=Object.assign({},S.models[ref],{model_id:mid,family:fam,adhoc:true});
  sel.model=key; $("mid").value="";
  $("mnote").innerHTML="⚠ <b>검증 안 된 조합</b> — 벤더가 파라미터를 거부하면 "+
    "실행 로그에 400 이 찍힙니다. 돌려본 것은 haiku · luna · kimi 세 개뿐입니다.";
  paint();
}
async function helper(action){
  const r=await fetch("/api/helper",{method:"POST",headers:{"content-type":"application/json"},
                                     body:JSON.stringify({scenario:sel.scenario,action:action})});
  const j=await r.json();
  if(!j.ok) $("hlog").textContent="[실패] "+(j.error||"알 수 없음");
}
function spec(){return S.scenarios.find(d=>d.name===sel.scenario)||{flags:[],runnable:false};}
// 이 시나리오(·조건)가 요구하는 것을 이 모델 경로가 못 주면 빠진 것 목록. 모델 표에
// native/emulable 이 없으면(하네스 파이썬을 못 찾은 기본값) 도구는 가리지 않는다.
function missingFor(d,mk,arm){
  const m=S.models[mk]||{}, miss=[];
  if(m.native||m.emulable)
    (d.needs_tools||[]).forEach(t=>{ if(!(m.native||[]).includes(t)&&!(m.emulable||[]).includes(t)) miss.push(t); });
  const pa=d.policy_arms||[];
  if(m.family && m.family!=="claude" && (pa.includes("*")||pa.includes(arm))) miss.push("정책 프롬프트");
  return miss;
}
function claudeOnly(d){            // claude 가 아닌 모델은 어느 조건으로도 못 돌리면 참
  const others=Object.keys(S.models).filter(k=>(S.models[k].family||"")!=="claude");
  const arms=(d.arms&&d.arms.length)?d.arms:[""];
  return others.length>0 && others.every(k=>arms.every(a=>missingFor(d,k,a).length));
}
function has(f){return spec().flags.includes(f);}
function show(box,on,note){            // 시나리오가 안 받는 옵션은 아예 감춘다
  const w=$(box).previousElementSibling;
  $(box).style.display=on?"":"none"; if(w)w.style.display=on?"":"none";
  if(on&&note&&w)w.innerHTML=w.innerHTML.split(" <span")[0]+note;
}
function paint(){
  scenPick(); if(picking) scenList();
  chips("o-model",Object.keys(S.models),"model",
        m=>({html:"<b>"+esc(m)+'</b><span class="sub">'
                 +esc(S.models[m].adhoc ? S.models[m].model_id+" (미검증)" : S.models[m].model_id)+"</span>",
             title:m+" — "+S.models[m].model_id}), "two");
  const arms=(S.models[sel.model]||{}).arms||[];
  if(!arms.includes(sel.read_mode)) sel.read_mode=arms[0];
  chips("o-read",arms,"read_mode");
  const sarms=spec().arms||[];
  if(sarms.length && !sarms.includes(sel.arm)) sel.arm=sarms[0];
  // 조건: 이름이 길어 칩으로 흘리면 들쭉날쭉해진다 → 한 줄에 하나, 축은 오른쪽 꼬리표로
  chips("o-arm",sarms,"arm",v=>{const t=(spec().arm_axis||{})[v];
    return {html:esc(v)+(t?'<span class="tag">'+esc(t)+"</span>":""), title:v+(t?" ("+t+")":"")};},"rows");
  chips("o-trials",["1","2"].slice(0,__MAXT__),"trials",null,"two");
  chips("o-mode",has("--smoke")?["smoke","run"]:["run"],"mode",
        v=>v==="smoke"?"테스트 (API 키 안 씀)":"실제 실행 (과금)","two");
  if(!has("--smoke")) sel.mode="run";
  // 시나리오가 실제로 받는 플래그에 맞춰 컨트롤을 노출
  $("find").style.display = S.scenarios.length > 6 ? "" : "none";   // 몇 개뿐이면 검색은 숨긴다
  show("o-read",has("--read-mode"));
  show("o-arm",has("--arm") && sarms.length>0);
  $("armlbl").textContent = spec().arm_label_ui || spec().arm_label || "조건";
  const hv=!!spec().helper;
  $("hcard").style.display = hv ? "" : "none";
  if(hv) $("hname").textContent = spec().helper;
  show("o-trials",has("--trials"));
  show("o-mode",has("--smoke"));
  const miss = sel.mode==="smoke" ? [] : missingFor(spec(), sel.model, sel.arm);
  const ok=spec().runnable && !miss.length;
  $("run").disabled=!ok;
  $("run").textContent=!spec().runnable?"이 시나리오는 UI 미지원":(miss.length?"이 모델로는 못 돌림":"실행");
  $("why").textContent=!spec().runnable?spec().why:(miss.length
      ? (sel.model+" 경로에는 "+miss.join(", ")+" 이(가) 없습니다 — claude 계열 모델로 돌리세요")
      : ("플래그: "+spec().flags.join(" ")));
  // 무엇을 돌리려는지 한 줄로 — 버튼 누르기 전에 눈으로 확인하라고
  const bits=[sel.scenario, sel.model];
  if(has("--read-mode") && sel.read_mode) bits.push(sel.read_mode);
  if(has("--arm") && sarms.length && sel.arm) bits.push(sel.arm);
  if(has("--trials")) bits.push(sel.trials+"회");
  bits.push(sel.mode==="smoke"?"테스트(무과금)":"실제 실행(과금)");
  // esc() 는 /ui.js 의 공용 함수. (삼항 안에서 화살표+객체리터럴을 쓰면 파서가 깨진다)
  $("sumline").innerHTML = ok ? ("<b>" + bits.map(x=>esc(String(x))).join("</b> · <b>") + "</b>")
                              : (miss.length ? esc($("why").textContent)
                                             : "이 시나리오는 웹 UI 에서 실행할 수 없습니다");
}
fetch("/api/options").then(r=>r.json()).then(d=>{
  S=d; sel.scenario=(d.scenarios.find(x=>x.runnable)||d.scenarios[0]).name;
  sel.model=Object.keys(d.models)[0];
  paint();});
$("find").oninput=e=>{ filter=e.target.value; scenList(); };
$("pick").onclick=()=>{ if(picking){ closePick(); return; }
  picking=true; paint();
  const f=$("find"); if(f.style.display!=="none") f.focus(); };
document.addEventListener("keydown",e=>{ if(e.key==="Escape" && picking) closePick(); });
$("run").onclick=()=>{
  $("run").disabled=true;
  fetch("/api/run",{method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({...sel,trials:+sel.trials,smoke:sel.mode==="smoke",
                         phase1_only:true})})
   .then(r=>r.json()).then(d=>{if(d.error)alert(d.error);
      else { setOff("● 시작 중…"); $("res").textContent="(실행 중… 끝나면 여기에 나옵니다)"; }
      paint();});
};
$("kill").onclick=()=>fetch("/api/kill",{method:"POST"});
// ── 화면: 버퍼 2장을 opacity 로 교대 ─────────────────────────
// 오프스크린 Image 로 미리 받아도, 프레임 응답에 Cache-Control: no-store 가 붙어 있어
// 같은 URL 을 <img>.src 에 꽂는 순간 **브라우저가 다시 받으러 간다** → 그 사이가 빈 화면.
// 그래서 숨겨둔 <img> 에 직접 로드하고, onload 후 그 엘리먼트를 보여준다(재요청 0).
let cur=0, shown=null, loading=false, mode="";
function setOff(msg){
  if(mode===msg) return;                   // 같은 상태면 DOM 을 건드리지 않는다
  mode=msg; shown=null; loading=false;
  $("fa").classList.remove("on"); $("fb").classList.remove("on");
  $("offmsg").style.display=""; $("offmsg").textContent=msg;
}
function setFrame(name){
  if(name===shown||loading) return;
  loading=true; mode="";
  const next=cur===0?$("fb"):$("fa"), prev=cur===0?$("fa"):$("fb");
  next.onload=()=>{ next.classList.add("on"); prev.classList.remove("on");
                    $("offmsg").style.display="none";
                    cur=1-cur; shown=name; loading=false; };
  next.onerror=()=>{loading=false;};       // 쓰는 중이라 깨진 PNG → 다음 틱에 재시도
  next.src="/api/frame?t="+Date.now();
}
setInterval(()=>fetch("/api/status?scenario="+encodeURIComponent(sel.scenario||"")).then(r=>r.json()).then(j=>{
  if(j.helper){
    $("hst").textContent = j.helper.running ? ("실행 중 — 포트 "+j.helper.port) : "중지됨";
    $("hdot").className  = "dot"+(j.helper.running?" on":"");
    $("hlog").textContent = j.helper.log || "(없음)";
  }
  if(!j.id){ setOff("● 대기 — 실행 전"); return; }
  $("st").textContent=j.running?("실행 중 — "+j.model+"/"+j.arm):("종료 (rc="+j.rc+")");
  $("dot").className="dot"+(j.running?" on":"");
  $("el").textContent=j.elapsed+"초";
  // 로그는 콘솔처럼 꼬리를 따라간다 — 사용자가 위로 올려 읽는 중이면 건드리지 않는다
  const L=$("log"), tail = L.scrollTop + L.clientHeight >= L.scrollHeight - 24;
  L.textContent=j.log||"(없음)";
  if(tail) L.scrollTop = L.scrollHeight;
  if(j.running){
    $("fr").textContent=j.frame?("프레임 "+j.frame):"";
    if(j.frame) setFrame(j.frame);
  }else{
    $("fr").textContent="";
    setOff("● 종료");
    // 서버가 한 실행당 한 번만 모델을 부른다. 이미 만들어 둔 것이 있으면 받아만 온다.
      if(analyzed[j.id]===undefined){ analyzed[j.id]=true; doAnalyze(j.id, j.analyzed); }
  }
}),1500);
</script>"""


class H(BaseHTTPRequestHandler):
    server_version = "cua-webui"
    ST: State = None  # type: ignore
    PASSWORD: Optional[str] = None     # None 이면 인증 없음(로컬 전용)

    def log_message(self, *a):   # 콘솔 소음 억제
        pass

    def _authed(self) -> bool:
        """터널로 노출하는 순간 링크를 아는 누구나 실행 버튼을 누를 수 있다
           (= 네 API 키로 과금). 비밀번호가 설정돼 있으면 전 경로를 막는다."""
        if not self.PASSWORD:
            return True
        hdr = self.headers.get("Authorization", "")
        if not hdr.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(hdr[6:]).decode("utf-8", "replace")
        except Exception:
            return False
        _, _, pw = raw.partition(":")
        return hmac.compare_digest(pw, self.PASSWORD)

    def _challenge(self):
        body = "인증이 필요합니다.".encode()
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="cua-webui"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send(self, code: int, body: bytes, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if not self._authed():
            return self._challenge()
        u = urlparse(self.path)
        p = u.path
        S = self.ST
        if p == "/":
            return self._send(200, PAGE.replace("__MAXT__", str(MAX_TRIALS)).encode())
        if p == "/guide":
            return self._send(200, GUIDE_PAGE.encode())
        if p == "/ui.js":
            return self._send(200, MD_JS.encode(), "application/javascript; charset=utf-8")
        if p == "/api/guide":
            return self._json(guide_docs())
        if p == "/api/options":
            return self._json({"models": S.models, "scenarios": S.scenarios,
                               "max_trials": MAX_TRIALS})
        if p == "/api/status":
            out = S.job.state() if S.job else {}
            # 이미 만들어 둔 요약이 있는지 알려 준다. 새로고침한 화면이 이걸 보고
            # "분석 중…" 을 띄우지 않고 바로 받아 간다.
            if S.job:
                out["analyzed"] = S.job.digest is not None
            scen = (parse_qs(u.query).get("scenario") or [""])[0] or (
                S.job.scenario if S.job else "")
            h = S.helper_for(scen)
            if h is not None:
                out["helper"] = {"name": h.script.name, "running": h.running(),
                                 "port": h.port, "log": h.tail(30)}
            return self._json(out)
        if p == "/api/frame":
            f = S.job.latest_frame() if S.job else None
            if not f:
                return self._json({"error": "no frame"}, 404)
            return self._send(200, f.read_bytes(), "image/png")
        if p == "/report":
            if not S.job:
                return self._send(200, "<meta charset=utf-8><p>아직 실행이 없습니다.".encode())
            html_s = R.render(S.job.results, embed=False,
                              title=f"{S.job.scenario} — {S.job.model}/{S.job.arm}")
            # 리포트의 상대 경로 스크린샷을 /files 로 연결
            html_s = html_s.replace("src='_results/", "src='/files/_results/")
            return self._send(200, html_s.encode())
        if p.startswith("/files/"):
            return self._file(p[len("/files/"):])
        return self._send(404, b"not found")

    def _file(self, rel: str):
        """결과 트리 안의 파일만 서브 — 경로 탈출 차단."""
        S = self.ST
        if not S.job:
            return self._send(404, b"no job")
        base = S.job.results.parent.resolve()
        try:
            tgt = (base / rel).resolve()
            tgt.relative_to(base)                     # 탈출이면 ValueError
            if not tgt.is_file():
                raise FileNotFoundError
        except Exception:
            return self._send(403, b"forbidden")
        ctype = mimetypes.guess_type(tgt.name)[0] or "application/octet-stream"
        return self._send(200, tgt.read_bytes(), ctype)

    def do_POST(self):
        if not self._authed():
            return self._challenge()
        u = urlparse(self.path)
        S = self.ST
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if u.path == "/api/run":
            keep = ("scenario", "model", "arm", "trials", "read_mode",
                    "phase1_only", "smoke")  # flags 는 서버가 채운다
            kw = {k: body.get(k) for k in keep}
            spec = next((d for d in S.scenarios if d["name"] == kw["scenario"]), None)
            model = str(kw.get("model") or "")
            if spec is None or (model not in S.models and not ADHOC.match(model)):
                return self._json({"error": "알 수 없는 시나리오/모델"}, 400)
            if not spec["runnable"]:
                return self._json({"error": spec["why"]}, 400)
            if spec["arms"] and kw.get("arm") not in spec["arms"]:
                return self._json({"error": f"'{kw.get('arm')}' 은 이 시나리오의 팔이 아닙니다 "
                                            f"— {', '.join(spec['arms'])}"}, 400)
            kw["flags"] = spec["flags"]
            return self._json(S.submit(**kw))
        if u.path == "/api/analyze":
            if not S.job:
                return self._json({"ok": False, "error": "아직 실행이 없습니다."}, 400)
            if S.job.proc and S.job.proc.poll() is None:
                return self._json({"ok": False, "error": "실행이 끝난 뒤에 분석하세요."}, 409)
            job = S.job
            with job.digest_lock:                 # 동시에 두 탭이 눌러도 한 번만 부른다
                if job.digest is not None:        # 이미 만든 것이 있으면 **다시 부르지 않는다**
                    return self._json({**job.digest, "cached": True})
            try:
                _h = S.helper_for(S.job.scenario)
                digest = A.build_digest(S.job.results, S.job.scenario,
                                        run_log=S.job.log,
                                        since=S.job.started, model=S.job.model,
                                        helper_log=_h.log if _h else None)
            except Exception as exc:                                   # noqa: BLE001
                return self._json({"ok": False, "error": f"결과를 못 읽음: {exc}"}, 500)
            if not digest.get("evaluator_summary") and digest["run_log"].startswith("(실행"):
                return self._json({"ok": False, "error": "결과도 로그도 없습니다."}, 400)
            with job.digest_lock:
                if job.digest is None:
                    out = A.analyze(digest)
                    if out.get("ok"):             # 실패는 캐시하지 않는다(다시 시도할 수 있게)
                        job.digest = out
                    return self._json(out)
                return self._json({**job.digest, "cached": True})
        if u.path == "/api/helper":
            h = S.helper_for(str(body.get("scenario") or ""))
            if h is None:
                return self._json({"ok": False, "error": "이 시나리오는 보조 서버가 없습니다"}, 400)
            return self._json(h.start() if body.get("action") == "start" else h.stop())
        if u.path == "/api/kill":
            return self._json(S.kill())
        return self._json({"error": "unknown"}, 404)


def main():
    global OSW, SCEN
    try:                                  # nohup/터널 운영 시 시작 로그가 묻히지 않게
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--osworld-root", default=None,
                    help="하네스(OSWorld 포크) 경로. 생략하면 $OSWORLD_ROOT → "
                         "레포 안 ./OSWorld 를 씁니다")
    ap.add_argument("--vmx", default=os.environ.get(
        "RAID_VMX", "vmware_vm_data/Ubuntu0/Ubuntu0.vmx"))
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1",
                    help="기본 127.0.0.1 유지 권장 — 외부 노출은 터널로 한다")
    ap.add_argument("--password", default=os.environ.get("WEBUI_PASSWORD"),
                    help="Basic 인증 비밀번호(아이디는 아무거나). 터널로 노출할 땐 필수")
    a = ap.parse_args()
    # 순서가 중요하다: 레포 .env → 하네스 확정 → 하네스 .env.
    #   레포 .env 가 OSWORLD_ROOT 를 줄 수 있으므로 그것부터 읽고,
    #   하네스 .env 는 **확정된 뒤** 읽어야 한다(먼저 읽으면 엉뚱한 포크의 키를 쓴다).
    got = load_env_files(ROOT / ".env")
    OSW = locate_osworld(a.osworld_root)
    SCEN = OSW / "security_scenarios"
    got += load_env_files(OSW / ".env")
    print(f"[webui] .env {got or '못 찾음 — smoke 만 가능'}")
    if not SCEN.is_dir():
        raise SystemExit(
            f"[webui] 중단: 하네스를 못 찾음 — {SCEN} 없음\n"
            f"        docs/SETUP.md 참고. 포크를 클론했으면 "
            f"--osworld-root <경로>/OSWorld 로 지정할 것.")
    print(f"[webui] 하네스 {OSW}")
    hl = os.environ.get("RAID_HEADLESS", "1").strip() not in ("0", "false", "no")
    print(f"[webui] VM 표시 {'헤드리스 (호스트에 창 없음 — 화면은 이 웹에서만)' if hl else '호스트에 창 띄움 (RAID_HEADLESS=0)'}")
    H.ST = State(a.vmx)
    H.PASSWORD = a.password or None
    _py = find_python()
    print(f"[webui] 하네스 파이썬 {_py or '못 찾음'}")
    if DEPS_HINT:
        print(f"[webui] ⚠ {DEPS_HINT}")
    print(f"[webui] 모델 {list(H.ST.models)}")
    print(f"[webui] 시나리오 {H.ST.scenarios}")
    print(f"[webui] http://{a.host}:{a.port}  (vmx={a.vmx}, 시행 상한 {MAX_TRIALS})")
    if H.PASSWORD:
        print("[webui] Basic 인증 켜짐 — 아이디는 아무거나, 비밀번호만 맞으면 됨")
    else:
        print("[webui] ⚠ 인증 없음. 로컬에서만 쓸 것. "
              "터널(cloudflared/ngrok)로 노출하려면 --password 를 반드시 줄 것 "
              "— 링크를 아는 누구나 실행해 API 키를 태울 수 있다.")
    if a.host not in ("127.0.0.1", "localhost") and not H.PASSWORD:
        raise SystemExit("[webui] 중단: 외부 바인딩인데 --password 가 없음")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
