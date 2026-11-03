"""隔离启动只创建本批清单，不修改玩家的TWMM或Steam配置。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class IsolatedLaunchTests(unittest.TestCase):
    def module(self):
        path = ROOT / "scripts/isolated_launch.py"
        self.assertTrue(path.is_file(), "缺少可核对的单包启动步骤")
        spec = importlib.util.spec_from_file_location("isolated_launch", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, root):
        run = root / "work/native-test"
        run.mkdir(parents=True)
        game = root / "game"
        (game / "data").mkdir(parents=True)
        (game / "Warhammer3.exe").write_bytes(b"fixture")
        pack = game / "data/fnvtw_native_test.pack"
        pack.write_bytes(b"input-fixture")
        (run / "manifest.json").write_text(json.dumps({"deployment_target": str(pack),
            "source_sha256": hashlib.sha256(pack.read_bytes()).hexdigest()}), encoding="utf-8")
        script = root / "user.script.txt"
        script.write_text('mod fnvtw_native_test.pack;\nprocess_campaign_startpos fnvtw_prototype;\n', encoding="utf-8")
        return game, script

    def test_command_uses_dedicated_empty_list_and_preserves_existing_settings(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script = self.fixture(root)
            before = script.read_bytes()
            result = module.prepare_launch(root, "native-test", game, script)
            self.assertTrue(Path(result["command"][0]).samefile(game / "Warhammer3.exe"))
            self.assertEqual(Path(result["command"][1]).read_bytes(), b"")
            self.assertEqual(result["command"][2], ";")
            self.assertEqual(script.read_bytes(), before)
            with self.assertRaises(FileExistsError):
                module.prepare_launch(root, "native-test", game, script)

    def test_other_script_mods_are_rejected(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script = self.fixture(root)
            script.write_text('mod another.pack;', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "启动脚本"):
                module.prepare_launch(root, "native-test", game, script)

    def test_movie_pack_requires_investigation_before_claiming_isolation(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script = self.fixture(root)
            (game / "data/extra.pack").write_bytes(struct.pack('<4sII', b'PFH5', 4, 0))
            with self.assertRaisesRegex(ValueError, "Movie"):
                module.prepare_launch(root, "native-test", game, script)


if __name__ == "__main__":
    unittest.main()
