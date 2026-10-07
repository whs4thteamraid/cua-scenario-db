#!/usr/bin/env python3
"""Small MCP stdio client used inside the OSWorld guest VM."""

from __future__ import annotations

import argparse
import base64
import json
import queue
import subprocess
import sys
import threading
from typing import Any


def decode_json_b64(value: str) -> Any:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def send(proc: subprocess.Popen[str], message: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def receive(proc: subprocess.Popen[str], request_id: int, timeout: float = 15.0) -> dict[str, Any]:
    assert proc.stdout is not None
    received: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=1)

    def read_until_match() -> None:
        try:
            for line in proc.stdout:
                message = json.loads(line)
                if message.get("id") == request_id:
                    received.put(message)
                    return
            stderr = proc.stderr.read() if proc.stderr else ""
            received.put(RuntimeError(f"MCP server closed stdout: {stderr[-1000:]}"))
        except BaseException as exc:  # Forward reader failures to the main thread.
            received.put(exc)

    threading.Thread(target=read_until_match, daemon=True).start()
    try:
        value = received.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(f"timed out waiting for MCP response id={request_id}") from exc
    if isinstance(value, BaseException):
        raise value
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-command-b64", required=True)
    parser.add_argument("--operation", choices=("list", "call"), required=True)
    parser.add_argument("--tool-name")
    parser.add_argument("--arguments-b64")
    parser.add_argument("--protocol-version", default="2025-06-18")
    args = parser.parse_args()

    command = decode_json_b64(args.server_command_b64)
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("server command must be a JSON string array")
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": args.protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "osworld-cua-mcp-bridge", "version": "1.0.0"},
                },
            },
        )
        initialized = receive(proc, 1)
        if "error" in initialized:
            print(json.dumps(initialized, ensure_ascii=False))
            raise SystemExit(2)
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        if args.operation == "list":
            request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        else:
            if not args.tool_name or not args.arguments_b64:
                raise ValueError("call requires --tool-name and --arguments-b64")
            request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": args.tool_name,
                    "arguments": decode_json_b64(args.arguments_b64),
                },
            }
        send(proc, request)
        print(json.dumps(receive(proc, 2), ensure_ascii=False))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
