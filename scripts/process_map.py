"""准备局部AK副本并调用CAIME处理；不写入Steam安装目录。"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from make_map_images import make_map_images
from project_paths import ROOT as PROJECT_ROOT, load_environment

ROOT = Path(__file__).parent


def prepare(workspace):
    environment = load_environment()
    ak = Path(environment["assembly_kit"]).resolve()
    game = Path(environment["game_root"]).resolve()
    workspace = workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("隔离工作目录必须为空，避免覆盖已有工作")
    if workspace.is_relative_to(game) or workspace.is_relative_to(ak):
        raise ValueError("隔离工作目录不能位于游戏安装目录中")
    # 原生导出器需要AK运行库，复制到隔离目录，不让工具写入原安装。
    shutil.copytree(ak / "binaries", workspace / "binaries")
    database = workspace / "raw_data/db"
    # CAIME只读少量表，但AK原生导出器还会读取其他数据库依赖。
    shutil.copytree(ak / "raw_data/db", database)
    map_dir = workspace / "raw_data/EmpireDesignData/campaign_maps/fnvtw_prototype_map"
    subprocess.run([environment["powershell"], "-NoProfile", "-File", str(ROOT / "build_map.ps1"),
                    "-OutputDirectory", str(map_dir), "-CaimeDirectory", environment["caime_dir"],
                    "-DatabaseDirectory", str(database),
                    "-ScenarioPath", str(PROJECT_ROOT / "content/prototype/场景.json")],
                    check=True)
    manifest = json.loads((map_dir / "map_manifest.json").read_text(encoding="utf-8"))

    def append_records(table, records, template_key=None):
        tree = ET.parse(database / (table + ".xml"))
        root = tree.getroot()
        template = root.find(table)
        if template_key:
            column, key = template_key
            template = next(row for row in root.findall(table) if row.findtext(column) == key)
        for values in records:
            row = deepcopy(template)
            # 新行使用自己的字段值；原版记录原封保留，源文件不写回。
            row.attrib.clear()
            for key, value in values.items():
                node = row.find(key)
                if node is None:
                    node = ET.SubElement(row, key)
                node.text = str(value)
            root.append(row)
        tree.write(database / (table + ".xml"), encoding="utf-8", xml_declaration=True)

    regions = manifest["regions"]
    append_records("regions", [{**r, "onscreen": r["key"], "battle_name": r["key"],
                                "is_sea": 0} for r in regions])
    append_records("campaign_map_regions", [{"campaign_map": manifest["map"],
                    "region": r["key"]} for r in regions])
    append_records("region_to_province_junctions", [{"region": r["key"],
                    "province": r["key"] + "_province", "is_capital": 1} for r in regions])
    append_records("campaign_maps", [{"mapname": manifest["map"], "minx": 0, "miny": 0,
                    "maxx": 64, "maxy": 64}])
    append_records("campaign_map_playable_areas", [{"mapname": manifest["map"],
                    "index": 2140000001, "campaign_key": "fnvtw_prototype",
                    "minx": 0, "maxx": 64, "miny": 0, "maxy": 64,
                    "is_mpc_available": 0}], ("campaign_key", "wh3_main_combi"))
    append_records("provinces", [{"key": r["key"] + "_province"} for r in regions])
    append_records("campaigns", [{"campaign_name": "fnvtw_prototype",
                    "map_name": manifest["map"], "display_location": manifest["map"],
                    "script_path": "script/campaign/fnvtw_prototype", "available_for_mp": 0}],
                    ("campaign_name", "wh3_main_combi"))
    return map_dir / "map.hex"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    map_file = prepare(args.workspace)
    environment = load_environment()
    result = subprocess.run([environment["powershell"], "-NoProfile", "-File", str(ROOT / "process_map.ps1"),
                "-Workspace", str(args.workspace.resolve()), "-MapFile", str(map_file),
                "-CaimeDirectory", environment["caime_dir"]],
                capture_output=True, text=True, encoding="utf-8")
    # 保存原生工具输出，避免仅凭包装命令的退出码认定处理成功。
    (args.workspace / "process.stdout.log").write_text(result.stdout, encoding="utf-8")
    (args.workspace / "process.stderr.log").write_text(result.stderr, encoding="utf-8")
    print(result.stdout)
    if result.returncode:
        raise SystemExit(result.stderr or result.returncode)
    make_map_images(args.workspace)
