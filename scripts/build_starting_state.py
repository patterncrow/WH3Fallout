"""为地图阶段包增加独立派系与三城开局；原版人物、文化及资产仅作占位。"""

import argparse
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

from project_paths import ROOT, load_environment, load_scenario
from rpfm_rpc import RpfmClient


SCENARIO = load_scenario()
CAMPAIGN = SCENARIO["id"]
ACTORS = tuple((a["label"], a["prototype_faction"], a["region"],
                *a["position"], a["playable"]) for a in SCENARIO["actors"])


def starting_records(ak):
    cache = {}
    def source(table):
        if table not in cache:
            cache[table] = [{x.tag: x.text or "" for x in row}
                for row in ET.parse(ak / "raw_data/db" / (table + ".xml")).getroot().findall(table)]
        return cache[table]

    def find(table, **filters):
        return next(row.copy() for row in source(table)
                    if all(row.get(k) == v for k, v in filters.items()))

    records = defaultdict(list)
    calendar = find("start_pos_calendars", campaign="wh3_main_combi")
    calendar["campaign"] = CAMPAIGN
    records["start_pos_calendars"].append(calendar)
    for index, (label, original, region, x, y, playable) in enumerate(ACTORS):
        # 按对象类型留出编号段，避免重映射时将城镇、人物、派系ID混用。
        actor = SCENARIO["actors"][index]
        faction_id, region_id = actor["faction_id"], actor["region_id"]
        character_id, settlement_id = actor["character_id"], actor["settlement_id"]
        key = "fnvtw_" + label
        faction = find("start_pos_factions", faction=original, campaign="wh3_main_combi")
        old_faction_id = faction["ID"]
        faction.update(ID=faction_id, faction=key, campaign=CAMPAIGN,
                       playable=str(int(playable)), is_major=str(int(playable)),
                       treasury="5000", starting_order=str(index + 1))
        records["start_pos_factions"].append(faction)

        capital = find("start_pos_regions", owning_faction=old_faction_id, faction_capital="1")
        old_region_id, old_region = capital["id"], capital["region"]
        subculture = find("factions", key=original)["subculture"]
        capital.update(id=region_id, region=region, campaign=CAMPAIGN,
                       owning_faction=faction_id, rebel_faction=key, cultural_originator=subculture)
        records["start_pos_regions"].append(capital)
        settlement = find("start_pos_settlements", region=old_region_id)
        settlement.update(id=settlement_id, region=region_id,
                          settlement_id="settlement:settlement:" + region,
                          onscreen_name=key + "_town")
        records["start_pos_settlements"].append(settlement)
        for slot_index, row in enumerate(source("start_pos_region_slot_templates")):
            if row["campaign"] == "wh3_main_combi" and row["region"] == old_region:
                slot = row.copy()
                slot.update(id=str(actor["slot_id_base"] + slot_index),
                            campaign=CAMPAIGN, region=region)
                records["start_pos_region_slot_templates"].append(slot)

        character = find("start_pos_characters", faction=old_faction_id,
                         ministerial_position="faction_leader")
        old_character_id = character["ID"]
        character.update(ID=character_id, faction=faction_id, startx=str(x), starty=str(y))
        records["start_pos_characters"].append(character)
        # 将六个既有部队配给每个可选领主；领主本人由override_general_unit生成。
        for unit_spec in actor["starting_units"]:
            unit = find("start_pos_land_units", id=unit_spec["prototype_id"],
                        unit_type=unit_spec["prototype_unit"], general=old_character_id)
            unit.update(id=unit_spec["id"], general=character_id)
            records["start_pos_land_units"].append(unit)
        if playable:
            records["start_pos_starting_general_options"].append({
                "id": actor["general_option_id"], "general": character_id, "precedence": "0",
                "frontend_faction_leader": key + "_leader", "exclude_other_options": "0"})

    # 双方开局敌对；围合守军亦为敌对对象，后续传送子例可直接检查战斗。
    for index, (left, right) in enumerate(((0, 1), (0, 2), (1, 2))):
        row = source("start_pos_diplomacy")[0].copy()
        row.update(key=str(2140100501 + index), faction1=SCENARIO["actors"][left]["faction_id"],
                   faction2=SCENARIO["actors"][right]["faction_id"], stance="war",
                   grants_military_access="0", grants_trade_agreement="0",
                   relations_modifier="0", non_aggression_pact="0")
        records["start_pos_diplomacy"].append(row)
    return records


def insert_rows(client, pack, table, rows, version=None):
    name = table + "_tables"
    path = "db/" + name + "/fnvtw_prototype"
    kind = {"type": "db", "table_name": name}
    if version is not None:
        kind["version"] = version
    client.tool("create_file", pack=pack, path=path, kind=kind)
    info = client.tool("table_info", file={"source": {"pack": pack}, "path": path})
    edits = []
    for row in rows:
        values = {}
        for column in info["columns"]:
            key, field_type = column["name"], column["field_type"]
            if key not in row:
                continue
            value = row[key]
            if field_type == "Boolean" and isinstance(value, str):
                value = value == "1"
            elif field_type in ("I16", "I32", "I64", "OptionalI16", "OptionalI32", "OptionalI64") and isinstance(value, str):
                value = int(value or column.get("default_value") or 0)
            elif field_type in ("F32", "F64") and isinstance(value, str):
                value = float(value or column.get("default_value") or 0)
            values[key] = value
        edits.append({"op": "insert", "values": values})
    client.tool("edit_table", pack=pack, path=path, edits=edits)


def build(source_path, output):
    game_root = Path(load_environment()["game_root"]).resolve()
    ak_root = Path(load_environment()["assembly_kit"]).resolve()
    source_path, output = Path(source_path).resolve(), Path(output).resolve()
    if output.exists() or output == source_path:
        raise ValueError("开局包必须另存为新的文件")
    if not output.name.startswith("fnvtw_") or output.suffix != ".pack":
        raise ValueError("输出必须使用fnvtw_前缀及.pack扩展名")
    if output.is_relative_to(game_root):
        raise ValueError("先在项目中构建，不直接写游戏目录")
    records = starting_records(ak_root)
    with RpfmClient() as client:
        client.tool("set_game", game="warhammer_3", rebuild_dependencies=False)
        vanilla = client.tool("open_pack", paths=[str(game_root / "data/db.pack")], lazy_loading=True)
        target = client.tool("open_pack", paths=[str(source_path)])
        try:
            # 开局编译会读取这里声明的图像，拒绝继续使用旧的缺资源地图包。
            area_data = client.tool("table_rows", file={"source": {"pack": target["key"]},
                "path": "db/campaign_map_playable_areas_tables/fnvtw_prototype"}, limit=2)
            area = dict(zip(area_data["columns"], area_data["rows"][0]["values"]))
            files = client.tool("list_files", source={"pack": target["key"]},
                path_prefix="campaign_maps/fnvtw_prototype_map/", limit=100)
            paths = {file["path"] for file in files["files"]}
            for field in ("map_file", "radar_file", "overlay_file", "minimap_lookup_file"):
                if "campaign_maps/fnvtw_prototype_map/" + area[field] not in paths:
                    raise ValueError("地图阶段包缺少声明资源：" + field)
            runtime, versions = defaultdict(list), {}
            for index, (label, original, _, _, _, playable) in enumerate(ACTORS):
                key = "fnvtw_" + label
                tables = [("factions", "key")]
                if playable:
                    tables += [("frontend_factions", "faction"),
                               ("frontend_faction_leaders", "faction"),
                               ("frontend_faction_groups_to_factions", "faction_key")]
                for table, column in tables:
                    ref = {"source": {"pack": vanilla["key"]}, "path": "db/" + table + "_tables/data__"}
                    versions[table] = client.tool("table_info", file=ref)["version"]
                    data = client.tool("table_rows", file=ref, filters=[{
                        "column": column, "op": "equals", "value": original}], limit=10)
                    if not data["rows"]:
                        raise ValueError("原版前端模板缺失：" + table + "/" + original)
                    row = dict(zip(data["columns"], data["rows"][0]["values"]))
                    row[column] = key
                    if table == "factions":
                        row["index"] = SCENARIO["actors"][index]["runtime_faction_index"]
                        row["is_rebel"] = False
                    elif table == "frontend_faction_leaders":
                        row.update(key=key + "_leader", prelude_battle="", show_full_intro_option=False)
                    elif table == "frontend_faction_groups_to_factions":
                        row.update(is_major_faction=True, show_in_frontend=True)
                    runtime[table].append(row)
            table = "campaign_map_settlements"
            ref = {"source": {"pack": vanilla["key"]}, "path": "db/" + table + "_tables/data__"}
            versions[table] = client.tool("table_info", file=ref)["version"]
            sample = client.tool("table_rows", file=ref, limit=1)
            baseline = dict(zip(sample["columns"], sample["rows"][0]["values"]))
            for _, _, region, _, _, _ in ACTORS:
                row = baseline.copy()
                row["settlement_id"] = "settlement:settlement:" + region
                runtime[table].append(row)
            for table, rows in runtime.items():
                insert_rows(client, target["key"], table, rows, versions[table])
            for table, rows in records.items():
                insert_rows(client, target["key"], table, rows)
            loc_path = "text/db/fnvtw_prototype.loc"
            client.tool("create_file", pack=target["key"], path=loc_path, kind={"type": "loc"})
            translations = {
                "campaign_map_playable_areas_onscreen_name_2140000001": "辐射：废土战争（技术样板）",
                "campaign_map_playable_areas_onscreen_description_2140000001":
                    "独立战役技术样板。NCR与凯撒军团使用原版文化、人物和部队占位；当前不代表正式内容。",
            }
            for label, title in (("ncr", "NCR样板集团"), ("legion", "凯撒军团样板集团"),
                                 ("local_guard", "围合区地方守军")):
                translations["factions_screen_name_fnvtw_" + label] = title
            for region, title in (("ncr", "NCR试验据点"), ("legion", "军团试验据点"),
                                  ("enclave", "围合区试验据点")):
                translations["regions_onscreen_fnvtw_" + region + "_town"] = title
                translations["provinces_onscreen_fnvtw_" + region + "_town_province"] = title
            client.tool("edit_table", pack=target["key"], path=loc_path, edits=[
                {"op": "insert", "values": {"key": key, "text": text, "tooltip": False}}
                for key, text in translations.items()])
            script = ROOT / "content/script/campaign/fnvtw_prototype/scripting.lua"
            client.tool("add_files_from_disk", pack=target["key"], paths=[str(script.resolve())],
                        pack_paths=["script/campaign/fnvtw_prototype/scripting.lua"])
            client.tool("save_pack", pack=target["key"], path=str(output), allow_editing_ca_packs=False)
        finally:
            client.tool("close_pack", pack=target["key"])
            client.tool("close_pack", pack=vanilla["key"])
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(build(args.input, args.output))
