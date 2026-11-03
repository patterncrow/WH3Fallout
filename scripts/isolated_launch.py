"""为原生编译准备独立启动参数；不改Steam、TWMM或玩家Mod清单。"""

import hashlib
import json
from pathlib import Path
import re
import struct


def prepare_launch(root, native_run, game_root, user_script):
    root, game_root = Path(root).resolve(), Path(game_root).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", native_run):
        raise ValueError("原生执行编号不合法")
    run = root / "work" / native_run
    if not run.resolve().is_relative_to(root):
        raise ValueError("执行目录越出本项目")
    plan = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    target = Path(plan["deployment_target"]).resolve()
    if target.parent != game_root / "data":
        raise ValueError("候选包不在所选游戏的data目录")
    if hashlib.sha256(target.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("已部署候选包摘要不符")
    text = Path(user_script).read_text(encoding="utf-8-sig")
    mods = [quoted or bare for quoted, bare in
            re.findall(r'\bmod\s+(?:"([^"]+)"|([^;\s]+))\s*;', text)]
    if mods != [target.name] or re.search(r"\badd_working_directory\b", text):
        raise ValueError("启动脚本不是本次单包配置")
    movie_packs = []
    for pack in (game_root / "data").glob("*.pack"):
        with pack.open("rb") as stream:
            header = stream.read(8)
        if len(header) == 8 and header[:3] == b"PFH" and struct.unpack_from("<I", header, 4)[0] & 15 == 4:
            movie_packs.append(pack.name)
    if movie_packs:
        raise ValueError("发现可能自动加载的Movie包，先核实来源：" + ", ".join(movie_packs))
    executable = game_root / "Warhammer3.exe"
    if not executable.is_file():
        raise FileNotFoundError(str(executable))
    modlist = run / "isolated_mods.txt"
    # 实际TWMM进程命令行证明WH3支持此清单参数；空清单只配合RPFM生成脚本使用。
    with modlist.open("xb"):
        pass
    result = {"command": [str(executable), str(modlist), ";"], "cwd": str(game_root),
              "environment_overrides": {"SteamAppId": "1142710", "SteamGameId": "1142710"},
              "expected_mod": target.name, "movie_packs": movie_packs,
              "note": "仅测试启动；玩家正常启动方式不变。实际加载组合仍须核对本次modified.log。"}
    with (run / "isolated-launch-plan.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result
