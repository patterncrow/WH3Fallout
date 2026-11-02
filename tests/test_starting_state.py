"""重读真实样板包，检查开局归属与军队引用形成完整对象链。"""

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


@unittest.skipUnless(os.environ.get("FNVTW_INTEGRATION") == "1", "需启用真实工具集成检查")
class StartingStateTests(unittest.TestCase):
    def test_two_playable_factions_and_local_guard_have_owned_towns_and_armies(self):
        with tempfile.TemporaryDirectory(prefix="fnvtw_start_") as folder:
            output = Path(folder) / "fnvtw_starting_state.pack"
            map_stage = Path(folder) / "fnvtw_map_stage.pack"
            prepared = subprocess.run([sys.executable, str(ROOT / "build_pack.py"),
                "--map-workspace", str(Path(os.environ.get("FNVTW_MAP_WORKSPACE", PROJECT / "work/legacy-20261102/kit"))), "--output", str(map_stage)],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            result = subprocess.run([sys.executable, str(ROOT / "build_starting_state.py"),
                "--input", str(map_stage),
                "--output", str(output)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with RpfmClient() as client:
                client.tool("set_game", game="warhammer_3", rebuild_dependencies=False)
                pack = client.tool("open_pack", paths=[str(output)])
                def rows(table):
                    data = client.tool("table_rows", file={"source": {"pack": pack["key"]},
                        "path": "db/" + table + "_tables/fnvtw_prototype"})
                    return [dict(zip(data["columns"], r["values"])) for r in data["rows"]]
                try:
                    factions = rows("start_pos_factions")
                    self.assertEqual(len(factions), 3)
                    self.assertEqual(sum(f["playable"] for f in factions), 2)
                    self.assertEqual({f["campaign"] for f in factions}, {"fnvtw_prototype"})
                    faction_ids = {f["ID"] for f in factions}
                    regions = rows("start_pos_regions")
                    self.assertEqual(len(regions), 3)
                    self.assertEqual({r["owning_faction"] for r in regions}, faction_ids)
                    self.assertEqual(len(rows("start_pos_settlements")), 3)
                    files = client.tool("list_files", source={"pack": pack["key"]},
                        path_prefix="db/campaign_map_settlements_tables/", limit=2)
                    self.assertTrue(files["files"], "开局城镇必须有对应的地图聚落记录")
                    self.assertEqual({s["settlement_id"] for s in rows("start_pos_settlements")},
                        {s["settlement_id"] for s in rows("campaign_map_settlements")})
                    characters = rows("start_pos_characters")
                    self.assertEqual({c["faction"] for c in characters}, faction_ids)
                    self.assertEqual(len(characters), 3)
                    units = rows("start_pos_land_units")
                    self.assertEqual({u["general"] for u in units}, {c["ID"] for c in characters})
                    self.assertEqual(len(rows("start_pos_starting_general_options")), 2)
                finally:
                    client.tool("close_pack", pack=pack["key"])


if __name__ == "__main__":
    unittest.main()
