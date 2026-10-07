# 하네스 계약

시나리오가 실행기에게 **기대할 수 있는 것**과, 반대로 **직접 해야 하는 것**의 경계.
이 경계를 명시하는 이유는, 흐릿하게 두면 시나리오마다 VM 생성·에이전트 생성·판정을
다시 구현하게 되고 그때부터 결과를 서로 비교할 수 없게 되기 때문이다.

참조 구현: `redteam/run_cua.py` 의 `Session` (OSWorld 포크 안).

## 실행기가 제공하는 것

| 호출 | 하는 일 |
|---|---|
| `Session(model=…, vmx=…, tools=…, memory_arm=…, approval_mode=…)` | VM 한 대를 잡는다. 모델·팔 설정은 `MODEL_SPECS` 한 곳에서 온다 |
| `prepare(task, result_dir=…, restore=…)` | 시작 상태를 만들고 `step_000.png` 를 남긴다 |
| `make_agent(result_dir=…, max_steps=…)` | **에피소드마다 새 에이전트** → 대화 단절이 구조적으로 보장된다 |
| `execute(agent, instruction, …)` | 에피소드 하나를 돌리고 trajectory 를 남긴다 |
| `run(task, …)` | 위 넷 + 평가 + `summary.json` |
| `shell(cmd)` | VM 안에서 셸 명령. **에피소드 사이**의 조작·관측용 |

## 시나리오가 직접 해야 하는 것

실행기는 **몇 판을 어떤 순서로 돌릴지 모른다.** 아래는 전부 `run_chain.py` 몫이다.

- 페이즈 순서와 페이즈 사이의 경계 처리
- 공격 표면 배치 (`shell()` 로)
- **판정** — 호스트측에서 파일을 읽어서 한다. 모델 자기보고를 쓰지 않는다
- 팔(arm) 사이의 차이를 만드는 것
- 집계와 조건부확률

## `restore` 의 의미 — 여기서 사고가 난다

```
restore="<스냅샷명>"   그 스냅샷으로 되돌리고 시나리오 config 적용
restore=None          VM 을 건드리지 않음.  config 도 적용되지 않음
```

`DesktopEnv.reset()` 은 `is_environment_used` 가 True 일 때만 스냅샷을 되돌린다.
그런데 그 플래그는 `env.step()` 과 config 셋업에서만 켜진다 — `Session.shell()` 과
에뮬 bash·memory 는 `env.controller` 를 **직접** 부르므로, VM 을 실제로 바꿔놓고도
플래그가 False 로 남는다. 그 상태로 `reset()` 을 부르면
`"Environment is clean, skipping snapshot revert"` 라며 **조용히 건너뛴다.**

결과: 이전 페이즈의 파일이 살아있는 채로 다음 페이즈가 시작되고, 로그는 정상으로 보인다.
그래서 참조 구현은 `restore` 가 명시되면 플래그를 강제로 True 로 올린다.

**페이즈 2 를 "되돌리지 않고 config 만 적용" 하는 방법은 없다.** 둘 중 하나다.
필요한 조작은 `shell()` 로 직접 한다.

## 시나리오를 어디에 두어야 하나

`run_chain.py` 는 레포 루트를 `Path(__file__).resolve().parents[2]` 로 자가탐색한다.
`.resolve()` 가 심링크를 따라가므로 **실제 파일이 하네스 트리 안에 있어야** 한다.

| 배치 | 되는가 |
|---|---|
| `OSWorld/security_scenarios/<이름>/run_chain.py` | ✅ |
| 트리 밖에 두고 트리 안으로 심링크 | ❌ ROOT 가 원본 위치를 가리켜 `desktop_env` import 실패 |
| 트리 밖에 복사본 | ❌ 같은 이유 |

(실측 2026-10-04)

## 새 실행기로 갈아탈 때

위 6개 호출과 `restore` 의 두 가지 의미만 재현하면 시나리오는 그대로 돈다.
`spec/` 의 판정 규약은 실행기에 의존하지 않는다.

## 시나리오 체크리스트

웹 UI 에 얹으려면 아래를 맞춰야 한다. 전부 실제로 터져 가며 확인한 것이다.

```
□ 위치   OSWorld/security_scenarios/<이름>/run_chain.py   (위의 배치 표)
□ 플래그 run_chain.py 가 --model 과 --trials 를 받는다    ← 없으면 UI 가 버튼을 잠근다
□ 팔     모듈 수준에 ARMS = ("A", "B", ...)               ← UI 가 소스에서 읽어 칩을 만든다
□ 과업   task/scenario JSON 에 evaluator 블록             ← 없으면 VM 부팅 직후 KeyError
□ 결과   _results/<모델>/<팔>/t<N>/summary.json
         _results/<모델>/<팔>/t<N>/p1/trajectory.jsonl
         _results/<모델>/<팔>/t<N>/p1/step_*.png
□ 표     summary.json 에 host_rows: [[라벨, 값, 강조], …]  ← 없으면 리포트가 남의 시나리오 항목을 보여준다
□ 판정   summary.json 에 verdict / hit_cap
```

### evaluator 블록은 빠뜨리기 쉽다

판정을 `run_chain` 이 호스트측에서 직접 하더라도 **이 블록은 있어야 한다.**
`DesktopEnv._set_evaluator_info` 가 기본값 없이 `task_config["evaluator"]` 를 읽기
때문이다. VM 은 정상 부팅하고 그 다음 줄에서 `KeyError` 로 죽는다.

```json
"evaluator": {
  "func": "check_include_exclude",
  "result":   {"type": "vm_command_line",
               "command": ["bash", "-c", "test -f <경로> && echo OK || echo NO"]},
  "expected": {"type": "rule", "rules": {"include": ["OK"], "exclude": []}}
}
```

### 팔 이름은 UI 가 읽는다

`ARMS` 를 안 두면 공격 팔 칩이 숨고, 두면 그 이름이 그대로 `--arm` 으로 들어간다.
서버도 스캔된 팔이 아닌 값은 400 으로 막는다. 예전에는 한 시나리오의 팔 이름
(`VULN`/`DEFENSE`/`STEAL-OFF`)이 UI 에 하드코딩돼 있어서, 다른 시나리오를 얹으면
엉뚱한 값이 전달됐다.

### 가장 싼 검증

`selftest_ping` 이 위 규약을 전부 만족하는 최소 예제다. 새 시나리오를 붙이기 전에
그것부터 돌려 환경을 확인하고, 붙인 뒤에는 `--smoke` 로 메커니즘만 먼저 본다.
