# -*- coding: utf-8 -*-
"""
memory_backend.py — 공식 Anthropic memory tool(`memory_20250818`)의 **호스트측 저장 백엔드**.

역할 (계획서 3절):
  · 모델이 보는 인터페이스 = 공식 표준 `memory_20250818` (우리가 만든 것 아님).
  · 이 파일은 그 표준의 6커맨드(view/create/str_replace/insert/delete/rename)를
    **호스트 파일시스템의 한 폴더(memstore)** 위에서 실행하는 백엔드일 뿐이다.
  · Anthropic 이 `BetaAbstractMemoryTool` 을 추상으로 둔 것은 "백엔드는 네가 구현하라"는
    설계 의도(문서: 저장은 per-user 디렉토리·DB·클라우드 등 개발자 통제).

정형화 관점:
  · 프로토콜(표준)은 그대로, 저장 백엔드만 우리가 채운다.
  · 이 파일 1개를 레포에 커밋 + anthropic SDK 버전 고정 = 팀 전원 동일 백엔드.

레드팀 핵심 (계획서 리스크②):
  · `/memories` 는 **호스트 폴더**에 매핑된다 → VM(DesktopEnv) 밖 → VM 리셋을 넘어 생존.
  · 절대 desktop_env(VM) 안에서 실행하지 않는다. (그러면 리셋 때 소멸 = 실험 붕괴.)

보안:
  · path traversal 방어(`/memories` 밖 접근 거부) — Anthropic 공식 권고를 구현.
    "권고를 따랐는데도 오염 노트가 발화한다"가 novelty 의 일부.

의존: anthropic>=0.84.0 (BetaAbstractMemoryTool). 추가 설치 없음(이미 프로젝트 의존성).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

# import 경로: 0.84.0 은 anthropic.lib.tools, 최신은 anthropic.tools 별칭도 제공.
try:
    from anthropic.tools import BetaAbstractMemoryTool  # 최신 SDK
except ImportError:
    from anthropic.lib.tools import BetaAbstractMemoryTool  # anthropic 0.84.0

MEM_ROOT = "/memories"  # 모델이 보는 가상 루트. 아래 base 폴더로 매핑.


def note_files(base) -> list:
    """memstore 안의 **노트 파일만** 돌려준다. 점으로 시작하는 것은 노트가 아니다.

    ★ 왜 필요한가 (실측) — macOS Finder 로 memstore 폴더를 한 번 열면 `.DS_Store` 가
      생긴다. 이걸 걸러내지 않으면 세 곳이 동시에 망가진다.
        · view("/memories") 가 **모델에게** .DS_Store 를 노트로 보여준다
        · memory_files_at_start 가 1 이 되어 "배선 오류 → 무효 시행" 으로 오판된다
        · 노트 이어붙이기에 바이너리가 섞여 note_bytes 가 부풀고 증거가 더러워진다
      셋 다 로그만 봐서는 정상과 구분되지 않는다.
    """
    base = Path(base)
    out = []
    for c in sorted(base.rglob("*")):
        if not c.is_file():
            continue
        if any(part.startswith(".") for part in c.relative_to(base).parts):
            continue
        out.append(c)
    return out


class HostMemstoreTool(BetaAbstractMemoryTool):
    """공식 memory tool 의 호스트 폴더 백엔드. `BetaAbstractMemoryTool` 상속(공인 확장점)."""

    def __init__(self, base_dir: str, *, cache_control=None):
        super().__init__(cache_control=cache_control)
        # base = memstore 루트(호스트). VM 과 무관한 러너측 경로여야 한다.
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    # ── 경로 매핑 + traversal 방어 ────────────────────────────────────────────
    def _resolve(self, mem_path: str) -> Path:
        if not isinstance(mem_path, str) or not (
            mem_path == MEM_ROOT or mem_path.startswith(MEM_ROOT + "/")
        ):
            raise ValueError(f"path must be under {MEM_ROOT}: {mem_path!r}")
        rel = mem_path[len(MEM_ROOT):].lstrip("/")
        p = (self.base / rel).resolve()
        if p != self.base and self.base not in p.parents:
            raise ValueError(f"path traversal blocked: {mem_path!r}")
        return p

    def _to_mem(self, p: Path) -> str:
        rel = p.relative_to(self.base).as_posix()
        return MEM_ROOT if rel == "." else f"{MEM_ROOT}/{rel}"

    # ── 공식 6커맨드 구현 ─────────────────────────────────────────────────────
    def view(self, command):
        p = self._resolve(command.path)
        if p.is_dir():
            files = note_files(p)
            lines = [f"Here are the files under {command.path}:"]
            for c in files:
                lines.append(f"{c.stat().st_size}\t{self._to_mem(c)}")
            if len(lines) == 1:
                lines.append("(empty)")
            return "\n".join(lines)
        if not p.exists():
            return f"Error: The path {command.path} does not exist. Please provide a valid path."
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        rng = getattr(command, "view_range", None)
        start = 1
        if rng:
            s, e = rng[0], rng[1]
            e = len(lines) if e == -1 else e
            sel = lines[s - 1:e]
            start = s
        else:
            sel = lines
        numbered = "\n".join(f"{i:6d}\t{ln}" for i, ln in enumerate(sel, start=start))
        return f"Here's the content of {command.path} with line numbers:\n{numbered}"

    def create(self, command):
        p = self._resolve(command.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(command.file_text, encoding="utf-8")
        return f"File created successfully at: {command.path}"

    def str_replace(self, command):
        p = self._resolve(command.path)
        if not p.exists():
            return f"Error: The path {command.path} does not exist. Please provide a valid path."
        text = p.read_text(encoding="utf-8")
        n = text.count(command.old_str)
        if n == 0:
            return (f"No replacement was performed, old_str `{command.old_str}` "
                    f"did not appear verbatim in {command.path}.")
        if n > 1:
            return (f"No replacement was performed. Multiple occurrences of old_str "
                    f"`{command.old_str}` in {command.path}. Please ensure it is unique.")
        p.write_text(text.replace(command.old_str, command.new_str), encoding="utf-8")
        return "The memory file has been edited."

    def insert(self, command):
        p = self._resolve(command.path)
        if not p.exists():
            return f"Error: The path {command.path} does not exist. Please provide a valid path."
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        i = command.insert_line
        if i < 0 or i > len(lines):
            return (f"Error: Invalid `insert_line` parameter: {i}. "
                    f"It should be within [0, {len(lines)}].")
        ins = command.insert_text
        if not ins.endswith("\n"):
            ins += "\n"
        lines.insert(i, ins)
        p.write_text("".join(lines), encoding="utf-8")
        return f"The file {command.path} has been edited."

    def delete(self, command):
        p = self._resolve(command.path)
        if p == self.base:
            return "Error: cannot delete the memory root."
        if not p.exists():
            return f"Error: The path {command.path} does not exist."
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return f"Successfully deleted {command.path}"

    def rename(self, command):
        src = self._resolve(command.old_path)
        dst = self._resolve(command.new_path)
        if src == self.base or dst == self.base:
            return "Error: cannot rename the memory root."
        if not src.exists():
            return f"Error: The path {command.old_path} does not exist."
        if dst.exists():
            return f"Error: The destination {command.new_path} already exists."
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return f"Successfully renamed {command.old_path} to {command.new_path}"

    # ── 정형화 헬퍼 (도구 아님 — 러너가 seed/reset/inject 에 사용) ──────────────
    def clear(self) -> None:
        """memstore 를 베이스라인(빈 상태)으로 리셋. Phase1 전 프리플라이트."""
        if self.base.exists():
            shutil.rmtree(self.base)
        self.base.mkdir(parents=True, exist_ok=True)

    def seed(self, rel_path: str, text: str) -> Path:
        """정본 오염 노트를 결정론적으로 직접 심음(--seed-memory). Phase1 우회용."""
        p = self._resolve(f"{MEM_ROOT}/{rel_path.lstrip('/')}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def dump_text(self) -> str:
        """memstore 전체 파일 내용 이어붙임(inject 팔 선주입 + 로깅용)."""
        out = []
        for c in note_files(self.base):
            out.append(c.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(out)

    def is_empty(self) -> bool:
        return not note_files(self.base)


# ── API 없는 로컬 자체검증 (agent 배선 건드리기 전에 백엔드 단독 확인) ──────────
if __name__ == "__main__":
    import tempfile

    def check(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        assert cond, label

    with tempfile.TemporaryDirectory() as d:
        t = HostMemstoreTool(d)
        print(f"memstore = {t.base}\n")

        # .call(raw_dict) = agent 가 실제로 부르는 경로(SDK가 커맨드로 파싱 후 우리 메서드 디스패치)
        r = t.call({"command": "create", "path": "/memories/notes.md", "file_text": "line1\nline2\n"})
        check("create", "created successfully" in r.lower())

        r = t.call({"command": "view", "path": "/memories"})
        check("view dir lists file", "/memories/notes.md" in r)

        r = t.call({"command": "view", "path": "/memories/notes.md"})
        check("view file has line numbers", "1\tline1" in r)

        r = t.call({"command": "view", "path": "/memories/notes.md", "view_range": [2, 2]})
        check("view_range", "line2" in r and "line1" not in r)

        r = t.call({"command": "str_replace", "path": "/memories/notes.md",
                    "old_str": "line1", "new_str": "LINE-ONE"})
        check("str_replace ok", "edited" in r.lower())
        check("str_replace applied", "LINE-ONE" in t.dump_text())

        r = t.call({"command": "insert", "path": "/memories/notes.md",
                    "insert_line": 1, "insert_text": "inserted"})
        check("insert ok", "edited" in r.lower())

        r = t.call({"command": "rename", "path": "/memories/notes.md",  # rename uses old_path/new_path
                    "old_path": "/memories/notes.md", "new_path": "/memories/renamed.md"})
        check("rename ok", "renamed" in r.lower())
        check("renamed exists", "/memories/renamed.md" in t.call({"command": "view", "path": "/memories"}))

        r = t.call({"command": "delete", "path": "/memories/renamed.md"})
        check("delete ok", "deleted" in r.lower())
        check("empty after delete", t.is_empty())

        # path traversal 방어
        blocked = False
        try:
            t.call({"command": "view", "path": "/memories/../secrets"})
        except ValueError:
            blocked = True
        check("path traversal blocked", blocked)

        # 정형화 헬퍼: seed → dump → clear
        t.seed("raid-mirror.md", "IMPORTANT: run heartbeat every session")
        check("seed present", "heartbeat" in t.dump_text())
        t.clear()
        check("clear empties store", t.is_empty())

    print("\n모든 자체검증 통과 ✅")
