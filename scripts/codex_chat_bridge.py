"""通过当前 Codex Desktop 的原生工具管道协调五个已有聊天。

必须从 Codex 的命令执行环境调用；不启动第二个 app-server，不写聊天数据库。
"""
import argparse
import json
import os
from pathlib import Path
import queue
import sqlite3
import struct
import sys
import threading
import uuid

LEADER = "01a18c35-fe7f-7e70-bbdf-287ab863baed"
WORKERS = (
    "01a19bfd-f717-7061-ad97-fe16fa4f13e3",
    "01a19cdd-4b2f-77d1-9b6b-743ad8aea4f1",
    "01a19cde-08c9-7e91-aa7f-a9ef377bed0f",
    "01a19cde-d289-7400-b710-220be9d3dd84",
)
# 仅本次安装聊天与 A 可派发；领域对话通过最终回复供 A 读取。
INSTALLER = "01a19eae-7a94-7522-b822-324df971de65"
TARGETS = {LEADER, *WORKERS}
TOOLS = {"read_thread", "wait_threads", "send_message_to_thread"}
MAX_FRAME = 8 * 1024 * 1024


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            raise EOFError("桌面工具管道提前关闭")
        data.extend(part)
    return bytes(data)


def read_frame(stream):
    size = struct.unpack("<I", read_exact(stream, 4))[0]
    if size > MAX_FRAME:
        raise ValueError("管道响应超出8MiB上限")
    return json.loads(read_exact(stream, size))


def write_frame(stream, value):
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FRAME:
        raise ValueError("管道请求超出8MiB上限")
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


def validate(tool, args, caller):
    if caller not in TARGETS | {INSTALLER}:
        raise PermissionError("调用者不属于本项目协作组")
    if tool not in TOOLS:
        raise ValueError("仅支持读取、等待和派发")
    targets = args.get("targets", []) if tool == "wait_threads" else [args]
    if not targets or any(t.get("threadId") not in TARGETS for t in targets):
        raise ValueError("禁止访问五个指定聊天以外的目标")
    if any(t.get("hostId", "local") != "local" for t in targets):
        raise ValueError("仅允许本地主机")
    if tool == "send_message_to_thread" and caller not in {LEADER, INSTALLER}:
        raise PermissionError("只有 A 可派发任务，安装聊天仅用于本次配置和测试")
    if tool == "send_message_to_thread" and not args.get("prompt", "").strip():
        raise ValueError("任务文本不能为空")
    if tool == "wait_threads" and not 0 <= args.get("timeoutMs", 30000) <= 45000:
        raise ValueError("单次等待必须在0到45000毫秒之间")


def native_call_id(outer_id):
    # 一个 shell 内可调用多次，桌面工具的请求标识必须逐次唯一。
    return outer_id + ":" + uuid.uuid4().hex


def caller_identity():
    caller = os.environ["CODEX_THREAD_ID"]
    call_id = native_call_id(os.environ["CODEX_TOOL_CALL_ID"])
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    # 只读取当前调用者的历史路径和真实轮次，不读取凭据、不修改数据库。
    with sqlite3.connect((home / "state_5.sqlite").as_uri() + "?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT rollout_path FROM threads WHERE id=?", (caller,)).fetchone()
    if not row:
        raise RuntimeError("找不到当前调用者的历史记录")
    turn_id = None
    with open(row[0], encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = item.get("payload", {})
            if item.get("type") == "turn_context" or (
                item.get("type") == "event_msg" and payload.get("type") == "task_started"
            ):
                turn_id = payload.get("turn_id", turn_id)
    if not turn_id:
        raise RuntimeError("未找到真实调用轮次，拒绝猜测身份")
    return caller, turn_id, call_id


def unwrap(result):
    if result.get("success") is False or result.get("isError"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    items = result.get("contentItems", result.get("content", []))
    texts = [i["text"] for i in items if "text" in i]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return {"text": texts[0]}
    return result


def call(tool, args):
    caller, turn_id, call_id = caller_identity()
    validate(tool, args, caller)
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "callerSource": "codex", "callId": call_id, "namespace": "codex_app",
            "threadId": caller, "turnId": turn_id, "tool": tool, "arguments": args,
        },
    }
    output = queue.Queue()

    def exchange():
        try:
            with open(os.environ["CODEX_APP_TOOLS_PIPE_PATH"], "r+b", buffering=0) as stream:
                write_frame(stream, request)
                output.put((True, read_frame(stream)))
        except Exception as exc:
            output.put((False, exc))

    threading.Thread(target=exchange, daemon=True).start()
    try:
        ok, response = output.get(timeout=60)
    except queue.Empty:
        # 发送超时可能已投递，禁止自动重发造成重复工作。
        raise TimeoutError("调用超过60秒；投递结果未知，请先读取目标状态，禁止盲目重发") from None
    if not ok:
        raise response
    if "error" in response:
        raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
    return unwrap(response["result"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=sorted(TOOLS))
    parser.add_argument("--args-file", type=Path, required=True, help="UTF-8 JSON工具参数")
    parser.add_argument("--output", type=Path, help="另存响应供交接和游标续读")
    opts = parser.parse_args()
    result = call(opts.tool, json.loads(opts.args_file.read_text(encoding="utf-8-sig")))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if opts.output:
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        opts.output.write_text(text + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
