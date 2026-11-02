"""项目位置与本机工具配置；不在代码内保存机器盘符。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_scenario():
    return json.loads((ROOT / "content/prototype/场景.json").read_text(encoding="utf-8"))


def load_environment(root=ROOT):
    path = Path(root) / "工程/本机配置.json"
    if not path.is_file():
        raise FileNotFoundError("请复制 工程/本机配置.example.json 为 工程/本机配置.json 并填写本机路径")
    return json.loads(path.read_text(encoding="utf-8-sig"))
