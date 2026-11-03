"""固定五个文件的游玩部署、只读状态与恢复；不启动或结束游戏。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


LOOSE_FILES = (
    "campaigns/fnvtw_prototype/startpos.esf",
    "campaign_maps/fnvtw_prototype_map/hlp_data.esf",
    "campaign_maps/fnvtw_prototype_map/spd_data.esf",
)


def _now():
    return datetime.now().astimezone().isoformat()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _run(root, identifier):
    root = Path(root).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", identifier):
        raise ValueError("执行编号不合法")
    run = root / "work" / identifier
    if not run.resolve().is_relative_to(root):
        raise ValueError("执行目录范围越界")
    return run


def running_games():
    command = "$p=@(Get-Process Warhammer3 -ErrorAction SilentlyContinue | Select-Object Id); ConvertTo-Json -InputObject $p -Compress"
    output = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", command], text=True)
    return bool(json.loads(output))


def _require_stopped(game_running):
    if (game_running or running_games)():
        raise RuntimeError("游戏仍在运行，不能部署或恢复")


def _scope(plan, game_root, user_script):
    data = (Path(game_root).resolve() / "data").resolve()
    target = Path(plan["deployment_target"]).resolve()
    if target.parent != data or not target.name.startswith("fnvtw_") or target.suffix != ".pack":
        raise ValueError("测试包恢复范围不合法")
    loose = [(data / relative).resolve() for relative in LOOSE_FILES]
    if any(not path.is_relative_to(data) for path in loose):
        raise ValueError("松散文件恢复范围越界")
    allowed = {target, Path(user_script).resolve(), *loose}
    records = plan["before"]
    if len(records) != 5 or {Path(item["target"]).resolve() for item in records} != allowed:
        raise ValueError("清单恢复范围不是约定的五个文件")


def deploy(root, native_build, run_id, game_root, user_script, *, game_running=None):
    _require_stopped(game_running)
    root, game_root, user_script = Path(root).resolve(), Path(game_root).resolve(), Path(user_script).resolve()
    native, run = _run(root, native_build), _run(root, run_id)
    proof = json.loads((native / "native-import.json").read_text(encoding="utf-8"))
    if proof["status"] != "clean_native_import_passed" or not proof["clean_mod_environment"]:
        raise ValueError("只能部署已通过单包原生生成的候选")
    source = (root / proof["output"]).resolve()
    if not source.is_relative_to(native.resolve()):
        raise ValueError("候选源文件范围越界")
    if _sha(source) != proof["sha256"]:
        raise ValueError("候选包摘要与原生生成记录不符")
    if run.exists():
        raise FileExistsError("不覆盖已有执行目录：" + str(run))
    target = game_root / "data" / ("fnvtw_playtest_" + run_id + ".pack")
    if target.exists():
        raise FileExistsError("不覆盖既有测试包：" + str(target))
    script = f"mod {target.name};\n".encode("utf-8")
    paths = [target, user_script, *(game_root / "data" / relative for relative in LOOSE_FILES)]
    records = []
    for index, path in enumerate(paths):
        if path.exists() and not path.is_file():
            raise ValueError("预期文件位置存在其他类型对象：" + str(path))
        item = {"target": str(path), "exists": path.exists(),
                "action": "create_pack" if index == 0 else ("replace_script" if index == 1 else "quarantine_own_loose_file"),
                "applied_sha256": proof["sha256"] if index == 0 else (hashlib.sha256(script).hexdigest() if index == 1 else None)}
        if path.is_file():
            item.update(sha256=_sha(path), bytes=path.stat().st_size,
                        backup=(run / "before" / f"{index:02d}-{path.name}").relative_to(root).as_posix())
        records.append(item)
    plan = {"format_version": 1, "build_id": run_id, "stage": "manual-playtest", "status": "prepared",
            "prepared_at": _now(), "source_pack": source.relative_to(root).as_posix(),
            "source_sha256": proof["sha256"], "deployment_target": str(target),
            "before": records, "startup_script": script.decode("utf-8"), "side_effects_applied": False}
    _scope(plan, game_root, user_script)
    run.mkdir(parents=True, exist_ok=False)
    (run / "before").mkdir()
    _write(run / "manifest.json", plan)
    try:
        for item in records:
            path = Path(item["target"])
            if path.exists() != item["exists"] or (item["exists"] and _sha(path) != item["sha256"]):
                raise ValueError("应用前发现原状冲突：" + str(path))
        if records[1]["exists"]:
            shutil.copy2(user_script, root / records[1]["backup"])
        for item in records[2:]:
            path = Path(item["target"])
            if item["exists"]:
                backup = root / item["backup"]
                if not path.resolve().is_relative_to((game_root / "data").resolve()) or not backup.resolve().is_relative_to(run.resolve()):
                    raise ValueError("文件迁移范围越界")
                path.rename(backup)
                plan["side_effects_applied"] = True
                _write(run / "manifest.json", plan)
        with target.open("xb") as destination, source.open("rb") as original:
            shutil.copyfileobj(original, destination)
        plan["side_effects_applied"] = True
        _write(run / "manifest.json", plan)
        user_script.write_bytes(script)
        if _sha(target) != proof["sha256"]:
            raise ValueError("部署副本摘要不一致")
        plan["status"] = "deployed_awaiting_launch"
    except Exception as error:
        plan.update(status="deployment_failed", error=str(error))
        raise
    finally:
        _write(run / "manifest.json", plan)
    return plan


def status(root, run_id, game_root, user_script):
    run = _run(root, run_id)
    plan = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    _scope(plan, game_root, user_script)
    checks = []
    for item in plan["before"]:
        path = Path(item["target"])
        exists = path.exists()
        current = _sha(path) if path.is_file() else None
        is_file_or_missing = path.is_file() or not exists
        checks.append({"target": str(path), "exists": exists, "current_sha256": current,
                       "matches_before": is_file_or_missing and exists == item["exists"] and
                       (not item["exists"] or current == item["sha256"]),
                       "matches_applied": is_file_or_missing and
                       ((not exists and item.get("applied_sha256") is None) or
                        (exists and current == item.get("applied_sha256")))})
    original = all(item["matches_before"] for item in checks)
    applied = all(item["matches_applied"] for item in checks)
    return {"build_id": run_id, "stage": "manual-playtest", "checked_at": _now(),
            "status": "restored" if original else ("deployed" if applied else "partial_or_conflict"),
            "matches_before": original, "matches_deployed": applied, "checks": checks}


def restore(root, run_id, game_root, user_script, *, game_running=None):
    _require_stopped(game_running)
    root = Path(root).resolve()
    run = _run(root, run_id)
    plan = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    inspected = status(root, run_id, game_root, user_script)
    report_path = run / "restoration.json"
    if inspected["matches_before"] and report_path.is_file():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        if previous["status"] == "restored":
            return previous
    operations, conflicts = [], []
    for item, check in zip(plan["before"], inspected["checks"]):
        if check["matches_before"]:
            continue
        if not check["matches_applied"]:
            conflicts.append(item["target"])
            continue
        operation = {"target": item["target"], "current_sha256": check["current_sha256"],
                     "action": "restore_original" if item["exists"] else "remove_owned_test_pack"}
        if item["exists"]:
            backup = (root / item["backup"]).resolve()
            if not backup.is_relative_to((run / "before").resolve()):
                raise ValueError("备份范围越界")
            if not backup.is_file():
                raise FileNotFoundError("原状备份缺失：" + str(backup))
            if _sha(backup) != item["sha256"]:
                raise ValueError("原状备份摘要不符")
            operation["backup"] = item["backup"]
        operations.append(operation)
    report = {"build_id": run_id, "stage": "restore-playtest", "created_at": _now(),
              "status": "conflict" if conflicts else "planned", "operations": operations, "conflicts": conflicts}
    _write(report_path, report)
    if conflicts:
        raise ValueError("发现用户新改动冲突，未执行任何恢复：" + ", ".join(conflicts))
    try:
        for operation in operations:
            path = Path(operation["target"])
            current = _sha(path) if path.is_file() else None
            if current != operation["current_sha256"]:
                raise ValueError("恢复前目标再次出现冲突：" + str(path))
            if operation["action"] == "restore_original":
                shutil.copy2(root / operation["backup"], path)
            else:
                path.unlink()  # 精确范围与本批摘要均已核对，不递归清理。
        final = status(root, run_id, game_root, user_script)
        if not final["matches_before"]:
            raise ValueError("恢复后仍与原状不符")
        report.update(status="restored", finished_at=_now(), checks=final["checks"])
        plan.update(status="restored", side_effects_applied=False, restoration="restoration.json")
        _write(run / "manifest.json", plan)
    except Exception as error:
        report.update(status="restoration_failed", error=str(error))
        raise
    finally:
        _write(report_path, report)
    return report
