#!/usr/bin/env python3
"""xiaohongshu-mcp HTTP 客户端：python mcp_call.py <tool> [json_args]"""
import json
import sys
import urllib.request

URL = "http://localhost:18060/mcp"
# 本机服务不走系统代理，否则会被代理拦成 502
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(payload, sid=None, timeout=180):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(URL, json.dumps(payload).encode(), headers)
    with OPENER.open(req, timeout=timeout) as r:
        raw = r.read().decode()
        new_sid = r.headers.get("Mcp-Session-Id")
    # SSE 解析
    if raw.lstrip().startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                break
    return (json.loads(raw) if raw.strip() else None), new_sid


def main():
    tool = sys.argv[1] if len(sys.argv) > 1 else None
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    init, sid = post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "wb-cli", "version": "1"}},
    })
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)

    if tool is None or tool == "list":
        res, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
        for t in res["result"]["tools"]:
            print(t["name"], "—", (t.get("description") or "")[:100].replace("\n", " "))
        return

    res, _ = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": tool, "arguments": args}}, sid)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
