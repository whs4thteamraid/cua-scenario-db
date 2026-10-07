# claude_cua — Claude Computer Use 어댑터

업스트림의 `mm_agents/anthropic` 은 Claude 에게 `computer` 툴만 준다(화면 GUI 만). 이
모듈은 툴 세트를 런타임에 고를 수 있게 해서, **GUI 만 열린 에이전트와 셸까지 열린
에이전트를 같은 코드로 바꿔 가며** 돌릴 수 있게 한다.

```
tools=("computer",)                 GUI 만
tools=("computer","bash")           셸 직통까지
tools=("computer","bash","editor")  + 파일 편집
```

업스트림 `mm_agents/anthropic/` 은 건드리지 않는다. 이 폴더는 전부 신규 파일이다.

## 파일

| | |
|---|---|
| `agent.py` | `ClaudeCUAAgent` — Computer Use 루프를 OSWorld VM 에 물린 본체 |
| `agent_mcp.py` | `MCPClaudeCUAAgent` — MCP 툴 표면 추가 |
| `agent_memory.py` | `MemoryClaudeCUAAgent` — 기억 툴 추가 |
| `agent_mcp_memory.py` | `MemoryMCPClaudeCUAAgent` — 둘 다 |
| `agent_system_prompt_mcp_memory.py` | `SystemPromptMCPMemoryClaudeCUAAgent` — 위에 시스템 프롬프트 고정까지. `MODEL_SPECS` 의 `haiku` 가 쓰는 것 |
| `memory_backend.py` | `HostMemstoreTool` — 공식 memory 툴(`memory_20250818`)의 호스트측 저장 백엔드. 기억이 호스트 파일로 남아 시행 사이에 들여다볼 수 있다 |
| `popup.py` | 합성 팝업 렌더러. 모델에게 보내는 **스크린샷에 합성**하며, VM 안에 실제로 창을 띄우지 않는다 |

## 툴을 VM 으로 어떻게 보내는가

| 툴 | 경로 |
|---|---|
| `computer` | `env.step(pyautogui)`. 모델에 선언한 폭(기본 1280)과 VM 실제 프레임버퍼(`env.screen_width/height`, 기본 1920×1080) 사이에서 좌표를 스케일하고, 결과로 새 스크린샷을 돌려준다 |
| `bash` | `controller.execute_python_command` 로 감싸 돌리고 stdout 을 돌려준다 |
| `editor` | `controller.get_file` 과 같은 경로의 파이썬 실행 (view·create·str_replace·insert) |

- `tool_choice.disable_parallel_tool_use=True` — 턴당 1툴. `bash` 와 `computer` 가 한 턴에
  섞이면 `tool_result` 순서가 꼬인다.
- `only_n_recent_images` — 최근 N 장 스크린샷만 유지한다(컨텍스트·비용).

## 쓰는 법

이 모듈을 직접 부르지 않는다. `mm_agents/adapters/agents.py` 의 `MODEL_SPECS` 가 모델 키와
에이전트 클래스를 묶고, `redteam/run_cua.py` 가 그것을 실행한다. 웹 UI 의 모델 버튼도 같은
표에서 나온다. API 키는 저장소 루트 `.env` 의 `ANTHROPIC_API_KEY` 에서 읽는다.

## 알려진 한계

- **`bash` 는 호출마다 새 셸이다.** cwd·환경변수가 이어지지 않으므로 `&&` 로 묶거나
  절대경로를 쓴다.
- `editor` 는 최소 구현(view·create·str_replace·insert)이다.
- 모델 ID 는 computer-use 툴 세대를 지원하는 것이어야 한다. `computer-use-2025-11-24`
  (`computer_20251124`)를 기본으로 쓰고, 안 되면 `computer-use-2025-01-24`
  (`computer_20250124`)로 내려간다. 그 이전 ID 는 404 가 난다.
