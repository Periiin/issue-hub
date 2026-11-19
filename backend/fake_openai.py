"""本地假 OpenAI 兼容服务：验证 API 通道的工具循环。

行为：
- 第 1 轮：返回 tool_calls（list_dir 或 read_file）
- 第 2 轮：再返回一次 tool_calls（read_file）
- 第 3 轮：返回最终文本，里面包含「它看到的内容摘要」

这样能验证：工具定义被发送、工具结果被正确回灌、多轮收敛、写工具只在 allow_write 时出现。

启动：python fake_openai.py 8899
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE: dict[str, int] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [
                {"id": "fake-model-a", "object": "model"},
                {"id": "fake-model-b", "object": "model"},
            ]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        tools = [t["function"]["name"] for t in (body.get("tools") or [])]

        # 用第一条 user 消息做 key，区分不同测试
        key = next((m.get("content", "")[:40] for m in messages if m.get("role") == "user"), "default")
        rounds = sum(1 for m in messages if m.get("role") == "assistant")
        tool_msgs = [m for m in messages if m.get("role") == "tool"]

        if not tools:
            # 没有工具（定性/定级场景）：直接给 JSON
            return self._json(self._completion(
                '{"title":"假数据","phenomenon":"无工具模式","repro_steps":[],'
                '"expected":"","actual":"","scope":"","module":"","uncertainties":[],"tags":[]}'))

        if rounds == 0:
            name = "list_dir" if "list_dir" in tools else tools[0]
            return self._json(self._completion(None, [{
                "id": "call_1", "type": "function",
                "function": {"name": name, "arguments": json.dumps({"path": "."})}
            }]))
        if rounds == 1:
            name = "read_file" if "read_file" in tools else tools[0]
            return self._json(self._completion(None, [{
                "id": "call_2", "type": "function",
                "function": {"name": name, "arguments": json.dumps({"path": "README.md", "start": 1, "end": 5})}
            }]))
        if rounds == 2 and "write_file" in tools:
            return self._json(self._completion(None, [{
                "id": "call_3", "type": "function",
                "function": {"name": "write_file",
                             "arguments": json.dumps({"path": "TOOL_WROTE.txt",
                                                      "content": "written by fake model\n"})}
            }]))
        # 收敛：把工具结果摘要塞进最终文本
        seen = " | ".join(m.get("content", "")[:60].replace("\n", " ") for m in tool_msgs)
        return self._json(self._completion(
            f'{{"root_cause":"fake","files":["README.md"],"changes":["{seen[:200]}"],'
            f'"verification":["ok"],"risks":[],"can_auto_fix":true}}'))

    def _completion(self, content, tool_calls=None):
        msg = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return {"id": "chatcmpl-fake", "object": "chat.completion", "model": "fake-model-a",
                "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool_calls else "stop"}]}

    def _json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print(f"fake openai on :{port}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
