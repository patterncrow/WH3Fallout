"""现有样板的统一制作入口；只写独立工作目录，不启动游戏或部署。"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parent


def now():
    return datetime.now().astimezone().isoformat()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fingerprint(path, relative_to=None):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": path.relative_to(relative_to).as_posix() if relative_to else str(path.resolve()),
            "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def source_snapshot(root):
    sources = set()
    for folder in ("scripts", "tests", "content", "assets", "文档"):
        if (root / folder).exists():
            sources.update(p for p in (root / folder).rglob("*")
                           if p.is_file() and "__pycache__" not in p.parts)
    sources.update(p for p in root.iterdir() if p.is_file() and
                   (p.suffix in (".md", ".py") or p.name in (".gitignore", ".gitattributes", "requirements.txt")))
    example = root / "工程/本机配置.example.json"
    if example.is_file():
        sources.add(example)
    return [fingerprint(p, root) for p in sorted(sources)]


def create_build_dir(root, build_id):
    root = Path(root).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", build_id):
        raise ValueError("build_id只能包含字母、数字、下划线与连字符，最长80字符")
    destination = root / "work" / build_id
    if not destination.resolve().is_relative_to(root):
        raise ValueError("工作目录必须在本项目中")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def record_attempt(root, manifest, build_dir):
    engineering = root / "工程"
    engineering.mkdir(exist_ok=True)
    summary = {"time": now(), "kind": "build", "build_id": manifest["build_id"],
               "stage": manifest["stage"], "status": manifest["status"],
               "evidence": (build_dir / "manifest.json").relative_to(root).as_posix()}
    with (engineering / "工程日志.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, ensure_ascii=False) + "\n")
    state_path = engineering / "当前状态.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        # 生成成功也不自动升级为可游玩候选，更不改写人工验收结果。
        state["latest_build_attempt"] = summary
        write_json(state_path, state)


def run_build(root, stage, build_id):
    root = Path(root).resolve()
    if stage not in ("registration", "map", "starting-state"):
        raise ValueError("未知制作阶段")
    build_dir = create_build_dir(root, build_id)
    manifest = {"format_version": 1, "build_id": build_id, "stage": stage,
                "started_at": now(), "status": "running",
                "source_snapshot": [], "inputs": [], "outputs": [], "steps": [],
                "environment": {"python": platform.python_version(), "declared_versions": {}},
                "checks": {"automated_tests": "not_run", "game_acceptance": "not_run"},
                "limitations": ["阶段输出不是已完成原生编译的可游玩包。",
                                "原生开局生成、导入、部署与恢复尚未收拢到本入口。",
                                "工具版本为本机配置声明，非运行时自动核验结果。"]}
    manifest_path = build_dir / "manifest.json"
    write_json(manifest_path, manifest)
    record_attempt(root, manifest, build_dir)
    returncode = 1
    try:
        config_path = root / "工程/本机配置.json"
        if not config_path.is_file():
            raise FileNotFoundError("请先复制 工程/本机配置.example.json 为 工程/本机配置.json 并填写路径")
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        manifest["environment"]["declared_versions"] = config.get("declared_versions", {})
        manifest["source_snapshot"] = source_snapshot(root)
        database_pack = Path(config["game_root"]) / "data/db.pack"
        manifest["inputs"].append(fingerprint(database_pack))
        if stage != "registration":
            # 地图原生导出读取整套AK数据库；输入指纹包括实际复制的XML。
            database = Path(config["assembly_kit"]) / "raw_data/db"
            manifest["inputs"].extend(fingerprint(p) for p in sorted(database.glob("*.xml")))
        scripts = root / "scripts"
        kit = build_dir / "kit"
        map_pack = build_dir / "fnvtw_prototype_map.pack"
        registration_pack = build_dir / "fnvtw_prototype_registration.pack"
        starting_pack = build_dir / "fnvtw_prototype_starting_state.pack"
        if stage == "registration":
            commands = [("registration", [sys.executable, str(scripts / "build_pack.py"),
                          "--output", str(registration_pack)], registration_pack)]
        else:
            commands = [
                ("map-process", [sys.executable, str(scripts / "process_map.py"),
                                 "--workspace", str(kit)],
                 kit / "working_data/campaign_maps/fnvtw_prototype_map/map_data.esf"),
                ("map-pack", [sys.executable, str(scripts / "build_pack.py"),
                              "--map-workspace", str(kit), "--output", str(map_pack)], map_pack)]
            if stage == "starting-state":
                commands.append(("starting-state", [sys.executable, str(scripts / "build_starting_state.py"),
                                 "--input", str(map_pack), "--output", str(starting_pack)], starting_pack))
                validation_report = build_dir / "startpos-validation.json"
                commands.append(("starting-state-validation", [sys.executable,
                                 str(scripts / "validate_starting_state.py"), "--input", str(starting_pack),
                                 "--output", str(validation_report)], validation_report))
        for name, command, expected_output in commands:
            step = {"name": name, "command": command, "started_at": now(), "status": "running"}
            manifest["steps"].append(step)
            write_json(manifest_path, manifest)
            with (build_dir / (name + ".stdout.log")).open("wb") as stdout, \
                    (build_dir / (name + ".stderr.log")).open("wb") as stderr:
                child_environment = os.environ.copy()
                child_environment.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
                result = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr,
                                        env=child_environment)
            step.update(returncode=result.returncode, finished_at=now())
            if result.returncode:
                step["status"] = "failed"
                returncode = result.returncode
                break
            if not expected_output.is_file():
                raise FileNotFoundError("步骤未生成声明的输出：" + str(expected_output))
            step["status"] = "succeeded"
            if name == "starting-state-validation":
                validation = json.loads(expected_output.read_text(encoding="utf-8"))
                manifest["checks"]["startpos_validation"] = {
                    "status": "passed", "issues": len(validation["issues"]),
                    "evidence": expected_output.name}
        else:
            returncode = 0
        manifest["status"] = "succeeded" if returncode == 0 else "failed"
    except KeyboardInterrupt:
        manifest.update(status="interrupted", error="用户中断；需核对外部工具是否仍在运行")
        returncode = 130
    except Exception as error:
        manifest.update(status="failed", error=str(error))
    finally:
        for step in manifest["steps"]:
            if step["status"] == "running":
                step.update(status=manifest["status"], finished_at=now())
        # 不把整套AK复制品列作产品输出；保留制作的地图文件及阶段包。
        output_paths = list(build_dir.glob("*.pack"))
        for folder in (build_dir / "kit/working_data/campaign_maps/fnvtw_prototype_map",
                       build_dir / "kit/raw_data/EmpireDesignData/campaign_maps/fnvtw_prototype_map"):
            if folder.is_dir():
                output_paths.extend(p for p in folder.rglob("*") if p.is_file())
        manifest["outputs"] = [fingerprint(p, build_dir) for p in sorted(output_paths)]
        manifest["finished_at"] = now()
        write_json(manifest_path, manifest)
        record_attempt(root, manifest, build_dir)
    print(f"{manifest['status']}: {manifest_path}")
    return returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("registration", "map", "starting-state", "prepare-native"))
    parser.add_argument("--build-id", default=datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    parser.add_argument("--input-build", help="prepare-native使用的已校验开局输入构建标识")
    args = parser.parse_args()
    if args.stage == "prepare-native":
        if not args.input_build:
            parser.error("prepare-native需要--input-build")
        sys.path.insert(0, str(ROOT / "scripts"))
        from prepare_native import prepare
        from project_paths import load_environment
        environment = load_environment()
        user_script = Path(os.environ["APPDATA"]) / "The Creative Assembly/Warhammer3/scripts/user.script.txt"
        report = prepare(ROOT, args.input_build, args.build_id, environment["game_root"], user_script)
        build_dir = ROOT / "work" / args.build_id
        record_attempt(ROOT, report, build_dir)
        print(f"awaiting_operator: {build_dir / 'manifest.json'}")
        return 0
    return run_build(ROOT, args.stage, args.build_id)


if __name__ == "__main__":
    raise SystemExit(main())
