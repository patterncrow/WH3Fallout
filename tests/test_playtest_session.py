"""游玩部署与恢复的真实文件合同；只在临时目录操作。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class PlaytestSessionTests(unittest.TestCase):
    def module(self):
        path = ROOT / "scripts/playtest_session.py"
        self.assertTrue(path.is_file(), "尚未收拢游玩部署与恢复步骤")
        spec = importlib.util.spec_from_file_location("playtest_session", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, root):
        game = root / "game"
        (game / "data").mkdir(parents=True)
        script = root / "config/user.script.txt"
        script.parent.mkdir()
        script.write_bytes(b"original-setting")
        for relative in ("campaigns/fnvtw_prototype/startpos.esf",
                         "campaign_maps/fnvtw_prototype_map/hlp_data.esf",
                         "campaign_maps/fnvtw_prototype_map/spd_data.esf"):
            path = game / "data" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode("utf-8"))
        native = root / "work/native"
        native.mkdir(parents=True)
        source = native / "fnvtw_compiled.pack"
        source.write_bytes(b"compiled-input")
        proof = {"status": "clean_native_import_passed", "clean_mod_environment": True,
                 "output": source.relative_to(root).as_posix(),
                 "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        (native / "native-import.json").write_text(json.dumps(proof), encoding="utf-8")
        return game, script, source

    def deploy(self, module, root, game, script):
        return module.deploy(root, "native", "test-001", game, script, game_running=lambda: False)

    def test_roundtrip_restores_all_files_and_repeated_restore_keeps_original_report(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script, source = self.fixture(root)
            plan = self.deploy(module, root, game, script)
            self.assertNotIn("quit_after", script.read_text(encoding="utf-8"))
            for item in plan["before"][2:]:
                self.assertFalse(Path(item["target"]).exists())
            inspected = module.status(root, "test-001", game, script)
            self.assertTrue(inspected["matches_deployed"])
            self.assertFalse(inspected["matches_before"])
            result = module.restore(root, "test-001", game, script, game_running=lambda: False)
            self.assertEqual(result["status"], "restored")
            self.assertTrue(all(x["matches_before"] for x in result["checks"]))
            self.assertEqual(script.read_bytes(), b"original-setting")
            self.assertTrue(source.is_file())
            saved = (root / "work/test-001/restoration.json").read_bytes()
            module.restore(root, "test-001", game, script, game_running=lambda: False)
            self.assertEqual((root / "work/test-001/restoration.json").read_bytes(), saved)

    def test_user_change_blocks_all_restore_operations(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script, _ = self.fixture(root)
            plan = self.deploy(module, root, game, script)
            script.write_bytes(b"user-new-setting")
            with self.assertRaisesRegex(ValueError, "冲突"):
                module.restore(root, "test-001", game, script, game_running=lambda: False)
            self.assertTrue(Path(plan["deployment_target"]).is_file())
            self.assertEqual(script.read_bytes(), b"user-new-setting")
            self.assertFalse(Path(plan["before"][2]["target"]).exists())

    def test_missing_backup_blocks_restore_before_any_file_is_changed(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script, _ = self.fixture(root)
            plan = self.deploy(module, root, game, script)
            (root / plan["before"][3]["backup"]).unlink()
            script_before = script.read_bytes()
            with self.assertRaises(FileNotFoundError):
                module.restore(root, "test-001", game, script, game_running=lambda: False)
            self.assertEqual(script.read_bytes(), script_before)
            self.assertTrue(Path(plan["deployment_target"]).is_file())

    def test_running_game_prevents_deploy_and_restore(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script, _ = self.fixture(root)
            with self.assertRaisesRegex(RuntimeError, "游戏"):
                module.deploy(root, "native", "test-001", game, script, game_running=lambda: True)
            self.assertFalse((root / "work/test-001").exists())
            plan = self.deploy(module, root, game, script)
            with self.assertRaisesRegex(RuntimeError, "游戏"):
                module.restore(root, "test-001", game, script, game_running=lambda: True)
            self.assertTrue(Path(plan["deployment_target"]).is_file())

    def test_changed_source_and_existing_run_do_not_overwrite_anything(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script, source = self.fixture(root)
            source.write_bytes(b"changed-input")
            with self.assertRaisesRegex(ValueError, "摘要"):
                self.deploy(module, root, game, script)
            self.assertFalse((root / "work/test-001").exists())
            source.write_bytes(b"compiled-input")
            self.deploy(module, root, game, script)
            deployed = script.read_bytes()
            with self.assertRaises(FileExistsError):
                self.deploy(module, root, game, script)
            self.assertEqual(script.read_bytes(), deployed)

    def test_manifest_cannot_expand_restore_scope_to_vanilla_files(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script, _ = self.fixture(root)
            plan = self.deploy(module, root, game, script)
            vanilla = game / "data/db.pack"
            vanilla.write_bytes(b"vanilla")
            plan["before"][2]["target"] = str(vanilla)
            path = root / "work/test-001/manifest.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "范围"):
                module.restore(root, "test-001", game, script, game_running=lambda: False)
            self.assertEqual(vanilla.read_bytes(), b"vanilla")
            self.assertTrue(Path(plan["deployment_target"]).is_file())

    def test_manual_recovery_does_not_return_an_outdated_conflict_report(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game, script, _ = self.fixture(root)
            plan = self.deploy(module, root, game, script)
            script.write_bytes(b"user-change")
            with self.assertRaises(ValueError):
                module.restore(root, "test-001", game, script, game_running=lambda: False)
            for item in plan["before"]:
                path = Path(item["target"])
                if item["exists"]:
                    shutil.copy2(root / item["backup"], path)
                elif path.is_file():
                    path.unlink()
            result = module.restore(root, "test-001", game, script, game_running=lambda: False)
            self.assertEqual(result["status"], "restored")


if __name__ == "__main__":
    unittest.main()
