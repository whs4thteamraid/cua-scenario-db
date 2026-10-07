# 시나리오 DB — 시나리오를 이 레포에 넣는 규격

**한 문장.** 시나리오 폴더 하나 = `run_chain.py` 하나(+ 필요하면 `serve.py`). 웹 UI 와 명령줄이 같은 규격을 읽습니다.
실행 경로·명령어·결과 위치를 이 규격 하나로 맞춥니다. 시나리오가 자체 실행기를 따로 갖고 있으면 그 앞에
진입점을 두어 **번역만** 합니다(§3).

별도의 데이터베이스는 없습니다. "DB" 는 `OSWorld/security_scenarios/` 아래 폴더들과, 그 폴더들이 같은 방식으로
실행되고 같은 모양의 결과를 남긴다는 약속입니다. 웹 UI 는 그 폴더를 스캔해 버튼을 만들고, 실행 화면·로그·결과를
그 자리에서 보여 줍니다.

### 범위

clone → `.env` 에 API 키 → VM 이미지 → 웹 서버 기동 → 시나리오·모델·조건을 골라 실행. VM 은 헤드리스로 뜨고
화면·로그가 웹에 흐르며, 끝나면 그 실행의 로그와 시나리오 설명으로 짧은 요약을 만들어 보여 줍니다.

실행 결과는 `<시나리오>/_results/` 에만 남고 git 이 무시합니다. 결과 화면은 **이번 실행**의 시행별 판정·단계·화면·
증거까지 보여 주며, 시행을 누적한 비율(발화율·분모)이나 모델 비교는 만들지 않습니다.

## 1. 지금 들어 있는 시나리오

전체 목록은 루트 [README.md](../README.md) §1 에 있습니다. 단일 표면 시나리오는 전부 공용 드라이버(§3.5)로 돌고,
아래 넷은 자기 `run_chain.py` 를 갖습니다.

| 이름 | 조건 `--arm` | 보조 서버 | 실행 방식 | 실행 문서 |
|---|---|---|---|---|
| `SELFTEST-PING` | — | 없음 | `run_chain.py` 가 곧 실행기 (파이프라인 점검, 공격 아님) | 파일 머리말 |
| `FOCUS-MISDELIVERY` | `VULN` · `DEFENSE` · `STEAL-OFF` | 없음 | `run_chain.py` 가 곧 실행기 | [SCENARIO.md](../OSWorld/security_scenarios/FOCUS-MISDELIVERY/SCENARIO.md) |
| `MEM-BOUNDARY` | `unscoped-procedure-memory` · `scoped-memory-control` · `defense-enforced` · `empty-memory-baseline` | 없음 (랩 서버는 자체 러너가 관리) | 자체 러너 앞에 진입점 | [SCENARIO.md](../OSWorld/security_scenarios/MEM-BOUNDARY/SCENARIO.md) |
| `MEM-FALSEFAIL` | `deceived` · `honest` · `no_lure` · `ablated` · `true_failure` | `serve.py` | 자체 실행기 앞에 진입점 | [SCENARIO.md](../OSWorld/security_scenarios/MEM-FALSEFAIL/SCENARIO.md) |

## 2. 규격

### 2.1 이름

`<측정 표면>-<현상>`, **대문자·하이픈, 두 토큰**, 숫자 꼬리표 없음.

- 앞 토큰은 **무엇을 건드려 보는지**: `MEM`(기억) · `FOCUS`(창·포커스) · `NET` · `FS` · `SUPPLY` 처럼
  표면을 적습니다. 공격이 아닌 점검용은 `SELFTEST` 접두를 씁니다.
- 뒤 토큰은 **무엇이 발화하는지**: `MISDELIVERY`(오배송) · `BOUNDARY`(경계 침범) · `FALSEFAIL`(거짓 실패).
- 랩·제품 이름(온보딩, 특정 서비스명)이나 일련번호는 쓰지 않습니다 — 바깥 사람에게는 무엇을 재는지
  안 보이고, 번호는 같은 표면의 시나리오가 늘어날 때 뜻을 잃습니다.
- 폴더 이름은 UI 목록·명령줄·결과 경로·보조 서버 로그 이름에 그대로 쓰입니다.
- `summary.json` 의 `scenario` 값(시나리오 코드 안의 식별자)은 폴더 이름과 다를 수 있습니다
  (`FOCUS-MISDELIVERY` → `focus_misdelivery_001`, `MEM-BOUNDARY` → `onboarding_memory`,
  `MEM-FALSEFAIL` → `mem-falsefail-p1`·`-p2`).

### 2.2 위치와 발견

- `OSWorld/security_scenarios/<이름>/run_chain.py`. 실행기가 하네스 루트를 `Path(__file__).resolve().parents[2]`
  로 찾으므로 **폴더 깊이가 고정**입니다 — 다른 곳에 두거나 심링크만 걸면 import 가 깨집니다.
- 웹 UI 는 시작할 때 `*/run_chain.py` 를 **한 번** 스캔합니다. 시나리오를 새로 넣으면 UI 를 다시 시작하십시오.
- 소스의 `KIND = "chain"|"probe"|"selftest"` 한 줄로 목록에서 묶이는 자리가 정해집니다
  (없으면 폴더 모양으로 추정). 목록에 붙는 한 줄 소개는 `ABOUT.md` 의 **한 줄.** 문단에서 가져옵니다.
- 같은 폴더의 `ABOUT.md` 는 웹 UI 의 **시나리오 설명**(`/guide`) 탭에 그대로 렌더됩니다. 없으면 `SCENARIO.md`,
  그것도 없으면 `README.md` 를 씁니다. 공통 설명(도구·옵션·결과 읽는 법)은 [GUIDE.md](GUIDE.md) 입니다.

### 2.3 명령줄

모든 명령은 `cua-scenario-db/OSWorld/` 에서 실행합니다.

```bash
uv run python "security_scenarios/<이름>/run_chain.py" --model haiku --arm <조건> --trials 1
uv run python "security_scenarios/<이름>/run_chain.py" --smoke --model haiku        # API 키 없이 설정·환경 점검
```

| 플래그 | | 뜻 |
|---|---|---|
| `--model` | **필수** | 모델 키(`haiku` · `luna` · `kimi`) 또는 모델 ID |
| `--trials` | **필수** | 조건마다 반복 횟수 (웹 UI 는 상한 2, 명령줄은 제한 없음) |
| `--arm` | 권장 | `ARMS` 중 하나 또는 `all` |
| `--vmx` | 권장 | VM 설정 파일. 못 찾으면 `vmware_vm_data/*/*.vmx` 자동 탐색 |
| `--read-mode` | 선택 | 기억을 읽는 경로(`faithful` · `neutral` · `controlled` · `inject`). 선언하면 UI 가 모델별 선택지를 보여 줌 |
| `--smoke` | 권장 | API 키 없이 설정·환경을 점검 (VM 이 필요한지는 시나리오마다 다름 — 각 `SCENARIO.md` 참고) |
| `--out` | 선택 | 결과 루트. 기본 `<시나리오>/_results` (웹 UI 는 넘기지 않음) |

웹 UI 는 **소스를 읽어** 시나리오가 받는 플래그를 알아냅니다(`add_argument("--…"` 리터럴을 정규식으로 찾음).
그래서 선언하지 않은 플래그는 보내지 않고, `--model` 과 `--trials` 가 없으면 "UI 미지원" 으로 표시됩니다.
또 소스의 모듈 최상위 두 줄을 그대로 읽어 조건 선택지를 만듭니다 — **이름과 형식을 바꾸지 마십시오.**

```python
ARMS = ("조건A", "조건B")          # UI 의 조건 칩. **첫 항목이 처치군**(기본 선택)
ARMS_LABEL = "이 조건을 가르는 축"   # 예: "기억·정책", "Phase1". 끝의 "조건" 은 UI 가 떼고 씁니다
```

**조건 이름은 시나리오가 정하고 표시만 통일합니다.** 조건 어휘는 시나리오마다 다를 수밖에 없어서
(`deceived` · `unscoped-procedure-memory` · `VULN`), UI 만 보면 어느 칩이 처치군인지 알 수 없습니다.
그래서 웹 UI 가 칩 뒤에 공통 축을 한 단어로 붙입니다 — `deceived (처치)` · `honest (대조)` ·
`no_lure (변형)` · `empty-memory-baseline (기준선)`. `--arm` 으로는 **칩에 적힌 조건 이름만** 갑니다.

- 사상은 `run_chain.py` 의 모듈 최상위 한 줄 `GUIDE_ARM_MAP = {"조건A": "VULN", "조건B": "CONTROL", …}` 에서
  읽습니다(리터럴만, 실행하지 않음). 공용 드라이버 시나리오는 `task.json`/`probe.json` 의 `guide_arm_map` 을 씁니다.
- 사상이 없으면 **꼬리표를 붙이지 않습니다.** 조건이 처치/대조 축이 아닌 경우
  (예: 후속 과업 두 종류를 조건으로 두는 시나리오)에 억지로 붙이면 틀린 표시가 됩니다.
- 사상에 없는 조건은 `(보조)` 로 적습니다 — 처치·대조·변형 세 축 밖의 보조 조건이라는 뜻입니다.
- 라벨은 `조건 — <축>` 으로 통일됩니다. `ARMS_LABEL` 이 없으면 축을 모르므로 `조건` 만 나옵니다
  (`FOCUS-MISDELIVERY` 가 그런 경우입니다).

> **`--phase1-only` 는 선언하지 마십시오.** 웹 UI 는 이 플래그를 선언한 시나리오에 **항상** 붙입니다. 2페이즈를
> 끝까지 돌려야 하는 시나리오가 이걸 선언하면 UI 에서는 첫 페이즈만 돌고 끝납니다. (이 플래그를 가진
> `FOCUS-MISDELIVERY` 만 예외 — 비용을 반으로 줄이려는 의도적 동작입니다.)

### 2.4 실행 환경과 종료

- 웹 UI 는 하네스 `.venv` 의 파이썬으로 `OSWorld/` 에서 `PYTHONPATH=.` 로 실행합니다. 시나리오는 표준 라이브러리와
  하네스만 씁니다.
- **보조 서버.** 시나리오 폴더에 `serve.py` 가 있으면 UI 가 실행 전에 포트 8000 으로 띄우고(cwd = 시나리오 폴더)
  작업이 끝나면 내립니다. VM 이 접속해야 해서 모든 인터페이스(0.0.0.0)에 붙으므로 **이 포트를 터널·프록시로 내보내지
  마십시오.** ([SAFETY.md](../SAFETY.md) — 게스트 제어 서버 `:5000` 도 마찬가지)
- **중지.** UI 의 [중지] 는 프로세스에 SIGTERM 을 보냅니다. 기본 동작은 즉사라 VM·랩 서버·잠금 해제 같은 정리 코드가
  안 돕니다. 진입점을 둔 시나리오는 SIGTERM 을 `KeyboardInterrupt` 로 바꿔 정리가 돌게 합니다
  (`scenario_db.install_sigterm_as_interrupt`). 윈도우는 가로챌 수 없습니다.
- **종료코드(진입점을 둔 시나리오).** 0 정상 · 2 환경·입력 오류(VM 못 찾음·서버 없음 등) · 130 사용자 중단.
- VM 은 한 대라 **동시에 한 작업만** 돕니다.

### 2.5 결과

```
<시나리오>/_results/<모델키>/<조건>/t<N>/
├─ summary.json                        ← 웹 UI 와 결과 리포트가 읽는 것
├─ p1/  p2/ …                          Phase 별 step_*.png (스크린샷) · trajectory.jsonl (궤적)
└─ (시나리오별 증거 파일)
```

- 시행 폴더는 실행할 때마다 새로 만들어집니다. `<결과 루트>` 는 git 이 무시합니다(`.gitignore` 의 `_results/`).
- **라이브 화면**은 `<결과 루트>/<모델>/*/t*/p?/step_*.png` 의 가장 최근 파일입니다. 자체 실행기가 다른 폴더에 쓴다면
  그 파일을 이 자리로 하드링크해 줘야 합니다(`scenario_db.FrameMirror`).
- **`summary.json`** — 화면과 결과 리포트가 이 파일만 읽습니다. 이 모양으로 쓰면 UI 가 그려 줍니다.

  | | 필드 |
  |---|---|
  | 꼭 필요 | `verdict`(판정 — 아래 어휘) · `stages[]`(단계마다 `id`·`reached`·`fired`·`evidence_complete`) · `host_rows`(호스트가 본 증거를 `[라벨, 값, "hit"|""]` 로) · `status` |
  | 있으면 쓰임 | `model` · `arm`(공통 축: VULN/CONTROL/VARIANT/BASELINE) · `arm_local`(시나리오 고유 조건 이름) · `trial` · `chain_stage` · `p1_hit_cap`·`p2_hit_cap`(스텝 천장) · `conditions` · `verdict_native` · `evidence_dir` |

  `host_rows` 를 빼면 UI 가 다른 시나리오용 기본 행을 그려 전부 "아니오" 로 찍힙니다 — 꼭 넣으십시오.

- **판정 어휘.** 화면은 `verdict` 의 접두어만 봅니다 — `FIRE_*`(발화) · `TRUE_NEGATIVE_*`(실행저항) · `PARTIAL_*` ·
  `INVALID_*`(무효). 뒤에 붙는 말은 시나리오가 정하고, 그 뜻은 그 폴더 `SCENARIO.md` 의 판정 표에 적습니다.
  자체 실행기의 판정 이름은 `verdict_native` 에 그대로 둡니다.
- **판정은 호스트측 파일로만.** 모델의 자기보고를 판정에 쓰지 않습니다. 실행이 끝난 뒤 LLM 에 보내는 것은
  **읽기 쉬운 리포트를 쓰기 위한 것**이고, 판정을 뒤집지 않습니다.
- **"하지 않음"과 "거기까지 못 감"을 합치지 마십시오.** 도달하지 못한 단계는 0 이 아니라 미측정입니다(`reached` 가 그
  구분입니다).
- **요약이 둘 이상일 때.** 한 시행에서 페이즈별로 요약을 나누려면 `summary.json` · `summary.p2.json` 처럼 둡니다.
  자체 실행기의 요약(`chain.json`, `trial_summary.json` 등)은 이름이 `summary` 로 시작하지 않게 두십시오.
- **절대경로·계정명을 넣지 마십시오.** 요약은 결과 리포트에서 LLM 으로 보내질 수 있고, PR 에 올라갈 수도 있습니다
  (`scenario_db.rel` 이 레포 기준 경로로 줄여 줍니다).
- 형식이 의심되면 결과 폴더의 `summary.json` 을 직접 열어 `verdict` · `stages` · `host_rows` · `status`
  네 키가 있는지 보십시오. 공용 드라이버(`probe.py` · `osw_task.py`)를 쓰면 이 형식이 보장됩니다.

## 3. 자기 `run_chain.py` 를 갖는 시나리오 — 두 가지 방식

**A. `run_chain.py` 가 곧 실행기.** 위 규격(플래그·결과 위치·`summary.json`)을 직접 따릅니다
(`SELFTEST-PING` · `FOCUS-MISDELIVERY`).

**B. 자체 실행기 앞에 진입점을 둔다.** 시나리오가 위치 인자·환경변수·고유한 결과 위치·고유한 판정 어휘를 쓰는
자체 실행기를 갖고 있으면, 그 앞에 `run_chain.py` 를 진입점으로 둡니다(`MEM-BOUNDARY` · `MEM-FALSEFAIL`).
진입점이 하는 일은 네 가지뿐입니다.

1. **입력 번역** — 공통 플래그를 자체 실행기가 받는 방식(인자·환경변수)으로 바꿔 넘긴다.
2. **실행** — 프로세스 안에서 시행마다 새로 부른다. 자체 실행기 이름이 `run_chain.py` 와 겹치면 `run_chain_native.py` 처럼 다른 이름으로 둔다.
3. **출력 번역** — 자체 실행기가 남긴 요약을 `_results/…/summary.json` 으로 옮긴다. 판정 어휘만 옮기고 **다시 채점하지 않는다**
   (자체 판정 값은 `verdict_native` 에 보존).
4. **실시간 화면** — 자체 실행기 폴더의 스크린샷·궤적을 행 폴더로 하드링크한다(`FrameMirror`).

공용 헬퍼는 [`scenario_db.py`](../OSWorld/security_scenarios/scenario_db.py) 한 곳에 있습니다(표준 라이브러리만).
하네스에 없는 기능을 자체 실행기가 기대하면 그 폴더 안의 `harness_compat.py` 처럼 런타임에 덧댑니다 — 벤더·stock 코드는
고치지 않고, 파일을 지우면 원복입니다.

## 3.5 단일 표면 시나리오(프로브) — 폴더 하나로 끝내기

공격 페이지 하나 + 과업 하나 + 호스트측 마커 하나로 끝나는 시나리오는 모양이 전부 같습니다.
그 공통부는 [`security_scenarios/probe.py`](../OSWorld/security_scenarios/probe.py) 에 있고,
시나리오 폴더는 자산만 두면 됩니다. 틀은 `_TEMPLATE/` 를 복사하십시오(`_` 로 시작하는 폴더는
UI 목록에서 건너뜁니다).

```
<이름>/
├─ run_chain.py      열 줄. run_probe(폴더) 를 부르고 KIND·ARMS 만 선언
├─ scenario.json     OSWorld 과업 — instruction · config · evaluator · safety (호스트 주소는 __HOST__)
├─ probe.json        단계와 판정 이름, 조건별 과업 파일, 포트
├─ serve.py          공격 페이지 서버. 접속을 hits.jsonl 로 남긴다 (판정 근거)
├─ webroot/          그 서버가 서빙하는 페이지
└─ ABOUT.md          무엇을 재는지 — 설명 탭에 뜬다
```

- **판정은 선언으로 합니다.** `probe.json` 의 단계마다 `{"hit": "LURE"}`(서버 기록에 그 event 가 있음)
  또는 `{"score": 1}`(과업 evaluator 가 1 점)을 적습니다. 드라이버는 그 선언을 읽을 뿐 다시 채점하지
  않습니다.
- "페이지가 떴다"처럼 **에이전트가 한 일이 아닌 전제** 단계에는 `"exposure": true` 를 붙입니다. 발화로
  세지 않고, 이 단계가 안 터지면 `INVALID_not_reached`(측정 불가)가 됩니다. 붙이지 않으면 페이지만 떠도
  발화로 찍힙니다. 규칙 전체는 루트 `README.md` §5.5.
- `__HOST__` 는 실행할 때 VM 이 닿는 호스트 IP 로 치환됩니다. 자동 탐지가 틀리면 `PROBE_HOST_IP` 로
  지정합니다.
- 조건이 둘 이상이면 `arms` 와 `tasks` 에 조건별 과업 파일을 적고, `guide_arm_map` 으로 공통 축에
  사상합니다(§2.3 의 칩 꼬리표가 여기서 나옵니다).
- `--smoke` 는 VM·API 키 없이 과업·판정 선언·페이지만 점검합니다.

## 4. 새 시나리오를 넣는 순서

1. `OSWorld/security_scenarios/<이름>/` 에 폴더를 만든다 (실행 산출물·`.env`·VM 이미지는 넣지 않는다).
   폴더 이름은 §2.1 규격으로 짓는다. 단일 표면이면 `_TEMPLATE/` 를 복사해 시작한다(§3.5).
2. 공용 드라이버로 되면 그걸 쓴다(§3.5). 자기 실행기가 필요하면 §3 의 A 나 B 로 맞춘다.
3. `python3 webui/app.py --vmx <경로>/Ubuntu0.vmx` 를 (다시) 시작해 목록에 뜨는지, 플래그·조건 칩이 맞는지 본다.
4. `--smoke` 로 설정을 점검한다.
5. `--trials 1` 로 한 판 돌려 결과 폴더의 `summary.json` 을 열어 본다 — 판정이 의도한 대로 나왔는지,
   단계의 도달·발화가 맞는지, `host_rows` 에 근거가 적혔는지.
6. [SAFETY.md](../SAFETY.md) 의 공개 전 점검 목록을 확인한다 — 실제 자격증명·개인정보 없음, 호스트 절대경로 없음.
7. 폴더에 `ABOUT.md`(이 시나리오가 무엇을 재는지 — 웹 UI 의 **시나리오 설명** 탭에 그대로 뜬다)를 둔다.
   실행 방법이 길면 `SCENARIO.md` 로 따로 둔다.

## 5. 알려진 한계

- **스텝 천장(`hit_cap`) 표시.** 이 하네스는 천장 도달을 결과의 `conditions.measured.hit_cap` 에만 기록합니다. 최상위
  `hit_cap` 을 읽는 실행기(`FOCUS-MISDELIVERY` · `SELFTEST-PING`, `MEM-FALSEFAIL` 의 자체 실행기)는 이 값을
  못 받아 늘 거짓으로 봅니다. 스텝을 다 쓰고 끝난 판을 '입력 거부'로 셀 수 있으니, 의심스러운 판은 궤적의 스텝 수로
  확인하십시오. 진입점은 자기 UI 카드 표시만 따로 계산하고 자체 판정은 바꾸지 않습니다. 하네스 쪽 한 줄 수정으로
  풀리는 문제이며, 이 규격 작업의 범위 밖입니다.
- 웹 UI 의 결과 카드는 첫 페이즈(`p1/`)의 화면·궤적만 재생합니다. 2페이즈 시나리오의 둘째 페이즈 화면은 `p2/` 폴더에서
  직접 보십시오.
- 웹 UI 는 시작할 때 한 번만 시나리오를 스캔합니다.
