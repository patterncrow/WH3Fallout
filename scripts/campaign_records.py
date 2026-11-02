"""生成只新增项目记录的战役注册数据，不修改原版模板。"""

from copy import deepcopy
import re
from project_paths import load_scenario


def build_campaign_records(campaign_template, area_template,
                           campaign_key="fnvtw_prototype"):
    if not re.fullmatch(r"fnvtw_[a-z0-9_]+", campaign_key):
        raise ValueError("独立战役标识必须使用 fnvtw_ 前缀与小写ASCII字符")

    scenario = load_scenario()
    map_key = campaign_key + "_map"
    campaign = deepcopy(campaign_template)
    campaign.update(campaign_name=campaign_key, map_name=map_key,
                    display_location=map_key,
                    script_path="script/campaign/" + campaign_key,
                    available_for_mp=False)

    area = deepcopy(area_template)
    area.update(mapname=map_key, campaign_key=campaign_key,
                index=scenario["playable_area_index"], minx=0.0, maxx=float(scenario["map"]["width"]),
                sort_order=100, is_mpc_available=False,
                map_file=campaign_key + "_map.png", radar_file=campaign_key + "_map.png",
                overlay_file=campaign_key + "_lookup.tga",
                minimap_lookup_file=campaign_key + "_lookup_minimap.tga",
                campaign_overlay_lookup="", campaign_overlay_map="", campaign_overlay_map_text="")
    return {
        "campaigns_tables": [campaign],
        "campaign_map_playable_areas_tables": [area],
    }
