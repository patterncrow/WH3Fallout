"""保护独立战役记录的隔离，避免样板覆盖原版战役或复用其入口。"""

import copy
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "campaign_records.py"


class CampaignRecordsTests(unittest.TestCase):
    def setUp(self):
        self.campaign = {
            "campaign_name": "wh3_main_combi",
            "map_name": "wh3_main_combi_map_7",
            "script_path": "script/campaign/main_warhammer",
            "terrain_location": "wh3_main_combi_map_1",
            "display_location": "wh3_main_combi_map_7",
            "available_for_mp": False,
        }
        self.area = {
            "mapname": "wh3_main_combi_map_7",
            "campaign_key": "wh3_main_combi",
            "index": 300,
            "sort_order": 1,
            "is_mpc_available": True,
            "terrain_folder": "terrain/battles/wh3_main_combi_map/",
        }

    def load_builder(self):
        # 缺少实现必须表现为明确断言失败，不用导入错误冒充测试红灯。
        self.assertTrue(MODULE_PATH.exists(), "尚未实现独立战役记录生成")
        spec = importlib.util.spec_from_file_location("campaign_records", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build_campaign_records

    def test_new_campaign_and_selection_card_point_to_the_same_new_map(self):
        build = self.load_builder()
        result = build(self.campaign, self.area)
        campaign = result["campaigns_tables"][0]
        area = result["campaign_map_playable_areas_tables"][0]
        self.assertEqual(campaign["campaign_name"], "fnvtw_prototype")
        self.assertEqual(area["campaign_key"], "fnvtw_prototype")
        self.assertEqual(campaign["map_name"], area["mapname"])
        self.assertNotEqual(campaign["map_name"], "wh3_main_combi_map_7")
        self.assertNotEqual(area["index"], 300)
        self.assertEqual(campaign["script_path"], "script/campaign/fnvtw_prototype")

    def test_borrowing_placeholder_terrain_does_not_mutate_original_records(self):
        build = self.load_builder()
        original = copy.deepcopy((self.campaign, self.area))
        result = build(self.campaign, self.area)
        self.assertEqual((self.campaign, self.area), original)
        self.assertEqual(result["campaigns_tables"][0]["terrain_location"],
                         "wh3_main_combi_map_1")
        self.assertNotEqual(result["campaigns_tables"][0]["display_location"],
                            "wh3_main_combi_map_7")
        self.assertFalse(result["campaigns_tables"][0]["available_for_mp"])
        self.assertFalse(result["campaign_map_playable_areas_tables"][0]["is_mpc_available"])

    def test_original_campaign_identifier_is_rejected(self):
        build = self.load_builder()
        with self.assertRaisesRegex(ValueError, "fnvtw_"):
            build(self.campaign, self.area, campaign_key="wh3_main_combi")


if __name__ == "__main__":
    unittest.main()
