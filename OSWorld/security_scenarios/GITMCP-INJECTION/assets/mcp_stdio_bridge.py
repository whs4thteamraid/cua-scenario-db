#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal MCP stdio client bridge for the RAID v3 runner.

The v3 agent invokes this (inside the VM) as:
  python3 mcp_stdio_bridge.py --server-command-b64 <b64> --operation list|call
                              [--tool-name X] [--arguments-b64 <b64>]
                              [--protocol-version V]
It launches the MCP server (server_command) over stdio, performs the JSON-RPC
handshake (initialize -> notifications/initialized), runs the requested op
(tools/list or tools/call), and prints EXACTLY ONE JSON-RPC response object to
stdout (the runner does json.loads on the whole stdout and reads .result/.error).
MCP stdio transport = newline-delimited JSON-RPC messages.
"""
import argparse
import base64
import json
import subprocess
import sys


def _send(proc, msg):
    proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _read_id(proc, want_id, limit=200):
    for _ in range(limit):
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if isinstance(msg, dict) and msg.get("id") == want_id:
            return msg
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-command-b64", required=True)
    ap.add_argument("--operation", required=True, choices=["list", "call"])
    ap.add_argument("--tool-name")
    ap.add_argument("--arguments-b64")
    ap.add_argument("--protocol-version", default="2025-06-18")
    a = ap.parse_args()

    server_command = json.loads(base64.b64decode(a.server_command_b64).decode("utf-8"))
    arguments = (json.loads(base64.b64decode(a.arguments_b64).decode("utf-8"))
                 if a.arguments_b64 else {})

    proc = subprocess.Popen(
        server_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1,
    )
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": a.protocol_version,
                                "capabilities": {},
                                "clientInfo": {"name": "raid-bridge", "version": "1.0"}}})
        _read_id(proc, 1)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        if a.operation == "list":
            _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            resp = _read_id(proc, 2)
        else:
            _send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                         "params": {"name": a.tool_name, "arguments": arguments}})
            resp = _read_id(proc, 3)

        print(json.dumps(resp if resp else {"error": {"code": -32000, "message": "no response"}},
                         ensure_ascii=False))
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
