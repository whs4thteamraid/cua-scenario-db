# -*- coding: utf-8 -*-
"""세 모델 어댑터 + 모델별 지원 도구 검증.

러너는 build_agent() 하나만 부르면 되고, 모델마다 다른 것은 전부 여기에 갇힌다.

  claude → ClaudeAdapter : claude_cua 를 그대로 위임 (벤더 코드 무수정, 전부 native)
  luna   → LunaAdapter   : PromptAgent(순수 텍스트) + 에뮬 도구
  kimi   → KimiAdapter   : KimiAgent(순수 텍스트) + 에뮬 도구

지원하지 않는 조합은 **VM 을 띄우기 전에 거부**한다. 조용히 다른 조건으로 도는 것이
제일 위험하기 때문이다(결과가 모델 차이처럼 보인다).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from mm_agents.base.base_agent import BaseAgent, EpisodeResult, StepAgentAdapter, StepOutput
from mm_agents.base.emu_tools import EmuToolLayer, make_vm_exec

logger = logging.getLogger("desktopenv.agent")


def _sp_fingerprint(text: str) -> Dict[str, Any]:
    """시스템 프롬프트의 지문. 전문을 summary 에 넣지 않으면서 '같은 프롬프트였나'를 판정한다.

    ★ 세 모델의 프롬프트는 계보가 달라서(우리 것/stock/벤더) 애초에 같아질 수 없다.
      그래도 지문을 남기는 이유는 **판 사이에 조용히 바뀌는 것**을 잡기 위해서다.
      같은 모델의 두 판에서 해시가 다르면 그 사이에 무언가 프롬프트를 건드린 것이다.
    """
    t = text or ""
    return {"system_prompt_sha256": hashlib.sha256(t.encode("utf-8")).hexdigest()[:16],
            "system_prompt_len": len(t)}


def claude_conditions(a: Any) -> Dict[str, Any]:
    """claude_cua 에이전트 객체에서 실제 조건을 읽는다.

    ★ 모듈 함수인 이유 — `Session.make_agent()` 의 claude 분기는 ClaudeAdapter 가 아니라
      SystemPromptMCPMemoryClaudeCUAAgent 를 **그대로** 돌려준다(벤더 호출 경로를 건드리지
      않으려고 그렇게 둔 것이다). 그래서 어댑터 메서드로만 두면 러너의 claude 판에는
      조건이 안 붙는다. 양쪽이 같은 함수를 부르게 해서 두 경로가 갈라지지 않게 한다.
    """
    d = {
        # 전부 살아있는 객체에서 읽는다 — 상수를 적어두면 드리프트를 못 잡는다.
        "history_steps": getattr(a, "only_n_recent_images", None),
        "history_unit":  "screenshots",
        "max_tokens":    getattr(a, "max_tokens", None),
        # messages.create 에 temperature/top_p 를 보내지 않는다 → API 기본값.
        # 속성이 생기면 자동으로 잡히도록 getattr 로 읽는다.
        "temperature":   getattr(a, "temperature", None),
        "top_p":         getattr(a, "top_p", None),
        # send_width 로 축소한 **실제 전송 크기**(기본 1280).
        "image_sent_wh": [getattr(a, "disp_w", None), getattr(a, "disp_h", None)],
        # ★ 기본값은 None 이지 False 가 아니다. claude 경로는 thinking 파라미터를
        #   payload 에 넣지 않으므로 이 속성이 없다. 예전에는 기본값이 False 라
        #   **보낸 적 없는 값을 "껐다"고 기록**했다 — thinking 은 비교 축이므로
        #   haiku 는 영영 False 로 읽혔다. None = 미전송이 정직한 기록이다.
        #   payload 에 넣게 되면 속성이 생겨 여기 자동 반영된다.
        "thinking":      getattr(a, "thinking", None),
        "reasoning_elicitation": "none",          # 강제 문구 없이 자연 발화
        "tool_channel":  "native_tool_result",
        # ★ 노브가 아니다. 응답당 tool_use 가 하나로 강제되고(disable_parallel_tool_use),
        #   실측상 GUI 호출/스텝이 1.00 이었다. 검증은 measured.gui_calls_per_step 으로.
        "one_call_per_step": None,
        "memory_arm":    getattr(a, "read_mode", None),
    }
    d.update(_sp_fingerprint(getattr(a, "system_prompt", "")))
    return d

# ── 문맥 길이: 세 모델을 같은 값에 맞춘다 ────────────────────────────────────
# ★ 왜 (실측) — 예전에는 모델마다 제각각이었다.
#       Luna  max_trajectory_length     3   (벤더·stock 기본값)
#       Haiku only_n_recent_images      6   (claude_cua 기본값)
#       Kimi  max_image_history_length  8   (벤더 기본값은 3인데 우리가 올려둔 값)
#   "1번 턴에 목록을 봤다 → 3번 턴에 그걸 근거로 답한다" 같은 판단이 이 값에 직접
#   걸린다. 값이 다르면 모델 차이인지 문맥 길이 차이인지 가를 수 없다.
#   Haiku 기준(6)으로 맞춘다 — claude_cua 는 우리가 건드리지 않는 벤더 코드이고,
#   그 결과가 이미 쌓여 있어 기준으로 삼는 것이 손실이 가장 적다.
#
# ★ 단위가 완전히 같지는 않다. Luna 는 (스크린샷+액션+생각) 묶음 수, Haiku·Kimi 는
#   유지하는 스크린샷 수다. "대략 같은 만큼 과거를 본다" 수준의 정렬이지 동일 조건은
#   아니며, 비교를 보고할 때 이 한계를 함께 적을 것.
HISTORY_STEPS = 6

# ── 출력 예산 ────────────────────────────────────────────────────────────────
# ★ 왜 6000 (위로 맞춤) — Haiku 4096(claude_cua 기본) / Luna 6000 / Kimi 4096(벤더 기본)
#   이었다. Kimi 는 thinking 을 켜면 추론과 본문이 **같은 예산**을 나눠 쓰므로 4096 으로
#   내려 맞추면 Kimi 만 실질 출력이 쪼들린다. 위로 맞추면 어느 모델도 불리해지지 않는다.
MAX_TOKENS = 6000

# ── 샘플링 ──────────────────────────────────────────────────────────────────
# ★ temperature 0.6 — 세 모델 공통. 왜 1.0 이 아니라 0.6 인가 (실측):
#     Kimi 는 추론을 끄면(thinking={"type":"disabled"}) **0.6 만 허용**한다
#     (`invalid temperature: only 0.6 is allowed for this model`).
#     Claude 는 0~1 아무 값, Luna(gpt-5.6)는 0.6 수락 확인됨(probe_luna_temperature).
#   그래서 0.6 으로 내려야 thinking 과 temperature 를 **동시에** 맞출 수 있다.
#   1.0 을 고집하면 Kimi 만 추론이 켜진 채로 남는다.
TEMPERATURE = 0.6
# ★ top_p 는 **맞출 수 없다.** 세 모델이 서로 다른 이유로 막혀 있다.
#     Haiku : messages.create 에 안 보낸다(=기본 1.0)
#     Luna  : gpt-5.6 이 top_p 를 거부 → gpt 분기가 payload 에서 제거
#     Kimi  : Moonshot hosted 가 **0.95 만 허용** (실측: 1.0 을 보내면
#             `invalid top_p: only 0.95 is allowed for this model` 400 으로 전 스텝 실패)
#   한때 1.0 으로 통일하려 했다가 Kimi 판을 통째로 날렸다. 벤더가 강제하는 값이므로
#   건드리지 않고, 비교기에서 구조적 잔차로 둔다.
KIMI_TOP_P = 0.95

# ★ Luna 의 확장 추론. gpt-5.6 은 reasoning_effort 를 받고 'none' 이 추론을 0 으로 만든다
#   (실측: none=0 / high=9 토큰). Haiku(파라미터 미전송)·Kimi(thinking=False) 와 같은
#   기준선에 세우기 위해 'none' 으로 고정한다. 켜려면 high/xhigh.
REASONING_EFFORT = "none"

# ── 벤더 파라미터: 기본은 stock, 레거시는 opt-in ─────────────────────────────
# ★ 위 상수들은 "3모델 출발선 정렬"을 위해 도입됐지만, 실측 결과 정렬로 기능하지
#   않았다(2026-09-25):
#     · Claude 에는 **적용된 적이 없다** — build_agent 의 claude 분기가 temperature/
#       max_tokens 를 넘기지 않아 agent_mcp 기본값(1.0/4096)으로 돌았다. 2모델짜리였다.
#     · Kimi 는 stock temperature=1 인데 0.6 을 보내 벤더가 거부한다
#       (`invalid temperature: only 1 is allowed for this model`).
#     · Luna 만 `reasoning_effort="none"` 을 명시 전송한다 — 문자열이라 truthy.
#       셋 중 이 모델만 추론이 꺼진 채 돈다.
#   그리고 축간 정렬은 애초에 성립하지 않는다(compare_conditions 의 MUST_MATCH 제외
#   목록: memory_arm·top_p·system_prompt 계보·coordinate_type). 맞추려는 노력이
#   "맞았다"는 착시만 준다.
#   → 기본값을 stock(=미전송)으로 내리고, 기존 판 재현이 필요하면 ALIGN_LEGACY=1.
#   ※ 예산 성격(max_tokens·HISTORY_STEPS)은 이번 범위 밖 — 따로 정한다.
ALIGN_LEGACY = os.environ.get("ALIGN_LEGACY", "0") != "0"

# ★ "안 보낸다" 로는 벤더 기본값에 닿지 않는다(실측). 하위 OSWorld 에이전트가 자기
#   기본값을 payload 에 싣기 때문이다 — PromptAgent 는 temperature=0.5 인데
#   gpt-5.6 은 그 값을 거부한다(`does not support 0.5 ... Only the default (1)`).
#   그래서 규칙은 "미전송"이 아니라 **"벤더 기본값을 명시 전송"** 이다.
#   세 모델 모두 그 값이 1.0 이다:
#     Claude  agent_mcp.py:76  temperature=1.0
#     Luna    gpt-5.6          1 만 허용
#     Kimi    kimi_agent.py    temperature=1
#   → 손을 떼면 세 모델이 1.0 에서 저절로 일치한다. 0.6 으로 끌어내린 것이
#     오히려 정렬을 깨고 있었다.
VENDOR_TEMPERATURE = 1.0

# ── 스톡 기본값: OSWorld 레포의 에이전트가 선언한 값 그대로 ──────────────────
# ★ "3모델 출발선 정렬"은 성립하지 않는다(2026-09-25 결론). 히스토리 축이 세는 대상이
#   애초에 다르기 때문이다:
#       PromptAgent.max_trajectory_length      = 3   관측(스크린샷+액션+생각) 묶음 수
#       KimiAgent.max_image_history_length     = 3   히스토리 이미지 수
#       ClaudeCUAAgent.only_n_recent_images    = 6   최근 이미지 수
#   GPT 의 3 은 "턴"이고 Kimi 의 3 은 "장"이다. 같은 6 으로 맞춰도 같은 문맥이 아니다.
#   → 기본값은 **각 벤더 에이전트의 선언값**으로 두고, 불일치는 지문에 그대로 적어
#     비교기가 구조적 잔차로 처리한다. 예전 판 재현은 ALIGN_LEGACY=1.
STOCK_LUNA_MAX_TOKENS  = 1500      # mm_agents/agent.py PromptAgent
STOCK_LUNA_TRAJ        = 3         #   같은 곳
STOCK_KIMI_MAX_TOKENS  = 4096      # mm_agents/kimi/kimi_agent.py KimiAgent
STOCK_KIMI_IMG_HISTORY = 3         #   같은 곳 (실효 2장 — kimi_effective_history 참조)
STOCK_CLAUDE_MAX_TOKENS = 4096     # mm_agents/claude_cua/agent_mcp.py:73
STOCK_CLAUDE_TEMPERATURE = 1.0     #   같은 곳 :76 (= VENDOR_TEMPERATURE)


def claude_stock_params() -> Dict[str, Any]:
    """claude 경로에 넘길 벤더 파라미터 — **단일 출처.**

    ★ 왜 함수인가 (전수조사 2026-09-27) — `build_agent` 의 claude 분기는 이 값들을
      넘기지 않지만, 러너의 `Session.make_agent()` 는 벤더 에이전트를 **직접** 만들면서
      `max_tokens=MAX_TOKENS, temperature=TEMPERATURE` 를 넘기고 있었다. 그래서
      "Claude 에는 정렬 상수가 적용된 적 없다" 가 거짓이었고, 어댑터만 스톡으로
      되돌렸을 때 haiku 만 6000/0.6 에 남아 회귀에서 빠졌다(ALIGN_LEGACY 로도 못 돌림).
      값을 두 곳에 두면 또 어긋난다. 양쪽이 이 함수를 부른다.
    """
    return {
        "max_tokens":  MAX_TOKENS if ALIGN_LEGACY else STOCK_CLAUDE_MAX_TOKENS,
        "temperature": TEMPERATURE if ALIGN_LEGACY else VENDOR_TEMPERATURE,
    }

# ── 모델 표 ──────────────────────────────────────────────────────────────────
MODEL_SPECS: Dict[str, Dict[str, Any]] = {
    "haiku": {
        "model_id": "claude-haiku-4-5",
        "family": "claude",
        "api_key_env": "ANTHROPIC_API_KEY",
        "agent": "claude_cua.SystemPromptMCPMemoryClaudeCUAAgent",
        "native": {"computer", "bash", "editor", "mcp", "memory", "approval", "popup"},
        "arms": ("faithful", "controlled", "inject"),
    },
    "luna": {
        "model_id": "gpt-5.6-luna",
        "family": "gpt",
        "api_key_env": "OPENAI_API_KEY",
        "agent": "PromptAgent(text)",
        "native": {"computer"},
        "emulable": {"bash", "memory", "approval"},
        # neutral = 도구만, 억제 문구 없음(진단용). 자세한 이유는 emu_tools 참조.
        "arms": ("neutral", "controlled", "inject"),
    },
    "kimi": {
        "model_id": "kimi-k2.6",
        "family": "kimi",
        "api_key_env": "KIMI_API_KEY",
        "agent": "KimiAgent(text)",
        "native": {"computer"},
        "emulable": {"bash", "memory", "approval"},
        "arms": ("neutral", "controlled", "inject"),
    },
}
_ALIASES = {spec["model_id"]: key for key, spec in MODEL_SPECS.items()}
_ALIASES.update({"claude": "haiku", "claude-haiku-4-5": "haiku",
                 "gpt-5.6-luna": "luna", "gpt": "luna", "kimi-k2.6": "kimi"})


# 패밀리별 기준 엔트리 — 임시 모델은 이것을 복제해 model_id 만 갈아끼운다.
_FAMILY_REF = {"claude": "haiku", "gpt": "luna", "kimi": "kimi"}


def resolve_model_key(name: str) -> str:
    raw = (name or "").strip()
    key = raw.lower()
    if key in MODEL_SPECS:
        return key
    if key in _ALIASES:
        return _ALIASES[key]

    # ── 임시 모델: "<패밀리>:<모델ID>" (예: claude:claude-sonnet-4-5) ──────────
    # 벤더 문서의 ID 를 그대로 붙여넣어 돌려보기 위한 통로. 코드 경로(에이전트 클래스·
    # 도구 층)는 패밀리가 정하므로 기준 엔트리를 복제하면 된다.
    #
    # ★ 돈다는 보장은 없다. 같은 벤더 안에서도 허용 파라미터가 다르다 — 실측:
    #     kimi  `invalid temperature: only 1 is allowed for this model`
    #     kimi  `invalid top_p: only 0.95 is allowed for this model`  → 전 스텝 400
    #     gpt-5.6  top_p 자체를 거부
    #   또 claude 경로의 computer 도구 버전은 agent.py 가 모델명 문자열로 고른다
    #   (`"haiku" in model.lower()`). 검증된 조합은 아래 MODEL_SPECS 의 3개뿐이다.
    if ":" in raw:
        fam, _, mid = raw.partition(":")
        fam, mid = fam.strip().lower(), mid.strip()
        ref = _FAMILY_REF.get(fam)
        if ref and mid:
            # 키는 memstore 경로로도 쓰이므로 파일명 안전하게 만든다
            safe = re.sub(r"[^a-z0-9._-]+", "-", mid.lower()).strip("-")
            adhoc = f"{fam}__{safe}"
            if adhoc not in MODEL_SPECS:
                spec = dict(MODEL_SPECS[ref])
                spec["model_id"] = mid
                spec["adhoc"] = True
                MODEL_SPECS[adhoc] = spec
            return adhoc

    raise ValueError(
        f"알 수 없는 모델 '{name}'. 검증된 모델: {', '.join(k for k in MODEL_SPECS if not MODEL_SPECS[k].get('adhoc'))}\n"
        f"  다른 모델을 쓰려면 '<패밀리>:<모델ID>' 형식으로 주십시오 "
        f"(패밀리: {', '.join(_FAMILY_REF)}). 예: claude:claude-sonnet-4-5")


def memstore_for(model: str, base) -> str:
    """모델별 memstore 경로 — `<base>_<모델키>` (예: redteam/memstore_kimi).

    ★ 왜 나누는가 — 세 모델이 한 폴더를 돌려쓰면, 시행 사이 정리가 **한 번만** 실패해도
      이전 모델의 노트가 다음 판에 섞인다. 섞인 판은 결과만 봐서는 정상과 구분되지 않는다.
      폴더가 갈려 있으면 그 사고 자체가 불가능해진다.

    ★ 조건 차이는 생기지 않는다 — 모델이 보는 경로는 세 모델 모두 가상 루트 `/memories`
      이고, 호스트 폴더가 실제로 어디인지는 프롬프트에 한 번도 나오지 않는다.
      (claude 는 memory_backend, 에뮬은 emu_tools 가 각각 /memories 를 매핑한다.)

    ★ 경로를 나눠도 **시행마다 비우는 것은 그대로** 해야 한다. 실험의 출발선은
      "노트 내용이 정확히 이것"이지 "폴더가 비어있음"이 아니다.
    """
    return f"{base}_{resolve_model_key(model)}"


# ── 검증: VM 을 띄우기 전에 조합을 거른다 ────────────────────────────────────
def validate_request(model: str, *, tools: List[str], memory: bool = False,
                     memory_arm: Optional[str] = None,
                     inject_popup: bool = False) -> Dict[str, Any]:
    """지원 여부를 판정하고 native/emulated 매핑을 돌려준다. 불가하면 ValueError."""
    key = resolve_model_key(model)
    spec = MODEL_SPECS[key]
    native = spec["native"]
    emulable = spec.get("emulable", set())

    wanted = {"computer"} | {t for t in tools if t and t != "computer"}
    if memory:
        wanted.add("memory")
    if inject_popup:
        wanted.add("popup")

    resolved: Dict[str, str] = {}
    refused: List[str] = []
    for name in sorted(wanted):
        if name in native:
            resolved[name] = "native"
        elif name in emulable:
            resolved[name] = "emulated"
        else:
            refused.append(name)

    reasons = {
        "mcp": "MCP 는 Luna·Kimi 경로에서 제공하지 않습니다. 텍스트로 흉내내면 "
               "'커넥터 공급망'이 아니라 '커넥터인 척하는 글자'가 되어 위협모델이 바뀝니다.",
        "editor": "editor 는 에뮬 bash 와 기능이 겹치고 문법 오류 표면만 늘려서 제공하지 않습니다. "
                  "파일 작업은 bash 로 하세요.",
        "popup": "팝업 주입은 현재 claude 경로에만 구현되어 있습니다(좌표계가 모델마다 다름).",
    }
    if refused:
        lines = [f"✗ 모델 '{spec['model_id']}' 에서 지원하지 않는 요청: {', '.join(refused)}"]
        lines += [f"  · {n}: {reasons.get(n, '지원하지 않습니다.')}" for n in refused]
        raise ValueError("\n".join(lines))

    if memory:
        arm = memory_arm or "faithful"
        if arm not in spec["arms"]:
            raise ValueError(
                f"✗ 모델 '{spec['model_id']}' 는 메모리 팔 '{arm}' 를 지원하지 않습니다.\n"
                f"  지원: {', '.join(spec['arms'])}\n"
                "  · faithful(자동조회)은 Anthropic 서버가 auto-view 프로토콜을 주입해서 "
                "생기는 행동이라, 프롬프트로 흉내내면 그건 이미 controlled 입니다.\n"
                "  · neutral(진단용)은 도구만 주고 억제 문구를 붙이지 않는 조건입니다. "
                "조회를 **지시하는** 시나리오는 억제 문구와 서로 밀므로 이 팔을 쓰세요.")

    return {"model_key": key, "model_id": spec["model_id"], "family": spec["family"],
            "agent": spec["agent"], "api_key_env": spec["api_key_env"],
            "tools_enabled": resolved,
            "emulated": sorted(n for n, v in resolved.items() if v == "emulated")}


# ── 어댑터 ───────────────────────────────────────────────────────────────────
class ClaudeAdapter(BaseAgent):
    """claude_cua 는 스스로 끝까지 도는 루프 소유형 → 그대로 위임만 한다."""

    name = "claude_cua"
    supports_arms = ("faithful", "controlled", "inject")

    def __init__(self, env, *, model: str, verbose: bool = True, **claude_kwargs):
        super().__init__(env, model=model, verbose=verbose)
        from mm_agents.claude_cua.agent_system_prompt_mcp_memory import (
            SystemPromptMCPMemoryClaudeCUAAgent)
        self._a = SystemPromptMCPMemoryClaudeCUAAgent(
            env, model=model, verbose=verbose, **claude_kwargs)

    def reset(self) -> None:
        self._a.reset()

    def run_episode(self, instruction: str, max_steps: int = 30,
                    result_dir: Optional[str] = None) -> EpisodeResult:
        raw = self._a.run(instruction, max_steps=max_steps, result_dir=result_dir)
        res = EpisodeResult.from_claude_dict(raw, model=self.model, agent=self.name)
        # from_claude_dict 는 벤더 dict 만 옮기므로 조건은 여기서 채운다.
        res.conditions = self.conditions()
        return res

    def conditions(self) -> Dict[str, Any]:
        # ★ 이 메서드는 반드시 클래스에 **명시적으로** 있어야 한다. 없으면 아래
        #   __getattr__ 가 claude_cua 쪽으로 넘겨버려서 조용히 엉뚱한 것이 불린다.
        return claude_conditions(self.__dict__["_a"])

    def __getattr__(self, item):        # mcp_tool_names 등 러너가 직접 보던 속성 통과
        return getattr(self.__dict__["_a"], item)


class LunaAdapter(StepAgentAdapter):
    """OSWorld stock PromptAgent 의 gpt 분기. 순수 텍스트 경로(도구 호출 없음)."""

    name = "PromptAgent(text)"
    tag = "luna"
    # PromptAgent 는 instruction 을 시스템 메시지로 넣는다 → 도구 결과는 따로 전달.
    results_to_user_turn = True

    def __init__(self, env, *, model: str, max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None, top_p: float = 0.9,
                 max_trajectory_length: Optional[int] = None,
                 reasoning_effort: Optional[str] = None,
                 one_call_per_step: bool = False,
                 client_password: str = "password", **kwargs):
        super().__init__(env, model=model, **kwargs)
        from mm_agents.agent import PromptAgent
        # ★ 기본값은 PromptAgent 선언값(1500 / 3). 예외는 벤더가 강제하는 두 개뿐:
        #     temperature — PromptAgent 는 0.5 인데 gpt-5.6 이 거부한다
        #                   (`does not support 0.5 ... Only the default (1)`) → 1.0 전송.
        #     top_p       — gpt 분기가 payload 에서 제거하므로 무슨 값이든 무시된다.
        #   즉 이 두 개는 우리 선택이 아니라 벤더 제약이다. 나머지는 손대지 않는다.
        if max_tokens is None:
            max_tokens = MAX_TOKENS if ALIGN_LEGACY else STOCK_LUNA_MAX_TOKENS
        if max_trajectory_length is None:
            max_trajectory_length = HISTORY_STEPS if ALIGN_LEGACY else STOCK_LUNA_TRAJ
        if temperature is None:
            temperature = TEMPERATURE if ALIGN_LEGACY else VENDOR_TEMPERATURE
        if reasoning_effort is None and ALIGN_LEGACY:
            reasoning_effort = REASONING_EFFORT     # None = 필드 미전송 = 벤더 기본
        _vp = {"temperature": temperature}
        self._a = PromptAgent(
            platform="ubuntu", model=model, max_tokens=max_tokens,
            top_p=top_p, **_vp,
            action_space="pyautogui", observation_type="screenshot",
            max_trajectory_length=max_trajectory_length, client_password=client_password)
        # PromptAgent 시그니처를 건드리지 않고 속성으로 넘긴다(extra_user_text 와 같은 방식).
        self._a.reasoning_effort = reasoning_effort
        self.one_call_per_step = bool(one_call_per_step)
        if self.one_call_per_step:
            # ★ stock 프롬프트가 **배치를 권장**한다. 실행기에서만 잘라내면 모델은 계속
            #   여러 줄을 뱉고 매 턴 교정 메시지를 받아 스텝을 낭비한다. 지시도 같이 바꾼다.
            _old = ("Return one line or multiple lines of python code to perform the "
                    "action each time, be time efficient.")
            _new = "Return exactly ONE pyautogui call per response."
            if _old in self._a.system_message:
                self._a.system_message = self._a.system_message.replace(_old, _new, 1)
            else:
                logger.warning("stock 프롬프트의 배치 권장 문구를 못 찾았다 — "
                               "문구가 바뀐 것인지 확인할 것 (one_call_per_step)")

    def attach_user_text(self, text: str) -> None:
        # 매 스텝 덮어쓴다 — 빈 문자열이면 지워져서 지난 결과가 남지 않는다.
        self._a.extra_user_text = (text + "\n\n") if text else ""

    def reset(self) -> None:
        self._a.extra_user_text = ""
        self._a.reset(_logger=logger, vm_ip=getattr(self.env, "vm_ip", None))

    def predict(self, instruction: str, obs: Dict[str, Any]) -> StepOutput:
        self._note_image(obs)
        response, actions = self._a.predict(instruction, obs)
        return StepOutput(response or "", list(actions or []), {})

    def _note_image(self, obs) -> None:
        """실제로 보낸 이미지 크기를 재둔다.

        ★ PromptAgent 는 스크린샷을 리사이즈하지 않고 raw PNG 를 그대로 보낸다.
          Claude 만 send_width(1280)로 줄여 보내므로 이 축은 현재 모델마다 다르다.
          '다르다'를 기록으로 남기려면 추정이 아니라 실측이어야 한다.
        """
        try:
            import io
            from PIL import Image
            shot = obs.get("screenshot") if isinstance(obs, dict) else None
            if shot:
                self._image_wh = list(Image.open(io.BytesIO(shot)).size)
        except Exception:       # 크기를 못 읽어도 실험은 계속된다
            pass

    def conditions(self) -> Dict[str, Any]:
        a = self._a
        _eff = getattr(a, "reasoning_effort", None)
        d = {
            "history_steps": getattr(a, "max_trajectory_length", None),
            # ★ 단위가 Haiku/Kimi 와 다르다 — 스크린샷 수가 아니라 (스샷+액션+생각) 묶음 수.
            "history_unit":  "trajectory_bundles",
            "max_tokens":    getattr(a, "max_tokens", None),
            "temperature":   getattr(a, "temperature", None),
            # gpt 분기가 payload 에서 top_p 를 제거하므로 실제로는 전송되지 않는다.
            "top_p":         None,
            "image_sent_wh": getattr(self, "_image_wh", None),
            # ★ thinking 은 "확장 추론이 꺼져 있나" 라는 **공통 의미**로 맞춘다.
            #   Haiku=파라미터 미전송 / Kimi=thinking False / Luna=reasoning_effort "none".
            #   셋 다 '확장 추론 없음' 이므로 False 로 보고하고, 원본 값은 따로 남긴다.
            # ★ thinking 은 "확장 추론이 꺼져 있나" 라는 **공통 의미**로 맞춘다.
            #   Haiku=파라미터 미전송 / Kimi=thinking False / Luna=reasoning_effort "none".
            #   ★ 미지정(None)은 False 가 아니라 **None** 이다 — "꺼짐"이 아니라
            #     "통제 안 됨"이고, 실측상 같은 요청에서도 추론 토큰이 9/0 으로 흔들린다.
            #     이걸 False 로 찍으면 통제되지 않은 조건을 정렬됐다고 오독하게 된다.
            "thinking":      (None if _eff is None else str(_eff).lower() != "none"),
            "reasoning_effort": _eff,
            "reasoning_elicitation": "forced_reason_line",   # '## Reason:' 강제 패치
            "tool_channel":  "user_turn",
            "one_call_per_step": getattr(self, "one_call_per_step", None),
            "memory_arm":    (self.emu.memory_arm if getattr(self, "emu", None) else None),
        }
        d.update(_sp_fingerprint(getattr(a, "system_message", "")))
        if getattr(self, "emu", None):
            d.update(self.emu.prompt_fingerprint())
        return d


def kimi_effective_history(declared):
    """Kimi 가 **실제로** 받는 스크린샷 수를 선언값에서 계산한다.

    벤더 kimi_agent.py:341 의 조건이 엄격 부등호다:

        if i > len(self.actions) - self.max_image_history_length:

    그래서 에피소드가 선언값보다 길어지면 붙는 이미지는 항상 `declared - 1` 장이다.
    Claude 의 _trim_images(agent_mcp.py:496)는 정확히 only_n_recent_images 장을 남기고,
    Luna 의 observations[-max_trajectory_length:] 도 정확히 그 수를 남긴다.

    즉 선언값을 그대로 지문에 적으면 Kimi 만 한 장 적게 보면서 "같다"고 기록된다.
    history_steps 는 MUST_MATCH 축이므로 이건 조용한 불일치다. 어댑터는 +1 을 줘서
    실효값을 맞추고, 지문은 이 함수로 실효값을 적는다. **테스트도 같은 함수를 쓴다**
    (compare_conditions.known_axes() 와 같은 이유 — 출처가 둘이면 조용히 어긋난다).
    """
    if isinstance(declared, bool) or not isinstance(declared, int):
        return declared
    return declared - 1 if declared > 0 else declared


class KimiAdapter(StepAgentAdapter):
    """Moonshot KimiAgent. --thinking 필수, 상대좌표 → 절대좌표 투영.

    ★ 좌표 투영 기준을 매 스텝 **실제 스크린샷 크기**로 맞춘다.
      KimiAgent 는 생성자에서 받은 고정 screen_size(기본 1920×1080)로 x*W 를 하므로,
      VM 창을 리사이즈해 게스트 해상도가 바뀌면 우측으로 갈수록 클릭이 오버슛한다.
      (Luna 는 절대좌표라 면역.) 벤더 파일을 고치지 않고 여기서 바로잡는다.
    """

    name = "KimiAgent(text)"
    tag = "kimi"

    # ★ 벤더 off-by-one (실측). kimi_agent.py:341 의 조건은
    #     `if i > len(self.actions) - self.max_image_history_length:`
    #   로 **엄격 부등호**라, 6 을 주면 실제로 붙는 이미지는 5장이다.
    #   Claude 의 _trim_images 는 정확히 6장을 남기고, Luna 의 [-6:] 도 6장이다.
    #   즉 6 을 그대로 주면 조건 지문은 6 이라고 적는데 Kimi 만 5장을 본다 —
    #   ★ 2026-09-25 이후로는 **보정하지 않는다.** 모델 간 문맥 길이를 맞추는 것이
    #   성립하지 않는다는 결론이 났으므로(세는 대상이 다르다), 선언값은 벤더 스톡 3 을
    #   그대로 쓰고 실효값 2 를 지문에 적는다. ALIGN_LEGACY=1 일 때만 예전처럼 +1 한다.
    #   conditions() 는 선언값이 아니라 **실효값(선언값-1)** 을 적는다 — 이건 벤더
    #   off-by-one 을 정직하게 기록하는 것이라 정렬 폐기와 무관하게 유지한다.
    def __init__(self, env, *, model: str, max_steps: int = 30,
                 max_image_history_length: Optional[int] = None,
                 coordinate_type: str = "relative",
                 max_tokens: Optional[int] = None, top_p: float = KIMI_TOP_P,
                 temperature: Optional[float] = None, one_call_per_step: bool = False,
                 thinking: bool = True, password: str = "password", **kwargs):
        super().__init__(env, model=model, **kwargs)
        # ★ 기본값은 KimiAgent 선언값(4096 / 3 / top_p 0.95 / temperature 1 / thinking True).
        #   thinking=True 가 스톡이고, 그 상태에서 벤더는 temperature=1 만 허용한다.
        #   (예전 0.6 은 thinking 을 끄려던 데서 나온 연쇄였다 — thinking 을 끄면 벤더가
        #    0.6 만 허용하기 때문. 스톡으로 돌리면 그 연쇄가 통째로 사라진다.)
        if max_tokens is None:
            max_tokens = MAX_TOKENS if ALIGN_LEGACY else STOCK_KIMI_MAX_TOKENS
        if max_image_history_length is None:
            max_image_history_length = (HISTORY_STEPS + 1 if ALIGN_LEGACY
                                        else STOCK_KIMI_IMG_HISTORY)
        if temperature is None:
            temperature = TEMPERATURE if ALIGN_LEGACY else VENDOR_TEMPERATURE
        _vp = {"temperature": temperature}
        from mm_agents.kimi.kimi_agent import KimiAgent
        self._a = KimiAgent(
            model=model, max_steps=max_steps,
            max_image_history_length=max_image_history_length, platform="ubuntu",
            action_space="pyautogui", observation_type="screenshot",
            coordinate_type=coordinate_type,
            max_tokens=max_tokens, top_p=top_p, **_vp,
            screen_size=(int(getattr(env, "screen_width", 1920) or 1920),
                         int(getattr(env, "screen_height", 1080) or 1080)),
            password=password, thinking=thinking)
        self._thinking = bool(thinking)
        self.one_call_per_step = bool(one_call_per_step)
        if not self._thinking:
            self._disable_native_reasoning()

    def _disable_native_reasoning(self) -> None:
        """payload 에 thinking={"type":"disabled"} 를 끼워 넣는다 (벤더 파일 무수정).

        ★ 왜 필요한가 (실측) — KimiAgent 의 `thinking` 인자는 **시스템 프롬프트와 파서만**
          바꾼다. payload 에 추론 제어 파라미터가 없어서, thinking=False 로 둬도 API 는
          reasoning_content 를 계속 채워 보냈다(스모크 실측 1914자). 그 상태로 "추론 껐다"
          고 기록하면 거짓 정렬이 된다.
        ★ 무엇이 진짜 끄는가 (probe_kimi_thinking) —
            thinking={"type":"disabled"}  → reasoning_content 0자
            reasoning_effort="none"       → reasoning_content 0자
          둘 다 temperature 0.6 을 요구한다. 앞의 것은 API 가 스키마를 명시적으로
          검증하므로(bool 을 보내면 "expected type object") 이쪽을 쓴다.
        """
        _orig = self._a.call_llm

        def _call(payload, model, _o=_orig):
            p = dict(payload)
            p["thinking"] = {"type": "disabled"}
            return _o(p, model)

        self._a.call_llm = _call

    def reset(self) -> None:
        self._a.reset(_logger=logger)

    def predict(self, instruction: str, obs: Dict[str, Any]) -> StepOutput:
        self._sync_screen_size(obs)
        response, actions, cot = self._a.predict(instruction, obs)
        self._note_reasoning(response)
        return StepOutput(self._as_text(response), list(actions or []), dict(cot or {}))

    def _note_reasoning(self, response: Any) -> None:
        """모델이 **실제로** 네이티브 추론을 했는지 잰다.

        ★ 왜 플래그를 믿으면 안 되는가 (실측) — KimiAgent 의 `thinking` 인자는
          시스템 프롬프트와 파서만 바꾼다. payload 에는 추론 제어 파라미터가 없고,
          thinking=False 로 둬도 API 는 reasoning_content 를 계속 채워 보낸다
          (실측: ON 2819자 / OFF 1914자 — 줄기만 하고 0 이 아니다).
          플래그를 thinking 축에 그대로 쓰면 '추론 껐다'는 거짓 ✓ 가 만들어진다.
        """
        if isinstance(response, dict):
            self._reasoning_chars = (getattr(self, "_reasoning_chars", 0)
                                     + len(str(response.get("reasoning_content") or "")))

    @staticmethod
    def _as_text(response: Any) -> str:
        """KimiAgent 의 response 는 API 메시지 **dict** 다(문자열 아님).

        그대로 str() 하면 trajectory/summary 에 파이썬 dict 리터럴이 박혀서 읽을 수
        없고, 종료 신호(DONE/FAIL)를 산문에서 찾는 검사도 걸리지 않는다.
        추론(reasoning_content) + 본문(content) 순서로 평문화한다.
        """
        if isinstance(response, dict):
            parts = [str(response.get(k, "") or "").strip()
                     for k in ("reasoning_content", "content")]
            return "\n\n".join(p for p in parts if p)
        return str(response or "")

    def _sync_screen_size(self, obs: Dict[str, Any]) -> None:
        try:
            import io
            from PIL import Image
            shot = obs.get("screenshot") if isinstance(obs, dict) else None
            if shot:
                size = Image.open(io.BytesIO(shot)).size
                self._a.screen_size = size
                self._image_wh = list(size)     # 전송 이미지 크기 실측(조건 지문용)
        except Exception:       # 크기를 못 읽으면 생성자 값 유지 (기존 동작)
            pass

    def conditions(self) -> Dict[str, Any]:
        a = self._a
        d = {
            # 선언값이 아니라 실효값. kimi_effective_history() 주석 참조 —
            # 지문은 "무엇을 줬나" 가 아니라 "모델이 실제로 무엇을 봤나" 를 적는다.
            "history_steps": kimi_effective_history(
                getattr(a, "max_image_history_length", None)),
            "history_unit":  "screenshots",
            "max_tokens":    getattr(a, "max_tokens", None),
            "temperature":   getattr(a, "temperature", None),
            # ★ 세 모델 중 top_p 가 실제로 걸리는 것은 Kimi 뿐이다(벤더 기본 0.95).
            "top_p":         getattr(a, "top_p", None),
            "image_sent_wh": getattr(self, "_image_wh", None),
            # thinking=False 면 payload 에 thinking={"type":"disabled"} 가 들어가
            # 네이티브 추론이 **실제로** 0 이 된다. 그 검증은 native_reasoning_chars.
            "thinking":      getattr(self, "_thinking", None),
            "kimi_thinking_flag": getattr(a, "thinking", None),
            "native_reasoning_chars": getattr(self, "_reasoning_chars", 0),
            "reasoning_elicitation": "native",       # ◁think▷ / reasoning_content
            "tool_channel":  "instruction_prefix",
            "one_call_per_step": getattr(self, "one_call_per_step", None),
            "memory_arm":    (self.emu.memory_arm if getattr(self, "emu", None) else None),
            "coordinate_type": getattr(a, "coordinate_type", None),
        }
        d.update(_sp_fingerprint(getattr(a, "system_prompt", "")))
        if getattr(self, "emu", None):
            d.update(self.emu.prompt_fingerprint())
        return d


_ADAPTERS = {"claude": ClaudeAdapter, "gpt": LunaAdapter, "kimi": KimiAdapter}


def build_agent(model: str, env, *, tools: List[str], memory: bool = False,
                memory_arm: Optional[str] = None, memstore_dir: Optional[str] = None,
                inject_popup: bool = False, approval: bool = False,
                result_dir: Optional[str] = None, max_steps: int = 30,
                sleep_after_execution: float = 0.0,
                approval_input=input, verbose: bool = True,
                claude_kwargs: Optional[Dict[str, Any]] = None,
                **kwargs) -> BaseAgent:
    """검증 → 어댑터 생성. 지원하지 않는 조합이면 여기서 ValueError 로 멈춘다."""
    wanted = list(tools)
    if approval:
        wanted.append("approval")
    plan = validate_request(model, tools=wanted, memory=memory,
                            memory_arm=memory_arm, inject_popup=inject_popup)
    spec = MODEL_SPECS[plan["model_key"]]
    if not os.environ.get(spec["api_key_env"]):
        raise ValueError(f"✗ {spec['api_key_env']} 가 없습니다 (.env 확인)")

    if plan["family"] == "claude":
        ck = dict(claude_kwargs or {})
        ck.setdefault("tools", tuple(t for t in wanted if t in ("bash", "editor", "mcp")))
        ck.setdefault("enable_memory", memory)
        ck.setdefault("memstore_dir", memstore_dir)
        ck.setdefault("read_mode", memory_arm or "faithful")
        ck.setdefault("inject_popup", inject_popup)
        ck.setdefault("approval_mode", "interactive" if approval else "off")
        ck.setdefault("approval_result_dir", result_dir)
        ck.setdefault("api_key", os.environ.get(spec["api_key_env"]))
        return ClaudeAdapter(env, model=plan["model_id"], verbose=verbose, **ck)

    emu = EmuToolLayer(
        enable_bash="bash" in plan["tools_enabled"],
        memstore_dir=memstore_dir,
        memory_arm=(memory_arm if memory else None),
        enable_approval="approval" in plan["tools_enabled"],
        vm_exec=make_vm_exec(env) if "bash" in plan["tools_enabled"] else None,
        approval_input=approval_input, result_dir=result_dir, verbose=verbose)

    cls = _ADAPTERS[plan["family"]]
    extra = {"max_steps": max_steps} if plan["family"] == "kimi" else {}
    return cls(env, model=plan["model_id"], emu=emu, unsupported_requested=[],
               sleep_after_execution=sleep_after_execution,
               verbose=verbose, **extra, **kwargs)
