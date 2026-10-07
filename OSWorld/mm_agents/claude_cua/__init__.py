"""
Claude Computer Use (유형2) agent for OSWorld — configurable tool set.

mm_agents/anthropic 는 Claude 에게 `computer` 툴만 준다(=유형1, 화면 GUI만).
이 모듈은 툴 세트를 런타임에 고를 수 있게 해서 유형1↔유형2를 스위칭한다:

  tools=("computer",)                 → 유형1 (GUI만)
  tools=("computer","bash")           → 유형2 (셸 직통 열림)
  tools=("computer","bash","editor")  → 유형2 + 파일편집

각 툴 호출을 OSWorld VM 컨트롤러로 라우팅한다:
  computer → env.step(pyautogui)          (스샷을 결과로)
  bash     → controller.execute_python_command 로 감싼 subprocess (stdout을 결과로)
  editor   → controller.get_file / run_python_script
"""

from .agent import ClaudeCUAAgent

__all__ = ["ClaudeCUAAgent"]
