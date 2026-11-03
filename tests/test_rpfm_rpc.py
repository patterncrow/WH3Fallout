"""覆盖实际遇到的SSE空事件与工具错误，避免把失败当构建成功。"""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "rpfm_rpc.py"


class RpfmProtocolTests(unittest.TestCase):
    def module(self):
        self.assertTrue(MODULE_PATH.exists(), "尚未实现RPFM本地调用适配")
        spec = importlib.util.spec_from_file_location("rpfm_rpc", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_empty_sse_control_event_does_not_hide_requested_response(self):
        module = self.module()
        body = 'data:\nid: control\n\ndata: {"jsonrpc":"2.0","id":8,"result":{"ok":true}}\n\n'
        self.assertEqual(module.parse_response(body, 8)["result"], {"ok": True})

    def test_unrelated_notification_is_not_returned_as_the_tool_result(self):
        module = self.module()
        body = ('data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
                'data: {"jsonrpc":"2.0","id":9,"result":{"value":3}}\n\n')
        self.assertEqual(module.parse_response(body, 9)["result"], {"value": 3})

    def test_rpc_or_tool_failure_stops_the_caller(self):
        module = self.module()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            module.unpack_tool_result({"error": {"message": "missing"}})
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            module.unpack_tool_result({"result": {"isError": True,
                                      "content": [{"type": "text", "text": "invalid"}]}})

    def test_structured_response_and_text_response_have_the_same_consumer_shape(self):
        module = self.module()
        self.assertEqual(module.unpack_tool_result({"result": {"structuredContent": {"rows": []}}}),
                         {"rows": []})
        self.assertEqual(module.unpack_tool_result({"result": {
            "content": [{"type": "text", "text": '{"rows": []}'}]}}), {"rows": []})

    def job_client(self, replies):
        module = self.module()
        self.assertTrue(hasattr(module.RpfmClient, "wait_job"), "缺少异步任务的终态等待")
        client = object.__new__(module.RpfmClient)
        client.tool = Mock(side_effect=replies)
        return client

    def test_job_waits_until_finished_and_returns_the_actual_result(self):
        client = self.job_client([{"state": "running"},
                                 {"state": "finished", "result": {"issues": []}}])
        self.assertEqual(client.wait_job(42), {"issues": []})
        self.assertEqual(client.tool.call_count, 2)

    def test_failed_job_does_not_look_like_a_successful_validation(self):
        client = self.job_client([{"state": "failed", "error": {"message": "invalid table"}}])
        with self.assertRaisesRegex(RuntimeError, "invalid table"):
            client.wait_job(42)

    def test_expired_wait_retains_job_identity_and_does_not_cancel_it(self):
        client = self.job_client([])
        with self.assertRaisesRegex(TimeoutError, "42"):
            client.wait_job(42, timeout=0)
        client.tool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
