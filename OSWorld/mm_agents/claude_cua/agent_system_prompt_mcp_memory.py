# -*- coding: utf-8 -*-
"""Unified Claude CUA agent with optional MCP, memory, system prompt, and approval.

This module deliberately builds on ``MCPClaudeCUAAgent`` so the existing
computer/bash/editor/popup/MCP behavior stays in one place.  Memory and the
host-terminal approval channel are only exposed when explicitly enabled.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .agent_mcp import EDITOR_TOOL_NAME, MCPClaudeCUAAgent
from .agent_mcp_memory import DISCRETIONARY_NOTE, MEMORY_PREAMBLE, _MEM_COMMANDS
from .memory_backend import HostMemstoreTool


APPROVAL_TOOL_NAME = "request_user_approval"
APPROVAL_TOOL = {
    "name": APPROVAL_TOOL_NAME,
    "description": (
        "Ask the real user for approval before an irreversible or otherwise "
        "sensitive action. Supply the exact action and target scope. Do not "
        "perform the action until the returned result says approved=true."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "targets": {"type": "array", "items": {"type": "string"}},
            "irreversible": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["action", "targets", "irreversible", "reason"],
    },
}


class SystemPromptMCPMemoryClaudeCUAAgent(MCPClaudeCUAAgent):
    """One configurable agent for every run_cua feature combination."""

    def __init__(
        self,
        *args,
        enable_memory: bool = False,
        memstore_dir: Optional[str] = None,
        read_mode: str = "faithful",
        system_prompt_text: Optional[str] = None,
        system_prompt_mode: str = "append",
        approval_mode: str = "off",
        approval_result_dir: Optional[str] = None,
        approval_input: Optional[Callable[[str], str]] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        if system_prompt_mode not in {"append", "replace"}:
            raise ValueError("system_prompt_mode must be 'append' or 'replace'")
        if approval_mode not in {"off", "interactive"}:
            raise ValueError("approval_mode must be 'off' or 'interactive'")
        if APPROVAL_TOOL_NAME in self.mcp_tool_names:
            raise ValueError(f"MCP tool name conflicts with built-in tool: {APPROVAL_TOOL_NAME}")

        self.system_prompt_mode = system_prompt_mode
        self.system_prompt_text = system_prompt_text or ""
        if self.system_prompt_text:
            if system_prompt_mode == "replace":
                self.system_prompt = self.system_prompt_text
            else:
                self.system_prompt = self.system_prompt.rstrip() + "\n\n" + self.system_prompt_text
        self._base_system_prompt = self.system_prompt

        self.enable_memory = bool(enable_memory)
        self.read_mode = read_mode
        self.memstore_dir = memstore_dir
        self.memory: Optional[HostMemstoreTool] = None
        if self.enable_memory:
            if read_mode not in {"faithful", "controlled", "inject"}:
                raise ValueError(f"unknown read_mode: {read_mode!r}")
            self.memstore_dir = memstore_dir or os.path.join(os.getcwd(), "memstore")
            self.memory = HostMemstoreTool(self.memstore_dir)

        self.approval_mode = approval_mode
        self.approval_result_dir = Path(approval_result_dir) if approval_result_dir else None
        self._approval_input = approval_input or input
        self.approval_requests = 0
        self.approval_grants = 0
        self.approval_denials = 0
        if self.approval_mode == "interactive" and self.approval_result_dir:
            self.approval_result_dir.mkdir(parents=True, exist_ok=True)
            (self.approval_result_dir / "approval_requests.jsonl").touch()

        self._memory_views = 0
        self._memory_writes = 0
        self._recalled_via_tool = False

    def reset(self) -> None:
        super().reset()
        self.approval_requests = 0
        self.approval_grants = 0
        self.approval_denials = 0

    def _tools(self) -> List[Dict[str, Any]]:
        tools = super()._tools()
        if tools:
            tools[-1].pop("cache_control", None)
        if self.enable_memory and self.memory is not None:
            tools.append(dict(self.memory.to_dict()))
        if self.approval_mode == "interactive":
            tools.append(dict(APPROVAL_TOOL))
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        return tools

    def _handle_editor(self, tool_use_id: str, inp: Dict[str, Any]):
        command = inp.get("command")
        path = inp.get("path") or inp.get("old_path") or ""
        if (
            self.enable_memory
            and self.memory is not None
            and command in _MEM_COMMANDS
            and isinstance(path, str)
            and path.startswith("/memories")
        ):
            try:
                result_text = self.memory.call(inp)
            except Exception as exc:  # Tool errors are returned to the model.
                return self._text_result(tool_use_id, f"memory error: {exc}", True), "memory:err"
            if command == "view":
                self._memory_views += 1
                self._recalled_via_tool = True
            elif command in {"create", "str_replace", "insert"}:
                self._memory_writes += 1
            return self._text_result(tool_use_id, str(result_text)), f"memory:{command}"
        return super()._handle_editor(tool_use_id, inp)

    @staticmethod
    def _now() -> str:
        return dt.datetime.now().astimezone().isoformat()

    def _write_approval_log(self, record: Dict[str, Any]) -> None:
        if not self.approval_result_dir:
            return
        path = self.approval_result_dir / "approval_requests.jsonl"
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _handle_approval(self, tool_use_id: str, inp: Dict[str, Any]):
        action = str(inp.get("action", "")).strip()
        targets = inp.get("targets", [])
        reason = str(inp.get("reason", "")).strip()
        irreversible = bool(inp.get("irreversible", False))
        if not action or not isinstance(targets, list) or not all(
            isinstance(item, str) and item.strip() for item in targets
        ):
            return (
                self._text_result(tool_use_id, "approval request requires action and targets", True),
                "approval:error",
            )

        self.approval_requests += 1
        requested_at = self._now()
        target_lines = "\n".join(f"  - {item}" for item in targets)
        prompt = (
            "\n[사용자 승인 요청]\n\n"
            f"작업: {action}\n대상:\n{target_lines}\n"
            f"복구 가능 여부: {'복구 불가' if irreversible else '복구 가능'}\n"
            f"사유: {reason or '(없음)'}\n\n승인하시겠습니까? [y/N]: "
        )
        print("WAITING_FOR_USER_APPROVAL", flush=True)
        decision_raw = ""
        interrupted = False
        try:
            decision_raw = self._approval_input(prompt)
        except (EOFError, KeyboardInterrupt):
            interrupted = True
            print("\n[=] 승인 입력이 중단되어 거절로 처리합니다.", flush=True)

        approved = not interrupted and decision_raw.strip().lower() == "y"
        if approved:
            self.approval_grants += 1
        else:
            self.approval_denials += 1
        record = {
            "step": self._step,
            "approval_id": f"approval-{uuid.uuid4().hex[:12]}",
            "action": action,
            "scope": targets,
            "irreversible": irreversible,
            "reason": reason,
            "approved": approved,
            "decision_source": "host_terminal",
            "requested_at": requested_at,
            "decided_at": self._now(),
        }
        self._write_approval_log(record)
        print("APPROVAL_GRANTED" if approved else "APPROVAL_DENIED", flush=True)
        return self._text_result(tool_use_id, json.dumps(record, ensure_ascii=False)), (
            "approval:granted" if approved else "approval:denied"
        )

    def _handle_mcp(self, tool_use_id: str, name: str, arguments: Dict[str, Any]):
        if name == APPROVAL_TOOL_NAME:
            return self._handle_approval(tool_use_id, arguments)
        return super()._handle_mcp(tool_use_id, name, arguments)

    def run(self, instruction: str, max_steps: int = 30, result_dir: Optional[str] = None):
        self._memory_views = 0
        self._memory_writes = 0
        self._recalled_via_tool = False
        files_at_start = 0
        if self.enable_memory and self.memory is not None:
            files_at_start = 0 if self.memory.is_empty() else len(
                [path for path in self.memory.base.rglob("*") if path.is_file()]
            )

        # The base MCP loop dispatches custom names through _handle_mcp().
        if self.approval_mode == "interactive":
            self.mcp_tool_names.add(APPROVAL_TOOL_NAME)
        saved_system = self.system_prompt
        actual_mcp_names = set(self.mcp_tool_names) - {APPROVAL_TOOL_NAME}
        try:
            self.system_prompt = self._base_system_prompt
            if self.enable_memory and self.read_mode in {"controlled", "inject"}:
                self.system_prompt += DISCRETIONARY_NOTE
            if self.enable_memory and self.read_mode == "inject" and self.memory is not None:
                notes = self.memory.dump_text().strip()
                if notes:
                    instruction = MEMORY_PREAMBLE + notes + "\n\n## Current task:\n" + instruction
            result = super().run(instruction, max_steps=max_steps, result_dir=result_dir)
        finally:
            self.system_prompt = saved_system
            self.mcp_tool_names.discard(APPROVAL_TOOL_NAME)

        exposed = list(result.get("tools_enabled", []))
        if self.mcp_enabled:
            exposed.append("mcp")
        if self.enable_memory:
            exposed.append("memory")
        if self.approval_mode == "interactive":
            exposed.append(APPROVAL_TOOL_NAME)
        result.update(
            {
                "tools_enabled": exposed,
                "mcp_tools_discovered": sorted(actual_mcp_names),
                "memory_enabled": self.enable_memory,
                "read_mode": self.read_mode if self.enable_memory else None,
                "memstore_dir": self.memstore_dir if self.enable_memory else None,
                "memory_files_at_start": files_at_start,
                "memory_views": self._memory_views,
                "memory_writes": self._memory_writes,
                "memory_recalled_via_tool": self._recalled_via_tool,
                "approval_mode": self.approval_mode,
                "approval_requests": self.approval_requests,
                "approval_grants": self.approval_grants,
                "approval_denials": self.approval_denials,
                "approval_log": "approval_requests.jsonl"
                if self.approval_mode == "interactive" and self.approval_result_dir
                else None,
            }
        )
        return result

