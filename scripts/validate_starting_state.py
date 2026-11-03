"""用RPFM校验实际开局包，保存终态报告；不生成或启动游戏。"""

import argparse
import json
from pathlib import Path

from rpfm_rpc import RpfmClient


def validate(client, source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("不覆盖已有校验报告：" + str(output))
    client.tool("set_game", game="warhammer_3", rebuild_dependencies=False)
    pack = client.tool("open_pack", paths=[str(source)])
    try:
        result = client.tool("validate_startpos", pack=pack["key"], campaign="fnvtw_prototype")
        if "job" in result:
            result = client.wait_job(result["job"])
        # 先保存实际报告；存在错误时退出失败，统一入口不得继续当作成功输入。
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if any(issue["level"] == "error" for issue in result["issues"]):
            raise ValueError("开局校验失败，详见：" + str(output))
        return result
    finally:
        client.tool("close_pack", pack=pack["key"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with RpfmClient() as client:
        result = validate(client, args.input, args.output)
    print("开局校验完成，问题数：" + str(len(result["issues"])))
