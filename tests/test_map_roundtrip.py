"""调用已安装CAIME序列化并重读小地图，核对普通陆路无法进入围合区。"""

import json
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


@unittest.skipUnless(os.environ.get("FNVTW_INTEGRATION") == "1",
                     "需明确启用真实CAIME集成检查")
class MapRoundtripTests(unittest.TestCase):
    def test_mainland_is_connected_and_enclave_is_separate_after_reload(self):
        with tempfile.TemporaryDirectory(prefix="fnvtw_map_") as folder:
            environment = load_environment()
            result = subprocess.run([environment["powershell"], "-NoProfile", "-File",
                str(ROOT / "build_map.ps1"), "-OutputDirectory", folder,
                "-CaimeDirectory", environment["caime_dir"],
                "-DatabaseDirectory", str(Path(environment["assembly_kit"]) / "raw_data/db"),
                "-ScenarioPath", str(PROJECT / "content/prototype/场景.json")],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["map"], "fnvtw_prototype_map")
            self.assertEqual([data["width"], data["height"]], [64, 64])
            self.assertEqual(data["town_count"], 3)
            self.assertEqual(data["passable_components"], 2)
            self.assertEqual(data["region_count"], 3)
            self.assertGreater((Path(folder) / "map.hex").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
