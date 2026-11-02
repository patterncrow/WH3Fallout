"""制作入口的工作目录隔离与失败留痕；不需要游戏或RPFM。"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]


class MakeTests(unittest.TestCase):
    def module(self):
        path = ROOT / "制作.py"
        self.assertTrue(path.is_file(), "统一制作入口尚未实现")
        spec = importlib.util.spec_from_file_location("fnvtw_make", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_existing_build_and_invalid_identifier_are_rejected(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / "work/old"
            old.mkdir(parents=True)
            marker = old / "keep.txt"
            marker.write_text("保留", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                module.create_build_dir(root, "old")
            with self.assertRaises(ValueError):
                module.create_build_dir(root, "../outside")
            self.assertEqual(marker.read_text(encoding="utf-8"), "保留")

    def test_failed_step_keeps_manifest_logs_and_does_not_change_candidate(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "工程").mkdir()
            (root / "scripts").mkdir()
            (root / "game/data").mkdir(parents=True)
            (root / "game/data/db.pack").write_bytes(b"fixture")
            (root / "scripts/build_pack.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
            config = {"game_root": str(root / "game"), "assembly_kit": str(root / "ak"),
                      "caime_dir": str(root / "caime"), "powershell": "powershell.exe",
                      "rpfm_url": "http://127.0.0.1:45127/mcp", "declared_versions": {}}
            (root / "工程/本机配置.json").write_text(json.dumps(config), encoding="utf-8")
            (root / "工程/当前状态.json").write_text(
                json.dumps({"candidate": {"build_id": "known-candidate"}}), encoding="utf-8")
            result = module.run_build(root, "registration", "failed-run")
            manifest = json.loads((root / "work/failed-run/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 7)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["steps"][0]["returncode"], 7)
            self.assertTrue((root / "work/failed-run/registration.stderr.log").is_file())
            state = json.loads((root / "工程/当前状态.json").read_text(encoding="utf-8"))
            self.assertEqual(state["candidate"]["build_id"], "known-candidate")
            event = json.loads((root / "工程/工程日志.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["status"], "failed")


if __name__ == "__main__":
    unittest.main()
