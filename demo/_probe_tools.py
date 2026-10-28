
import json, os
from pathlib import Path
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
import httpx
tools = [{
  "type": "function",
  "function": {
    "name": "query_metrics",
    "description": "查询事件时间窗内的指标序列（磁盘、CPU、网络）",
    "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"], "additionalProperties": False},
  },
}]
payload = {"model": "deepseek-flash",
           "messages": [{"role": "system", "content": "只能从给定工具中选择，不需要就返回空。"},
                        {"role": "user", "content": json.dumps({"event_id": "evt_1", "components": ["DataNode"], "metrics_available": True})}],
           "tools": tools, "tool_choice": "auto", "temperature": 0, "max_tokens": 200, "stream": False}
r = httpx.post("https://api.deepseek.com/chat/completions",
               headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]},
               json=payload, timeout=60, trust_env=False)
print("HTTP", r.status_code)
data = r.json()
if r.status_code == 200:
    msg = data["choices"][0]["message"]
    print("finish:", data["choices"][0].get("finish_reason"))
    print("tool_calls:", json.dumps(msg.get("tool_calls"), ensure_ascii=False)[:400])
    print("content:", repr(msg.get("content"))[:200])
    print("usage:", data.get("usage"))
else:
    print(r.text[:400])
