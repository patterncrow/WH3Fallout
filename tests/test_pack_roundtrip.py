"""使用真实RPFM写入后重读，检查样板包只新增自己的战役入口。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "scripts"
sys.path.insert(0, str(ROOT))
from rpfm_rpc import RpfmClient


@unittest.skipUnless(os.environ.get("FNVTW_INTEGRATION") == "1",
                     "需明确启用真实RPFM集成检查")
class PackRoundtripTests(unittest.TestCase):
    def test_map_bundle_keeps_custom_regions_and_game_format_map(self):
        with tempfile.TemporaryDirectory(prefix="fnvtw_bundle_") as folder:
            output = Path(folder) / "fnvtw_prototype_map_stage.pack"
            result = subprocess.run([sys.executable, str(ROOT / "build_pack.py"),
                "--output", str(output), "--map-workspace", str(Path(os.environ.get("FNVTW_MAP_WORKSPACE", PROJECT / "work/legacy-20261102/kit")))],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with RpfmClient() as client:
                client.tool("set_game", game="warhammer_3", rebuild_dependencies=False)
                pack = client.tool("open_pack", paths=[str(output)])
                try:
                    regions = client.tool("table_rows", file={"source": {"pack": pack["key"]},
                        "path": "db/regions_tables/fnvtw_prototype"})
                    self.assertEqual(regions["total"], 3)
                    key_column = regions["columns"].index("key")
                    self.assertTrue(all(row["values"][key_column].startswith("fnvtw_")
                                        for row in regions["rows"]))
                    area_data = client.tool("table_rows", file={"source": {"pack": pack["key"]},
                        "path": "db/campaign_map_playable_areas_tables/fnvtw_prototype"})
                    area = dict(zip(area_data["columns"], area_data["rows"][0]["values"]))
                    files = client.tool("list_files", source={"pack": pack["key"]},
                        path_prefix="campaign_maps/fnvtw_prototype_map/", limit=100)
                    paths = {file["path"] for file in files["files"]}
                    for field in ("map_file", "radar_file", "overlay_file", "minimap_lookup_file"):
                        self.assertIn("campaign_maps/fnvtw_prototype_map/" + area[field], paths,
                                      "可玩区域声明的图像必须存在：" + field)
                    client.tool("extract_files", source={"pack": pack["key"]},
                        paths=["campaign_maps/fnvtw_prototype_map/map_data.esf"], destination=folder)
                    bundled = Path(folder) / "campaign_maps/fnvtw_prototype_map/map_data.esf"
                    self.assertEqual(bundled.read_bytes()[:4], b"\xca\xab\0\0")
                finally:
                    client.tool("close_pack", pack=pack["key"])

    def test_saved_pack_registers_its_own_campaign_without_original_rows(self):
        with tempfile.TemporaryDirectory(prefix="fnvtw_pack_") as folder:
            output = Path(folder) / "fnvtw_prototype.pack"
            result = subprocess.run(
                [sys.executable, str(ROOT / "build_pack.py"), "--output", str(output)],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            with RpfmClient() as client:
                client.tool("set_game", game="warhammer_3", rebuild_dependencies=False)
                pack = client.tool("open_pack", paths=[str(output)])
                def records(table):
                    data = client.tool("table_rows", file={
                        "source": {"pack": pack["key"]},
                        "path": "db/" + table + "/fnvtw_prototype"})
                    return [dict(zip(data["columns"], row["values"]))
                            for row in data["rows"]]
                campaigns = records("campaigns_tables")
                areas = records("campaign_map_playable_areas_tables")
                self.assertEqual(len(campaigns), 1)
                self.assertEqual(campaigns[0]["campaign_name"], "fnvtw_prototype")
                self.assertEqual(len(areas), 1)
                self.assertEqual(areas[0]["campaign_key"], "fnvtw_prototype")
                self.assertEqual(areas[0]["mapname"], campaigns[0]["map_name"])
                self.assertEqual(areas[0]["index"], "2140000001")
                client.tool("close_pack", pack=pack["key"])


if __name__ == "__main__":
    unittest.main()
