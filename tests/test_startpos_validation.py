"""开局校验必须等待真实结果，报告错误并释放自己打开的包。"""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, call

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StartposValidationTests(unittest.TestCase):
    def module(self):
        path = ROOT / "scripts/validate_starting_state.py"
        self.assertTrue(path.is_file(), "缺少可重复调用的开局校验步骤")
        spec = importlib.util.spec_from_file_location("validate_starting_state", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_async_validation_writes_actual_result_and_closes_own_pack(self):
        module = self.module()
        client = Mock()
        client.tool.side_effect = [{}, {"key": "ours"}, {"job": 42}, {}]
        client.wait_job.return_value = {"issues": []}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "validation.json"
            module.validate(client, Path(folder) / "input.pack", output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"issues": []})
        client.wait_job.assert_called_once_with(42)
        self.assertEqual(client.tool.call_args, call("close_pack", pack="ours"))

    def test_error_report_is_preserved_and_blocks_the_next_step(self):
        module = self.module()
        report = {"issues": [{"level": "error", "message": "missing reference"}]}
        client = Mock()
        client.tool.side_effect = [{}, {"key": "ours"}, report, {}]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "validation.json"
            with self.assertRaisesRegex(ValueError, "校验"):
                module.validate(client, Path(folder) / "input.pack", output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
        self.assertEqual(client.tool.call_args, call("close_pack", pack="ours"))


if __name__ == "__main__":
    unittest.main()
