"""调用已运行的本地RPFM后端；不启动后端，也不实现Pack格式。"""

import itertools
import json
import urllib.request
from project_paths import load_environment


def parse_response(body, request_id):
    text = body.strip()
    if text.startswith("{"):
        messages = [json.loads(text)]
    else:
        messages = []
        for event in body.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(line[5:].lstrip() for line in event.splitlines()
                             if line.startswith("data:")).strip()
            if data:
                messages.append(json.loads(data))
    for message in messages:
        if message.get("id") == request_id:
            return message
    raise RuntimeError("RPFM响应未包含当前请求结果")


def unpack_tool_result(response):
    if "error" in response:
        raise RuntimeError(str(response["error"]))
    result = response["result"]
    if result.get("isError"):
        raise RuntimeError(str(result.get("content", result)))
    if "structuredContent" in result:
        return result["structuredContent"]
    for content in result.get("content", []):
        if content.get("type") == "text":
            return json.loads(content["text"])
    return result


class RpfmClient:
    """每次工作使用独立会话，不接管用户前端打开的包。"""

    def __init__(self):
        self.url = load_environment()["rpfm_url"]
        self.headers = {"Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"}
        self.ids = itertools.count(1)

    def call(self, method, params=None, notification=False):
        request_id = None if notification else next(self.ids)
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if request_id is not None:
            payload["id"] = request_id
        request = urllib.request.Request(self.url,
            data=json.dumps(payload).encode("utf-8"), headers=self.headers)
        with urllib.request.urlopen(request, timeout=180) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                self.headers["Mcp-Session-Id"] = session
            body = response.read().decode("utf-8")
        return None if notification else parse_response(body, request_id)

    def tool(self, tool_name, **arguments):
        return unpack_tool_result(self.call("tools/call",
            {"name": tool_name, "arguments": arguments}))

    def __enter__(self):
        result = self.call("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "WH3Fallout-prototype", "version": "1"}})
        if "error" in result:
            raise RuntimeError(str(result["error"]))
        self.call("notifications/initialized", notification=True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if "Mcp-Session-Id" in self.headers:
            request = urllib.request.Request(self.url, method="DELETE",
                                             headers=self.headers)
            with urllib.request.urlopen(request, timeout=15):
                pass
