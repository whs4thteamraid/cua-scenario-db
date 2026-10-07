# 측정 함정

**로그는 정상인데 결과만 조용히 뒤집히는** 것들. 전부 직접 밟아 가며 모았다.
새 시나리오를 돌리기 전에 이 목록으로 자기 코드를 훑는 쪽이 싸다.

---

## 1. `pkill -f` 가 자기 자신을 죽인다

```bash
pkill -f attacker_win.py        # ❌
pkill -f '[a]ttacker_win\.py'   # ✅
```

`-f` 는 전체 명령줄을 본다. `pkill` 을 부른 **셸의 명령줄에 그 패턴이 들어있으므로**
셸이 매칭되어 먼저 죽고, 뒤에 이어 붙인 pkill 들은 실행되지 않는다.

**증상이 고약하다.** 정리가 안 된 채 다음 팔이 시작되므로:
- 팔이 달라졌는데 프로세스 PID 가 동일
- 공격 OFF 인 팔의 로그에 ON 팔의 마커가 찍힘 (`tag=smoke-VULN` in `STEAL-OFF`)

즉 **팔 사이의 차이가 사라지는데 에러는 안 난다.** 대조군이 대조군이 아니게 된다.

점검: 정리 직후 `pgrep -af <패턴>` 이 비는지 확인한다. 팔마다 PID 가 바뀌는지 본다.

## 2. 화면 해상도는 하네스가 정하지 않는다

```python
# desktop_env/providers/vmware/manager.py:425
def get_vm_path(self, os_type, region=None, screen_size=(1920, 1080), **kwargs):
    # Note: screen_size parameter is ignored for VMware provider
```

게스트 쪽에서 결정되고, `.vmx` 에 고정 키가 없다. **같은 PC 에서도 부팅마다 달라진다**
(실측: 1920×911 / 1920×1080).

- 절대 좌표를 쓰는 시나리오는 자기 환경의 실측값을 먼저 확인해야 한다
- 모델 간 비교는 **같은 PC·같은 부팅** 안에서 돈 판끼리만 유효하다
- 실제로 보낸 크기는 `summary.json` 의 `conditions.image_sent_wh` 에 있다.
  `conditions.screen_size` 는 **리터럴**이므로 파서가 믿으면 안 된다

관련: `controllers/setup.py` 의 `{SCREEN_WIDTH}`/`{SCREEN_HEIGHT}` 치환은
하드코딩된 1920×1080 을 쓴다. 업스트림 예제 다수가 이것에 의존한다.

## 3. tkinter 위젯은 포커스를 안 가진다

창을 띄웠다고 입력이 들어가는 것이 아니다. `ent.focus_set()` 이 없으면 엔트리에
키보드 포커스가 없고, 타이핑이 **아무 데도** 안 들어간다.

오버레이 시나리오에서는 이것이 설계 결정과 충돌한다 — 1단계 창의 포커스를 흔들지 않으려고
`focus_set()` 을 일부러 빼면, 2단계 창도 입력을 못 받는다. 배송 점검 프로브는
`xdotool key Tab` 을 먼저 보내야 한다.

**오버레이의 z-order 는 `-topmost` 로 올린다.** `focus_force()` 는 아래 창의 상태를
건드려 1단계 측정을 오염시킨다.

## 4. `xdotool getwindowpid` 는 tkinter 창에서 빈 값

`_NET_WM_PID` 를 안 세우는 듯하다. `xprop` 폴백도 비었다. 어느 창이 입력을 받았는지
PID 로 귀속시키려는 계측은 **영구히 "불명"** 이 된다. 그런 필드는 두지 말고,
싱크 파일을 분리해서 귀속한다 (1단계 → `focus_sink.log`, 2단계 → `focus_sink_b.log`).

## 5. 스냅샷 복원이 조용히 건너뛰어진다

`restore` 를 명시했는데 VM 이 안 돌아가는 경우가 있다. → `spec/HARNESS.md` 의
`restore` 절. 로그에 `"Environment is clean, skipping snapshot revert"` 가 찍히면
**이전 페이즈의 파일이 살아있는 채로** 다음 페이즈가 시작됐다는 뜻이다.

## 6. 세션 경계가 창 하나 때문에 새는다

페이즈 1 에서 열린 창(에디터·브라우저)이 페이즈 2 까지 남아 있으면, 페이즈 2 의 결과가
"메모리에서 되살아난 것"인지 "화면에 그냥 남아 있던 것"인지 구분할 수 없다.
경계에서 **창 전체를 정리**하고, 정리됐다는 것을 호스트측에서 확인한다.

## 7. 시나리오마다 CLI 가 다르다

위치 인자형(`<arm> <model> <N>`)과 플래그형(`--model --trials`)이 섞여 있다.
가정하고 실행하면 엉뚱한 자리에 값이 꽂혀 터진다
(`ValueError: invalid literal for int() with base 10: '--model'`, 실측 2026-10-04).

웹 UI 는 `run_chain.py` 소스에서 `add_argument` 를 읽어 지원 플래그를 **스캔**하고,
`--model`/`--trials` 가 없는 시나리오는 버튼을 잠근다.

## 8. 비밀 토큰을 랜덤 hex 로 만들면 OCR 변수가 섞인다

`FP-6d33` 같은 토큰은 에이전트가 스크린샷에서 오독한다 (F↔P 혼동, 자릿수 누락).
그러면 "속았는가"와 "읽을 수 있었는가"가 한 숫자에 섞인다.
대문자 단어 2개 + 2자리(`RIVER-TIGER-42`) 로 두면 오독이 줄고 유일성은 유지된다.

## 9. 시나리오를 하네스 트리 밖에 두면 import 가 깨진다

`run_chain.py` 는 `Path(__file__).resolve().parents[2]` 로 레포 루트를 찾는다.
→ `spec/HARNESS.md` 의 배치 표.

## 10. 체인 단계가 게이팅되지 않으면 조건부확률이 아니다

→ `spec/VERDICTS.md` 원칙 3.

## 11. `Cache-Control: no-store` + `img.src` = 두 번 받는다

실시간 화면 갱신에서, 미리 받아둔 URL 을 `img.src` 에 대입하면 **다시 네트워크로 받는다**
(no-store 이므로 캐시에 없다). 그 사이 프레임이 비어 깜박인다.
`<img>` 두 장을 겹쳐 두고 `opacity` 로 교체한다.

## 12. 긴 명령을 타이핑시키면 게스트에서 문법 오류가 난다

에이전트에게 긴 한 줄을 실행하라고 시키면, 모델이 그것을 `pyautogui.write("...")`
안에 넣다가 **중간에서 줄을 바꾼다.** 파이썬 문자열이 안 닫힌다.

```
SyntaxError: unterminated string literal (detected at line 4)
pyautogui.write("ping -c 2 8.8.8.8 > ~/selftest.txt 2>&1
                                                        ^
```

그러면 그 스텝은 **아무것도 실행되지 않고**, 화면은 그대로이고, 모델은 "입력이 안
됐네" 하며 같은 동작을 스텝 한도까지 반복한다. 모델이 멍청해 보이지만 원인은
시나리오가 요구한 줄 길이다.

**타이핑시킬 명령은 짧게 쪼갠다.** 특수문자(`;` `&` `>` 따옴표)가 많을수록 더 쉽게
깨지므로, 꼭 필요한 것만 남긴다.

### 이것이 안 보였던 이유 — 게스트 에러를 버리고 있었다

`DesktopEnv.step()` 이 `controller.execute_python_command(command)` 의 **반환값을
받지 않았다.** 게스트가 stderr 로 무엇을 뱉든 호스트 로그는 정상으로 보인다.
이 포크는 그것을 `info["exec"]` 로 올리고, 에뮬 경로가 `guest_stderr:` 라벨로
남긴다. 없었으면 이 함정은 "모델이 이상하다"로 끝났을 것이다.
