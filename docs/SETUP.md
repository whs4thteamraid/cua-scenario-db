# 설치

## 한눈에 — 무엇을 누가 하나

| 구분 | 항목 | 누가 |
|---|---|---|
| **수동** | VMware (Fusion / Workstation Pro) | **사용자** |
| **수동** | Python 3.12, [uv](https://docs.astral.sh/uv/) | **사용자** |
| 레포에 포함 | 하네스(OSWorld 기반 실행기) | 클론하면 같이 옴 |
| 자동 | VM 이미지 (수 GB) | 하네스가 첫 실행 때 내려받음 |
| 본인 것 | API 키 (`.env`) | 사용자 — **`--smoke` 는 없어도 동작** |

---

## 0. 하네스 — 레포에 들어 있습니다

`OSWorld/` 가 하네스입니다. 따로 받을 것 없이 의존성만 깔면 됩니다.

```bash
cd OSWorld && uv sync && cd ..
```

깔지 않아도 웹 UI 는 뜨지만 모델 목록이 기본값으로 나오고, 그렇다고 알려줍니다
(예전엔 UI 가 말없이 가상환경을 만들어 설치를 시작했습니다 — 지금은 안 합니다).

### 포크를 따로 쓰는 경우

```bash
python3 webui/app.py --osworld-root <다른 OSWorld 경로> --vmx ...
# 또는 .env 에  OSWORLD_ROOT=<다른 OSWorld 경로>
```

경로를 **주면 그 경로만** 씁니다. 틀렸으면 다른 데로 넘어가지 않고 중단합니다 —
조용히 다른 하네스를 재는 것보다 멈추는 쪽이 낫기 때문입니다.
경로를 안 주면 레포 안 `./OSWorld` 를 씁니다.

### 시나리오

`OSWorld/security_scenarios/` 아래 폴더 하나가 시나리오 하나입니다. 목록은 루트 [README.md](../README.md) §1.
처음에는 `SELFTEST-PING`(파이프라인 점검, 공격 아님)부터 돌려 보십시오.

시나리오는 `<이름>/run_chain.py` 로 들어가야 합니다 — 실행기가 레포 루트를
`Path(__file__).resolve().parents[2]` 로 자가탐색하므로, 그 트리 밖에 두거나
심링크만 걸면 import 가 깨집니다. → [../spec/HARNESS.md](../spec/HARNESS.md)

## 1. VMware (유일한 수동 설치)

| 플랫폼 | 제품 |
|---|---|
| 맥 (Apple Silicon / Intel) | VMware Fusion |
| 리눅스 · 윈도우 | VMware Workstation Pro |

**개인용은 무료**이지만 다운로드에 브로드컴 계정이 필요합니다.
설치 절차는 업스트림 문서가 가장 정확합니다 →
[OSWorld / INSTALL_VMWARE.md](https://github.com/xlang-ai/OSWorld/blob/main/desktop_env/providers/vmware/INSTALL_VMWARE.md)

### 설치 확인

```bash
vmrun -T ws list
```

현재 실행 중인 VM 목록이 뜨면 설치와 PATH 설정이 모두 성공한 것입니다.
`command not found` 가 나오면 PATH 에 `vmrun` 이 없는 것입니다.

```bash
# 맥 (Fusion)
export PATH="$PATH:/Applications/VMware Fusion.app/Contents/Public"
# 리눅스는 보통 /usr/bin/vmrun 로 이미 잡혀 있습니다
```

## 2. VM 이미지 — `SELFTEST-PING` 이 받아 옵니다

처음에 `SELFTEST-PING` 을 「테스트」 모드(`--smoke`)로 돌리면, VM 이미지가 없을 때 하네스가
플랫폼·아키텍처를 감지해 맞는 이미지를 자동으로 내려받습니다(Apple Silicon → ARM,
Intel/AMD → x86, API 키 불필요). 이어받기를 지원하므로 중간에 끊겨도 다시 실행하면
이어서 받습니다. 받고 나면 `OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx` 가 생기고,
그게 `--vmx` 의 기본값입니다. 다른 시나리오는 VM 을 못 찾으면 시작하지 않고 안내만 합니다.

> 이미지는 56GB 급이라 저장소에 들어갈 수 없습니다. 그래서 받아오는 구조입니다.

> **처음에는 수십 분 걸립니다.** 수 GB 다운로드 + 압축 해제 + VM 첫 부팅입니다.
> 멈춘 것이 아니니 기다리십시오.

## 3. API 키

레포 루트의 `.env` 에 넣습니다 (`.env.example` 복사).

```bash
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
KIMI_API_KEY=...
```

웹 UI 는 이 파일을 읽어 실행에 넘깁니다. 명령줄로 돌릴 때도 대부분의 시나리오가 직접 읽지만,
`FOCUS-MISDELIVERY` · `SELFTEST-PING` 은 읽지 않으므로 셸에 키를 export 하십시오.
셸에 이미 떠 있는 값이 우선입니다.

**키가 없어도 `--smoke` 는 동작합니다.** 에이전트도 API 호출도 없이 시나리오 메커니즘만
검증하므로, 과금 전에 환경 점검을 끝낼 수 있습니다.

## 4. 첫 실행 순서

```bash
# ① 웹 UI 가 뜨는가 (하네스를 찾았다는 줄이 먼저 찍힌다)
python3 webui/app.py --vmx <경로>/Ubuntu0.vmx

# ② SELFTEST-PING 을 「테스트」 모드로 — VM 다운로드·부팅·셸·판정 경로 검증 (키 불필요)
#    웹 UI 에서 시나리오 SELFTEST-PING, 모드 '테스트' 로 실행

# ③ run 1회 — 실제 측정 (키 필요)
```

②가 통과하면 환경 문제는 없습니다. 여기서 막히면 ③으로 넘어가지 마십시오.

### 호스트 서버를 쓰는 시나리오 — 방화벽

보조 서버(`serve.py`)가 있는 시나리오와 `MEM-BOUNDARY`(랩 서버 `:8080`)는 게스트 VM 이
**호스트의 LAN IP** 로 호스트 서버에 접속합니다. 호스트 방화벽이 python 인바운드를 막으면
`127.0.0.1` 점검은 통과하는데 VM 만 연결이 거부됩니다. 페이지가 안 뜨거나 접속 기록이 비면
방화벽을 먼저 보십시오.

- 맥: 시스템 설정 → 네트워크 → 방화벽
- 윈도우: Defender 방화벽 → python 인바운드 허용

호스트 IP 는 실행할 때마다 자동으로 감지하므로, Wi-Fi 가 바뀌어도 따로 할 일은 없습니다.

## 알려진 함정

**화면 해상도는 PC 마다 다릅니다.** 하네스가 정하지 않고 게스트 쪽에서 결정되며, 같은 PC
에서도 부팅마다 달라질 수 있습니다(실측: 1920×911 / 1920×1080). 절대 좌표를 쓰는 시나리오는
자기 환경의 실측값을 먼저 확인해야 하고, 모델 간 비교는 같은 PC·같은 부팅 안에서 돈 판끼리만
유효합니다.

**VM 1 대 = 동시 실행 1 건.** 웹 UI 는 작업 슬롯을 하나만 둡니다.

**게스트 제어 서버(`:5000`)를 터널로 노출하지 마십시오.** 임의 명령 실행 엔드포인트가
있습니다. 웹 UI(`8787`)만 노출하고, 노출할 때는 `--password` 를 반드시 줍니다
(없으면 외부 바인딩 자체를 거부합니다). → [../SAFETY.md](../SAFETY.md)

전체 함정 목록은 [../spec/TRAPS.md](../spec/TRAPS.md) 에 있습니다.
