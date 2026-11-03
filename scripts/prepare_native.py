"""准备原生编译交接：校验输入、复制候选和备份明确目标，不改游戏。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(root, input_build, run_id, game_root, user_script):
    root, game_root, user_script = Path(root).resolve(), Path(game_root).resolve(), Path(user_script).resolve()
    for identifier in (input_build, run_id):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", identifier):
            raise ValueError("构建标识只能使用字母、数字、下划线和连字符，最长80字符")
    folder = root / "work" / input_build
    destination = root / "work" / run_id
    if not folder.resolve().is_relative_to(root) or not destination.resolve().is_relative_to(root):
        raise ValueError("输入与交接目录必须位于本项目工作目录")
    source = folder / "fnvtw_prototype_starting_state.pack"
    source_manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest["status"] != "succeeded":
        raise ValueError("输入构建尚未成功")
    expected = next(item for item in source_manifest["outputs"] if item["path"] == source.name)
    if digest(source) != expected["sha256"]:
        raise ValueError("输入包与构建清单摘要不一致")
    validation = json.loads((folder / "startpos-validation.json").read_text(encoding="utf-8"))
    if any(issue["level"] == "error" for issue in validation["issues"]):
        raise ValueError("开局数据存在错误，不进入原生编译交接")
    pack_name = "fnvtw_native_" + run_id + ".pack"
    deployment_target = game_root / "data" / pack_name
    if deployment_target.exists():
        raise FileExistsError("不会覆盖游戏中的既有同名包：" + str(deployment_target))
    destinations = [deployment_target, user_script, user_script.with_name(user_script.name + ".bak")]
    for relative in ("campaigns/fnvtw_prototype/startpos.esf",
                     "campaign_maps/fnvtw_prototype_map/hlp_data.esf",
                     "campaign_maps/fnvtw_prototype_map/spd_data.esf"):
        target = game_root / "data" / relative
        destinations.extend((target, target.with_name(target.name + ".bak")))
    # 这些是RPFM源码及当前接口明确会触及的文件，不扫描或备份整个游戏。
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "before").mkdir()
    report = {"format_version": 1, "build_id": run_id, "stage": "prepare-native",
              "status": "preparing", "prepared_at": datetime.now().astimezone().isoformat(),
              "input_build": input_build, "source_pack": source.relative_to(root).as_posix(),
              "source_sha256": expected["sha256"], "validation": validation,
              "deployment_target": str(deployment_target), "before": [],
              "side_effects_applied": False,
              "limitations": ["只完成交接准备，尚未原生编译、部署或恢复。",
                              "应用前重新核对全部目标与before摘要；出现用户新改动时停止。",
                              "恢复按本批开始前状态进行，不撤销更早批次遗留配置。"]}
    manifest_path = destination / "manifest.json"

    def save():
        manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        for index, target in enumerate(destinations):
            item = {"target": str(target), "exists": target.exists()}
            if item["exists"]:
                if not target.is_file():
                    raise ValueError("预期文件位置存在其他类型对象：" + str(target))
                backup = destination / "before" / f"{index:02d}.bin"
                shutil.copy2(target, backup)
                item.update(backup=backup.relative_to(root).as_posix(), sha256=digest(backup))
            report["before"].append(item)
            save()
        staged_pack = destination / pack_name
        shutil.copy2(source, staged_pack)
        if digest(staged_pack) != expected["sha256"]:
            raise ValueError("候选副本摘要不一致")
        report["staged_pack"] = staged_pack.relative_to(root).as_posix()
        report["status"] = "awaiting_operator"
        report["steps"] = [
            "确认游戏已退出；重新核对所有before摘要，检查RPFM没有其他待完成的startpos生成。",
            "仅将staged_pack复制到deployment_target，并通过RPFM打开该新副本。",
            "调用validate_startpos；若返回job，必须等待终态，不能把任务号当作校验结果。",
            "在同一RPFM会话调用start_startpos，campaign=fnvtw_prototype，process_hlp_spd_data=true；此调用会启动游戏。",
            "用户观察生成；游戏可能按生成脚本自动退出，若停在主菜单则正常退出。不要进入其他战役。",
            "确认游戏退出后，调用finish_startpos(cancel=false)一次；此调用消费pending状态，失败不能盲目重试finish。",
            "核对导入startpos、hlp_data和spd_data三文件，另存到本交接目录的新compiled包，不覆盖输入包。",
            "检查RPFM已恢复的文件，对剩余改动逐文件核对本次写入摘要，再按before恢复；有新改动则停止。",
            "人工游玩另建部署记录，切换该compiled包；原生编译通过不能代替进入、存读档及原版入口验收。"
        ]
        save()
    except Exception as error:
        report.update(status="failed", error=str(error))
        save()
        raise
    return report
