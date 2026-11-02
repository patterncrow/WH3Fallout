"""转换真实AK输出，并使用CAIME自带的独立ESF库检查游戏格式。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "scripts"
sys.path.insert(0, str(ROOT))
from project_paths import load_environment


@unittest.skipUnless(os.environ.get("FNVTW_INTEGRATION") == "1", "需启用真实工具集成检查")
class EsfConversionTests(unittest.TestCase):
    def test_game_codec_can_load_converted_map_without_changing_native_output(self):
        source = Path(os.environ.get("FNVTW_MAP_WORKSPACE", PROJECT / "work/legacy-20261102/kit")) / "working_data/campaign_maps/fnvtw_prototype_map/map_data.esf"
        before = source.read_bytes()
        with tempfile.TemporaryDirectory(prefix="fnvtw_esf_") as folder:
            output = Path(folder) / "map_data.esf"
            result = subprocess.run([sys.executable, str(ROOT / "convert_map.py"),
                "--input", str(source), "--output", str(output)],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(output.read_bytes()[:4], b"\xca\xab\0\0")
            # 独立库只支持游戏的ABCA，不用同一个转换器自说自话。
            environment = load_environment()
            library = str(Path(environment["caime_dir"]) / "EsfLibrary.dll").replace("'", "''")
            script = ("$ErrorActionPreference='Stop'; "
                "$null=[Reflection.Assembly]::LoadFrom('" + library + "'); "
                "$file=[EsfLibrary.EsfCodecUtil]::LoadEsfFile('" + str(output) + "'); "
                "$file.Codec.GetType().Name")
            check = subprocess.run([environment["powershell"],
                "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertIn("AbcaFileCodec", check.stdout)


if __name__ == "__main__":
    unittest.main()
