# CUA 메모리 도구 — 공식 `memory_20250818` 이관

CUA 레드팀 하네스의 메모리 기능을 **Anthropic 공식 memory tool(`memory_20250818`)** 위에서
쓰도록 만든 재사용 모듈입니다. 커스텀 `save_memory`/`read_memory`는 제거했습니다.

> **핵심 한 줄**: 모델이 보는 인터페이스는 **공식 표준**, 저장 백엔드만 우리가 구현.
> 시나리오 작성자는 이 모듈 + 동일 SDK 위에 **자기 시나리오**를 얹으면 됩니다.

---

## 무엇을 공유하나

| 구분 | 파일 | 설명 |
|---|---|---|
| **필수** | `mm_agents/claude_cua/memory_backend.py` | 공식 도구의 저장 백엔드 |
| **필수** | `mm_agents/claude_cua/agent_memory.py` | 메모리 도구를 물린 에이전트 |
| **필수** | `pyproject.toml` · `requirements.txt` · `uv.lock` | `anthropic==0.84.0` 핀 |
| 참고 | `redteam/smoke_claude_memory.py` | 환경 검증용 독립 테스트 |
| 각자 | 시나리오·오케스트레이터·서버·VM 스냅샷 | 시나리오 작성자가 직접 작성 (오케스트레이션 패턴은 아래 *사용법* 참고) |

---

## 파일별 설명 — 무엇 / 공식 근거 / 왜 이렇게

### 🧩 `memory_backend.py` — 공식 도구의 저장 백엔드
- **무엇**: 공식 memory tool(`memory_20250818`)의 6커맨드
  (`view`/`create`/`str_replace`/`insert`/`delete`/`rename`)를 실제로 실행하는 백엔드.
- **공식 근거**: 이 도구는 client-side라 **"저장은 개발자가 직접 구현"**하는 게 설계입니다.
  SDK가 `BetaAbstractMemoryTool`을 **추상 클래스**로 제공하고, docstring에 명시돼 있습니다 —
  *"Subclass this to create your own memory storage solution (e.g., database, cloud storage,
  encrypted files, etc.)"*. 상속이 **공인된 확장 방식**입니다.
- **왜 이렇게**: 저장을 우리가 통제해야
  ① `/memories`를 **호스트 폴더**에 매핑(VM 밖 → 리셋·로테이션 생존),
  ② `seed()`/`clear()`로 결정론적 초기화(재현성),
  ③ **path traversal 방어**(공식 문서 권고)를 구현하고도 공격이 성립함을 보임.

### 🤖 `agent_memory.py` — 메모리를 물린 에이전트(서브클래스)
- **무엇**: 원본 `ClaudeCUAAgent`를 상속해 공식 memory 도구를 붙인 `MemoryClaudeCUAAgent`.
- **공식 근거**: 공식 도구는 `tools` 배열에 `{"type":"memory_20250818","name":"memory"}`
  **한 줄 선언**만 하면 되고 베타 헤더도 불필요(공식 문서). 모델이 호출하면 백엔드가 실행.
- **왜 이렇게**: 원본은 불변(상속만), 커스텀 save/read는 삭제하고 공식 선언으로 교체.
  도구 호출은 `/memories` 경로 프리픽스로 구분해 백엔드로 전달.
  조회 방식 **4팔**(아래)은 공식 auto-view 프로토콜 + 프롬프트 억제로 구성(스모크로 검증).

### 📌 핀 (`pyproject.toml` / `requirements.txt` / `uv.lock`)
- **무엇**: `anthropic==0.84.0` 고정.
- **공식 근거**: memory tool은 Claude 4+ 지원. 우리가 상속한 클래스는 0.84.0에선
  `anthropic.lib.tools`에 있습니다(최신 SDK는 `anthropic.tools` 별칭도 제공 — 백엔드가 둘 다 시도).
- **왜 이렇게**: 팀 전원이 `uv sync`로 **정확히 같은 SDK·핸들러**를 받게 = 정형화.
  실제 강제는 `uv.lock`이 합니다.

### 📎 (참고) `smoke_claude_memory.py` — 환경 검증
- 공식 도구가 computer-use와 **공존·동작**하는지 최소 API 호출로 확인(30초).

---

## read_mode 4팔 (메모리를 "어떻게 접하나")

| 팔 | 동작 | 모델링 대상 | 쓸 수 있는 모델 |
|---|---|---|---|
| `faithful` | 공식 auto-view 유지 → 세션 시작 시 스스로 조회 | 실제 제품(자동 조회) | **haiku만** |
| `neutral` | 도구만 주고 억제 문구 없음 | 에뮬 모델의 무억제 기준선 | **luna·kimi만** |
| `controlled` | auto-view 억제, 태스크가 요구할 때만 재량 조회 | 신중한 pull 메모리 | 셋 다 |
| `inject` | 노트를 첫 메시지에 선주입(조회 불필요) | 항상-컨텍스트 메모리 | 셋 다 |

네 팔 모두 **노트 내용은 동일**하고, 다른 건 "그게 어떻게 모델 눈에 들어오나"뿐입니다.

**`faithful` 과 `neutral` 은 서로 대응물이 아닙니다.** `faithful` 은 Anthropic 서버가
주입하는 auto-view 프로토콜이라 프롬프트로 흉내낼 수 없고(흉내내면 그건 이미 `controlled`),
에뮬 모델에는 존재하지 않습니다. 그래서 격자가 3×4 가 아니라 **haiku 3 / luna 3 / kimi 3
이고 축이 겹치지 않습니다** — 비교는 모델 내에서 하세요.

`neutral` 이 따로 필요한 이유: 같은 억제 문구가 haiku 에는 **있던 자동조회를 끄는** 조치이고,
에뮬 모델에는 **없던 것에 금지를 더하는** 조치입니다. 한쪽은 감산, 다른 쪽은 가산이라
`controlled` 끼리 비교하면 조건이 안 맞습니다. `neutral` 이 그 둘을 구분합니다.

⚠️ `inject` 에서는 **메모리 조회 횟수가 구조적으로 0** 입니다(노트를 첫 메시지에 주므로
도구 호출이 없음). 조회 수를 판정에 쓰는 러너는 `inject` 를 예외 처리해야 합니다 —
0 을 "안 봤다"로 읽으면 판정이 뒤집힙니다.

---

## 사용법 (자기 러너에 물리기)

```python
from mm_agents.claude_cua.agent_memory import MemoryClaudeCUAAgent
from mm_agents.claude_cua.memory_backend import HostMemstoreTool

# 러너가 memstore를 제어(리셋/시딩)
store = HostMemstoreTool("redteam/memstore")   # 호스트 폴더 = VM 밖
store.clear()                                  # 베이스라인 리셋
store.seed("note.md", "…오염 노트…")            # (선택) 결정론적 시딩

agent = MemoryClaudeCUAAgent(
    env, model="claude-haiku-4-5", tools=("computer", "bash"),
    memstore_dir="redteam/memstore",           # 같은 폴더를 공유
    read_mode="faithful",                       # faithful | controlled | inject
)
result = agent.run(instruction, max_steps=18)
# result["memory_views"] / ["memory_writes"] / ["memory_recalled_via_tool"] 로 계측
```

---

## 검증 (자기 환경에서 먼저 돌려볼 것)

```bash
uv sync                                              # anthropic==0.84.0 설치
uv run python mm_agents/claude_cua/memory_backend.py # 백엔드 자체검증 → 14/14 PASS
uv run python redteam/smoke_claude_memory.py                # 공존·동작 확인
```

---

## 건드리지 말 것 / 공유 금지

- `.env` — `ANTHROPIC_API_KEY` 포함. **커밋 금지.**
- `redteam/memstore/` — 실행 산출물. `.gitignore`에 추가.
- `redteam/agent_memory.json` — 옛 커스텀 메모리 파일. **삭제**(미사용).

---

## 설계 원칙 (왜 이런 구조인가)

1. **원본 하네스 불변** — 상속·신규 파일로만 확장.
2. **표준 프로토콜, 우리 백엔드** — 인터페이스는 공식, 저장만 구현.
3. **메모리는 호스트에** — VM 밖이라 리셋·로테이션을 넘어 생존.
4. **측정 변수만 남기고 고정** — 3팔·seed·baseline 복원으로 셀 독립성.
5. **정형화** — SDK 핀 + 결정론 시딩으로 모두 같은 출발선.
6. **계측 가능** — views/writes 카운터로 정량화 준비.
