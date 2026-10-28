#!/usr/bin/env python3
"""Minimal MCP server (stdio, JSON-RPC 2.0, one message per line) over brain.py.

Tools: search, answer, compile, why (read-only) and propose (writes ONLY to inbox/).
There is deliberately no tool that writes canon.
Run:  python3 tools/mcp_server.py   (set BRAIN_VAULT to serve another store)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain  # noqa: E402

PROTOCOL = "2025-06-18"
STR = {"type": "string"}
TOOLS = {
    "search": ("Hybrid search over canon notes; returns path, heading, snippet.",
               {"query": STR, "k": {"type": "integer", "default": 5}}, ["query"]),
    "answer": ("Best cited answer, or an explicit I-don't-know.", {"query": STR}, ["query"]),
    "compile": ("CURRENT / OUTRANKED / SUPERSEDED package for an entity.", {"entity": STR}, ["entity"]),
    "why": ("Provenance (from, source, date, log claims) for the best match.", {"query": STR}, ["query"]),
    "propose": ("Propose a fact. Writes one file to inbox/ for the curator; never touches canon.",
                {"text": STR, "from_agent": STR, "source": STR}, ["text", "from_agent", "source"]),
}


def call(name: str, a: dict):
    if name == "search":
        return brain.search(a["query"], int(a.get("k", 5)))
    if name == "answer":
        from cite import cited_answer
        return cited_answer(a["query"])
    if name == "compile":
        return brain.compile_entity(a["entity"])
    if name == "why":
        return brain.why(a["query"])
    if name == "propose":
        p = brain.propose(a["text"], a["from_agent"], a["source"])
        return {"proposed": p.relative_to(brain.VAULT).as_posix()}
    raise KeyError(name)


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None  # notification
    try:
        if method == "initialize":
            res = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "second-brain", "version": "0.1"}}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": [{"name": n, "description": d,
                              "inputSchema": {"type": "object", "properties": p, "required": r}}
                             for n, (d, p, r) in TOOLS.items()]}
        elif method == "tools/call":
            prm = msg.get("params", {})
            if prm.get("name") not in TOOLS:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
            try:
                out = call(prm["name"], prm.get("arguments") or {})
                res = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": False}
            except (KeyError, ValueError) as exc:
                res = {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    except Exception as exc:  # never kill the session
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
