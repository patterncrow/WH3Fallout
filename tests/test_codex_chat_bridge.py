"""仅验证跨对话桥接，不涉及游戏或制作工具。"""
import importlib.util
import io
import json
from pathlib import Path
import struct
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/codex_chat_bridge.py"


class BridgeTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("bridge", SCRIPT)
        self.bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bridge)

    def test_utf8_frame_roundtrip(self):
        stream = io.BytesIO()
        value = {"text": "中文协作回传"}
        self.bridge.write_frame(stream, value)
        stream.seek(0)
        self.assertEqual(self.bridge.read_frame(stream), value)

    def test_truncated_frame_fails(self):
        with self.assertRaises(EOFError):
            self.bridge.read_frame(io.BytesIO(struct.pack("<I", 8) + b"{}"))

    def test_oversized_frame_fails(self):
        with self.assertRaises(ValueError):
            self.bridge.read_frame(io.BytesIO(struct.pack("<I", 9000000)))

    def test_outside_target_rejected(self):
        with self.assertRaises(ValueError):
            self.bridge.validate("read_thread", {"threadId": "unrelated"}, self.bridge.LEADER)

    def test_worker_cannot_dispatch(self):
        with self.assertRaises(PermissionError):
            self.bridge.validate("send_message_to_thread", {"threadId": self.bridge.WORKERS[0], "prompt": "任务"}, self.bridge.WORKERS[1])

    def test_leader_can_dispatch(self):
        self.bridge.validate("send_message_to_thread", {"threadId": self.bridge.WORKERS[0], "prompt": "任务"}, self.bridge.LEADER)

    def test_result_unwrap(self):
        result = {"success": True, "contentItems": [{"type": "inputText", "text": json.dumps({"polls": []})}]}
        self.assertEqual(self.bridge.unwrap(result), {"polls": []})

    def test_same_shell_multiple_calls_have_distinct_ids(self):
        first = self.bridge.native_call_id("outer-exec")
        second = self.bridge.native_call_id("outer-exec")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
