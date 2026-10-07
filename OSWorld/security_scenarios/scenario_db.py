#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시나리오 DB 공용 헬퍼 — 웹 UI 가 읽는 결과 '행(row)' 규격을 한 곳에서 만든다.

시나리오의 자체 실행기마다 CLI·출력 위치·판정 어휘가 다르다. 이 모듈은 그 차이를
진입점(run_chain.py) 쪽에서 흡수하게 돕는다.
표준 라이브러리만 쓴다.

규격 (자세한 설명: docs/SCENARIO_DB.md)
  실행  python security_scenarios/<이름>/run_chain.py --model <모델> --trials N
                                                      [--arm A] [--read-mode M] [--smoke]
  결과  <시나리오>/_results/<모델키>/<arm>/t<N>/{summary.json, p1/, p2/, ...}
  판정  자체 판정을 번역만 한다. 다시 채점하지 않고, 판정 경로에 LLM 을 쓰지 않는다.

이 파일을 쓰는 곳: MEM-BOUNDARY/run_chain.py · MEM-FALSEFAIL/run_chain.py
(FOCUS-MISDELIVERY · SELFTEST-PING 은 이미 이 규격이라 안 쓴다)
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple, Union

SCEN_ROOT = Path(__file__).resolve().parent        # .../OSWorld/security_scenarios
HARNESS_ROOT = SCEN_ROOT.parent                    # .../OSWorld
REPO_ROOT = HARNESS_ROOT.parent                    # .../cua-scenario-db


# ── 경로·입력 ──────────────────────────────────────────────────────────────
def rel(p: Any) -> str:
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


def resolve_vmx(given: str) -> str:
    """--vmx 를 실제 파일로 풀어 준다. 못 찾으면 빈 문자열 — 자체 러너가 자기 말로 알린다."""
    if given and Path(given).exists():
        return str(Path(given))
    if given and (HARNESS_ROOT / given).exists():
        return str(HARNESS_ROOT / given)
    found = sorted(HARNESS_ROOT.glob("vmware_vm_data/*/*.vmx"))
    return str(found[0]) if found else ""


def model_key(model: str) -> str:
    """--model 값(키 또는 모델 ID)을 하네스의 모델 키로 풀어 준다. 못 풀면 받은 값 그대로."""
    try:
        from mm_agents.adapters.agents import resolve_model_key
        return resolve_model_key(model)
    except Exception:                                              # noqa: BLE001
        return model


def stock_read_mode(model_key: str) -> Optional[str]:
    """메모리 팔 기본값 = 모델 벤더 스톡(MODEL_SPECS 의 첫 팔). UI 의 기본 선택과 같은 규칙."""
    try:
        from mm_agents.adapters.agents import MODEL_SPECS
        arms = list(MODEL_SPECS[model_key].get("arms", ()))
        return arms[0] if arms else None
    except Exception:                                              # noqa: BLE001
        return None


def load_env() -> None:
    """API 키는 레포 루트 .env 와 하네스 .env 에서 읽는다(웹 UI 와 같은 위치). 셸에서 준 값이 우선.
    python-dotenv 가 없으면 조용히 넘어간다 — 키가 셸 환경에 이미 있을 수 있다."""
    try:
        from dotenv import load_dotenv
    except Exception:                                              # noqa: BLE001
        return
    for p in (REPO_ROOT / ".env", HARNESS_ROOT / ".env"):
        try:
            if p.is_file():
                load_dotenv(p, override=False)
        except Exception:                                          # noqa: BLE001
            pass


# ── 파일 ──────────────────────────────────────────────────────────────────
def write_json(path: Union[str, Path], obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Union[str, Path]) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def row_dir(outdir: Union[str, Path], model_key: str, arm: str, i: int) -> Path:
    """UI 가 읽는 시행 폴더: <결과루트>/<모델키>/<arm>/t<N>"""
    return Path(outdir) / model_key / arm / f"t{i}"


def fresh_dir(path: Union[str, Path]) -> Path:
    p = Path(path)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def copy_if_exists(src: Path, dst: Path) -> None:
    """자체 실행기가 남긴 증거 파일/폴더를 행 폴더로 복사한다. 없으면 조용히 넘어간다."""
    try:
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("summary*.json", "__pycache__"))
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except OSError as exc:
        print(f"[!] 증거 복사 실패 {src.name}: {exc}")


def yn(v: Any) -> List[str]:
    """host_rows 의 (값, 강조) 쌍 — 렌더러의 범용 대조 카드 규격."""
    return ["예", "hit"] if v else ["아니오", ""]


def deepest_fired(stages: Optional[Iterable[dict]], names: dict) -> str:
    """가장 깊이 발화한 단계 이름. 하나도 없으면 'none'."""
    last = None
    for s in stages or []:
        if s.get("fired"):
            last = s.get("id")
    if last is None:
        return "none"
    return f"{last}_{names[last]}" if last in names else str(last)


# ── 실시간 화면: 자체 실행기 폴더 → UI 행 폴더 ─────────────────────────────────────
Source = Union[Path, None, Callable[[], Optional[Path]]]


class FrameMirror:
    """자체 러너가 쓰는 스크린샷·궤적을 UI 가 읽는 행 폴더로 따라 옮긴다.

    UI 는 `<결과루트>/<모델>/*/t*/p?/step_*.png` 만 보고 실행 화면을 띄운다. 자체 러너는
    자기 규칙의 폴더(phase1/phase2 등)에 쓰므로, 그대로 두고 여기서 **하드링크**(안 되면
    복사)로 옮긴다. 자체 러너의 파일은 읽기만 한다.
    """

    def __init__(self, pairs: Sequence[Tuple[Source, Path]], interval: float = 1.0):
        self.pairs = list(pairs)
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seen: dict = {}

    @staticmethod
    def _wanted(f: Path) -> bool:
        return f.is_file() and (f.name == "trajectory.jsonl"
                                or (f.name.startswith("step_") and f.suffix == ".png"))

    def _sync_one(self, src: Source, dst: Path) -> None:
        d = src() if callable(src) else src
        if d is None or not Path(d).is_dir():
            return
        try:
            files = [f for f in Path(d).iterdir() if self._wanted(f)]
        except OSError:
            return
        for f in files:
            try:
                st = f.stat()
            except OSError:
                continue
            target = dst / f.name
            sig = (st.st_size, st.st_mtime_ns)
            if self._seen.get(target) == sig and target.exists():
                continue
            try:
                dst.mkdir(parents=True, exist_ok=True)
                if f.suffix == ".png":
                    if target.exists() and target.stat().st_size == st.st_size:
                        self._seen[target] = sig
                        continue
                    if target.exists():
                        target.unlink()
                    try:
                        os.link(f, target)
                    except OSError:
                        shutil.copyfile(f, target)
                else:
                    shutil.copyfile(f, target)
                self._seen[target] = sig
            except OSError:
                continue

    def sync(self) -> None:
        for src, dst in self.pairs:
            self._sync_one(src, dst)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.sync()
            except Exception:                                      # noqa: BLE001
                pass

    def start(self) -> "FrameMirror":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.sync()                                                # 마지막 한 번


# ── 프로세스 ───────────────────────────────────────────────────────────────
def install_sigterm_as_interrupt() -> None:
    """UI 의 [중지] 는 프로세스에 SIGTERM 을 보낸다. 기본 동작은 즉사라 자체 러너의 정리
    코드(VM·랩 서버·잠금 해제)가 안 돈다. KeyboardInterrupt 로 바꿔 정리가 돌게 한다.
    (윈도우의 TerminateProcess 는 가로챌 수 없다 — 그쪽은 남은 잠금 파일을 안내만 한다.)"""
    def _handler(signum, frame):                                   # noqa: ARG001
        raise KeyboardInterrupt(f"signal {signum}")
    try:
        signal.signal(signal.SIGTERM, _handler)
    except Exception:                                              # noqa: BLE001
        pass
