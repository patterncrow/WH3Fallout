"""通过RPFM生成注册或地图阶段样板；尚不包含可启动的startpos。"""

import argparse
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from campaign_records import build_campaign_records
from convert_map import convert
from rpfm_rpc import RpfmClient
from project_paths import load_environment


def build_pack(output, game_root=None, map_workspace=None):
    game_root = Path(game_root or load_environment()["game_root"]).resolve()
    output = Path(output).resolve()
    if output.suffix != ".pack" or not output.name.startswith("fnvtw_"):
        raise ValueError("样板包必须使用 fnvtw_ 前缀及 .pack 扩展名")
    if output.exists():
        raise FileExistsError("不覆盖已有文件：" + str(output))
    if output.is_relative_to(Path(game_root).resolve()):
        raise ValueError("构建产物先保存在项目中，不能直接写入游戏目录")

    with tempfile.TemporaryDirectory(prefix="fnvtw_build_") as staging, RpfmClient() as client:
        client.tool("set_game", game="warhammer_3", rebuild_dependencies=False)
        source = client.tool("open_pack", paths=[str(game_root / "data/db.pack")],
                             lazy_loading=True)
        target = None
        try:
            templates, versions = {}, {}
            for table, column in (("campaigns_tables", "campaign_name"),
                                  ("campaign_map_playable_areas_tables", "campaign_key")):
                ref = {"source": {"pack": source["key"]},
                       "path": "db/" + table + "/data__"}
                versions[table] = client.tool("table_info", file=ref)["version"]
                data = client.tool("table_rows", file=ref, filters=[{
                    "column": column, "op": "equals", "value": "wh3_main_combi"}], limit=2)
                if len(data["rows"]) != 1:
                    raise RuntimeError("原版模板缺失或不唯一：" + table)
                templates[table] = dict(zip(data["columns"], data["rows"][0]["values"]))

            records = build_campaign_records(templates["campaigns_tables"],
                         templates["campaign_map_playable_areas_tables"])
            if map_workspace is not None:
                map_workspace = Path(map_workspace).resolve()
                for table in ("regions", "provinces", "campaign_map_regions",
                              "region_to_province_junctions"):
                    name = table + "_tables"
                    ref = {"source": {"pack": source["key"]}, "path": "db/" + name + "/data__"}
                    versions[name] = client.tool("table_info", file=ref)["version"]
                    sample = client.tool("table_rows", file=ref, limit=1)
                    baseline = dict(zip(sample["columns"], sample["rows"][0]["values"]))
                    records[name] = []
                    xml = ET.parse(map_workspace / "raw_data/db" / (table + ".xml"))
                    for node in xml.getroot().findall(table):
                        if not any((child.text or "").startswith("fnvtw_") for child in node):
                            continue
                        row = baseline.copy()
                        for column, old_value in baseline.items():
                            value = node.find(column)
                            if value is not None:
                                text = value.text or ""
                                # 使用运行表的数据类型，不把AK的字符串0误作布尔真。
                                if isinstance(old_value, bool):
                                    row[column] = text == "1"
                                elif isinstance(old_value, int):
                                    row[column] = int(text)
                                elif isinstance(old_value, float):
                                    row[column] = float(text)
                                else:
                                    row[column] = text
                        if table == "regions":
                            # 运行表将AK的三个颜色通道合并为六位RGB字符串。
                            row["unnamed colour group_1"] = "".join(
                                f"{int(node.findtext(channel)):02X}" for channel in ("r", "g", "b"))
                        records[name].append(row)
            target = client.tool("new_pack", name=output.name)
            for table, rows in records.items():
                path = "db/" + table + "/fnvtw_prototype"
                client.tool("create_file", pack=target["key"], path=path,
                            kind={"type": "db", "table_name": table,
                                  "version": versions[table]})
                client.tool("edit_table", pack=target["key"], path=path,
                            edits=[{"op": "insert", "values": row} for row in rows])
            if map_workspace is not None:
                exports = map_workspace / "working_data/campaign_maps/fnvtw_prototype_map"
                converted = convert(exports / "map_data.esf", Path(staging) / "map_data.esf")
                relative_paths = ["map_data.esf", "pathfinding.ppd", "display/borders/borders.pbd",
                                  "fnvtw_prototype_map.png", "fnvtw_prototype_lookup.tga",
                                  "fnvtw_prototype_lookup_minimap.tga"]
                client.tool("add_files_from_disk", pack=target["key"],
                    paths=[str(converted)] + [str(exports / path) for path in relative_paths[1:]],
                    pack_paths=["campaign_maps/fnvtw_prototype_map/" + path for path in relative_paths])
            client.tool("save_pack", pack=target["key"], path=str(output),
                        allow_editing_ca_packs=False, clean=False)
        finally:
            if target is not None:
                client.tool("close_pack", pack=target["key"])
            client.tool("close_pack", pack=source["key"])
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--map-workspace", type=Path, help="已完成原生地图导出的隔离AK目录")
    args = parser.parse_args()
    print(build_pack(args.output, map_workspace=args.map_workspace))
