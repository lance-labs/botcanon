#!/usr/bin/env python3
"""End-to-end MCP test: spawn the server over stdio against a temp copy of the vault."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        v = Path(d) / "vault"
        shutil.copytree(ROOT, v, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
        env = {**os.environ, "BRAIN_VAULT": str(v)}
        subprocess.run([sys.executable, str(v / "tools/brain.py"), "ingest"], env=env, check=True, capture_output=True)
        canon_before = {p: p.read_bytes() for p in v.rglob("*.md") if "inbox" not in p.parts}
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "who supplies our flour"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "answer", "arguments": {"query": "zxqv blorptastic"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "compile", "arguments": {"entity": "opening-hours"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "propose", "arguments": {"text": "Rye arrives Fridays.", "from_agent": "mcp-test", "source": "test"}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "write_canon", "arguments": {}}},
        ]
        p = subprocess.run([sys.executable, str(v / "tools/mcp_server.py")], env=env, capture_output=True, text=True,
                           input="\n".join(json.dumps(r) for r in reqs) + "\n", timeout=300)
        out = {m["id"]: m for m in map(json.loads, p.stdout.splitlines())}
        body = lambda i: json.loads(out[i]["result"]["content"][0]["text"])
        errs = []
        if out[1]["result"]["serverInfo"]["name"] != "second-brain": errs.append("initialize")
        if sorted(t["name"] for t in out[2]["result"]["tools"]) != ["answer", "compile", "propose", "search", "why"]: errs.append("tools/list")
        if "people/ari-novak.md" not in [h["path"] for h in body(3)[:3]]: errs.append("search")
        if body(4)["known"]: errs.append("answer should not know")
        if not body(5)["outranked"]: errs.append("compile OUTRANKED empty")
        prop = body(6)["proposed"]
        if not prop.startswith("inbox/") or not (v / prop).exists(): errs.append("propose")
        if "error" not in out[7]: errs.append("unknown tool accepted")
        after = {p: p.read_bytes() for p in v.rglob("*.md") if "inbox" not in p.parts}
        if after != canon_before: errs.append("canon changed")
        print("test_mcp:", "PASS" if not errs else "FAIL " + ", ".join(errs))
        return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
