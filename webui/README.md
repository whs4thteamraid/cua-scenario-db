# webui — 시나리오 실행 UI

옵션을 버튼으로 고르고 실행하면 VM 화면이 실시간으로 뜨고, 끝나면 결과 요약이 나온다.
**표준 라이브러리만 쓴다** — 설치 단계를 0 으로 두려고 의존성을 넣지 않았다.

```bash
cd <저장소>/cua-scenario-db
python3 webui/app.py --vmx vmware_vm_data/Ubuntu0/Ubuntu0.vmx
# → http://127.0.0.1:8787
```

쓰는 법은 UI 안의 **시나리오 설명 보기**(`/guide`) 에 있다.

결과만 정적 HTML 로 뽑을 때(서버 불필요, 파일 하나로 휴대):

```bash
cd <저장소>/cua-scenario-db
python3 webui/render.py OSWorld/security_scenarios/<시나리오>/_results \
  -o report.html --embed
```

## 파일

| | |
|---|---|
| `app.py` | 서버와 페이지 전부 — 시나리오 탐색·실행·화면 중계·결과 표시 |
| `render.py` | `_results/` 를 정적 HTML 리포트로 (서버 없이) |
| `analyze.py` | 실행 로그를 사용자 API 키로 한 번 호출해 읽기 쉬운 요약으로 |

## 설계 원칙 세 개

1. **판정은 코드가, 표시만 웹이.** `run_chain` 이 호스트측 파일로 내린 판정을 그대로 읽는다.
   웹도 렌더러도 판단하지 않고 **LLM 은 판정 경로에 들어가지 않는다.** 실행이 끝나면
   자동으로 붙는 요약(`analyze.py`)은 이미 확정된 판정을 설명만 하고 바꾸지 않는다.
2. **라이브 화면은 시행이 이미 쓰는 `step_*.png` 를 서브한다.** 게스트를 폴링하거나 VM 에
   무엇을 설치하지 않는다 — `FOCUS-MISDELIVERY` 처럼 **창 z-order 가 측정 대상**인
   시나리오는 게스트 환경을 건드리는 순간 측정이 오염된다.
3. **게스트 `:5000` 으로 일반 프록시를 열지 않는다.** 그 서버에는 명령 실행 엔드포인트가
   있어서, 프록시를 열면 인증을 통과한 누구나 VM 안에서 임의 명령을 돌릴 수 있다.

## 안전장치

| | 동작 |
|---|---|
| 시행 수 상한 | `MAX_TRIALS = 2`. 더 요청해도 깎인다 |
| 동시 실행 차단 | VM 1 대 — 실행 중 재요청은 `busy` 로 거부 |
| 입력 검증 | 탐색된 시나리오·모델 목록에 없으면 400 |
| 경로 탈출 | `/files/` 는 결과 트리 밖을 403 |
| 중단 | `POST /api/kill` 또는 UI 의 「중단」 |

## 시나리오 버튼은 자동으로 생긴다

`OSWorld/security_scenarios/<이름>/run_chain.py` 를 서버가 시작할 때 한 번 스캔한다.
폴더를 넣고 **UI 를 다시 띄우면** 목록에 나타난다.

어떤 옵션 칸이 보일지는 그 `run_chain.py` 가 실제로 선언한 플래그에서 정해진다 —
`--read-mode` 를 받지 않는 시나리오에서는 「메모리 조회 방식」 칸이 아예 보이지 않고,
`--smoke` 가 없으면 「테스트」 모드가 사라지는 식이다. 규격은
[../docs/SCENARIO_DB.md](../docs/SCENARIO_DB.md) 에 있다.

## 모델 버튼도 자동으로 늘어난다

`mm_agents/adapters/agents.py` 의 `MODEL_SPECS` 를 단일 출처로 읽는다. 모델을 추가하려면
**그 표에 항목 하나만** 넣으면 UI 에 버튼이 생긴다 — webui 코드는 손대지 않는다.

```python
"sonnet": {
    "model_id": "claude-sonnet-4-5",
    "family": "claude", "api_key_env": "ANTHROPIC_API_KEY",
    "agent": "claude_cua.SystemPromptMCPMemoryClaudeCUAAgent",
    "native": {"computer","bash","editor","mcp","memory","approval","popup"},
    "arms": ("faithful","controlled","inject"),
},
```

`MODEL_SPECS` 를 못 읽으면(하네스 가상환경을 못 찾는 등) 내장 기본 목록으로 폴백하고,
그 사실을 화면에 알린 뒤 UI 는 그대로 돈다. 벤더 문서의 모델 ID 를 UI 에서 직접 넣어
임시로 추가할 수도 있다(검증되지 않은 조합일 수 있다).

## 범위 밖

계정·비밀번호·API 키를 **보관하는 기능은 두지 않았다.** 키는 저장소 루트의 `.env` 에서
읽고 그 키로 호출한 결과만 띄운다. 여러 사람이 함께 쓰는 공용 인스턴스로 올리는 용도가
아니라 셀프호스팅용이다. 보조 서버 포트와 VM 제어 포트는 바깥으로 내보내지 말 것.
