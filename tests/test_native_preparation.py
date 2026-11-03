"""原生编译交接只准备副本和恢复依据，不改真实游戏环境。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class NativePreparationTests(unittest.TestCase):
    def module(self):
        path = ROOT / "scripts/prepare_native.py"
        self.assertTrue(path.is_file(), "缺少原生编译交接准备步骤")
        spec = importlib.util.spec_from_file_location("prepare_native", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def inputs(self, root):
        folder = root / "work/input"
        folder.mkdir(parents=True)
        source = folder / "fnvtw_prototype_starting_state.pack"
        source.write_bytes(b"test-input")
        (folder / "manifest.json").write_text(json.dumps({"status": "succeeded", "outputs": [
            {"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}), encoding="utf-8")
        (folder / "startpos-validation.json").write_text('{"issues": []}', encoding="utf-8")
        return source

    def test_preparation_backs_up_existing_files_without_changing_them(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = self.inputs(root)
            user_script = root / "config/user.script.txt"
            user_script.parent.mkdir()
            user_script.write_bytes(b"existing-mod-setting")
            loose = root / "game/data/campaigns/fnvtw_prototype/startpos.esf"
            loose.parent.mkdir(parents=True)
            loose.write_bytes(b"previous-generated-file")
            report = module.prepare(root, "input", "native-001", root / "game", user_script)
            self.assertEqual(report["status"], "awaiting_operator")
            self.assertEqual(user_script.read_bytes(), b"existing-mod-setting")
            self.assertEqual(loose.read_bytes(), b"previous-generated-file")
            self.assertFalse(Path(report["deployment_target"]).exists())
            self.assertEqual((root / report["staged_pack"]).read_bytes(), source.read_bytes())
            for item in report["before"]:
                if item["exists"]:
                    self.assertEqual((root / item["backup"]).read_bytes(), Path(item["target"]).read_bytes())

    def test_changed_input_is_rejected_before_creating_handoff(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = self.inputs(root)
            source.write_bytes(b"changed-after-build")
            with self.assertRaisesRegex(ValueError, "摘要"):
                module.prepare(root, "input", "native-001", root / "game", root / "config/user.script.txt")
            self.assertFalse((root / "work/native-001").exists())

    def test_existing_handoff_and_path_escape_are_rejected(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.inputs(root)
            (root / "work/native-001").mkdir()
            with self.assertRaises(FileExistsError):
                module.prepare(root, "input", "native-001", root / "game", root / "config/user.script.txt")
            with self.assertRaises(ValueError):
                module.prepare(root, "input", "../outside", root / "game", root / "config/user.script.txt")


if __name__ == "__main__":
    unittest.main()
