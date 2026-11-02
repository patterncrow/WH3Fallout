"""在隔离的AK工作目录里执行CAIME验证和地图处理。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "scripts"


@unittest.skipUnless(os.environ.get("FNVTW_INTEGRATION") == "1", "需启用真实工具集成检查")
class MapProcessingTests(unittest.TestCase):
    def test_caime_accepts_custom_regions_and_exports_map_data(self):
        with tempfile.TemporaryDirectory(prefix="fnvtw_kit_") as folder:
            result = subprocess.run([sys.executable, str(ROOT / "process_map.py"),
                "--workspace", folder], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            exports = Path(folder) / "working_data/campaign_maps/fnvtw_prototype_map"
            self.assertTrue((exports / "map_data.esf").is_file())
            self.assertTrue(list(exports.glob("*.ppd")))
            self.assertTrue((exports / "display/borders/borders.pbd").is_file())


if __name__ == "__main__":
    unittest.main()
