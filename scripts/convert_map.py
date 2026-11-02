"""调用MIT许可的既有转换工具，保留AK输出，生成游戏格式副本。"""

import argparse
from pathlib import Path

from vendor.lire_esf import Esf, convertir_vers_abca, flux_rle, lire_chaines


def convert(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.exists():
        raise ValueError("转换必须写入新的副本，不覆盖源文件或既有产物")
    blob = source.read_bytes()
    original = Esf(blob)
    original.analyse()
    converted = convertir_vers_abca(blob)
    result = Esf(converted)
    result.analyse()
    # 不只检查魔数：转换前后的节点、完整字符串表和地区索引覆盖均须一致。
    if original.racine != result.racine or lire_chaines(original)[:2] != lire_chaines(result)[:2]:
        raise ValueError("转换改变了地图内容")
    width, height, runs = flux_rle(result)
    if not width or not height or sum(run[2] for run in runs) != width * height:
        raise ValueError("地区索引未覆盖整张地图")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(converted)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(convert(args.input, args.output))
