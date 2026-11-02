"""将CAIME地区位图转为样板地图PNG与既有工具支持的WH3查找图。"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

from vendor.palette_tga import ecrit_tga_palette


def make_map_images(workspace):
    workspace = Path(workspace)
    folder = workspace / "working_data/campaign_maps/fnvtw_prototype_map"
    manifest = json.loads((workspace / "raw_data/EmpireDesignData/campaign_maps/"
                           "fnvtw_prototype_map/map_manifest.json").read_text(encoding="utf-8"))
    regions = manifest["regions"]
    with Image.open(folder / "fnvtw_prototype_lookup.bmp") as source:
        image = source.convert("RGB")
    rgb = np.asarray(image)
    keys = rgb[:, :, 0].astype(np.uint32) * 65536 + rgb[:, :, 1].astype(np.uint32) * 256 + rgb[:, :, 2]
    palette = [(r["r"], r["g"], r["b"], 255) for r in regions]
    colour_ids = {r * 65536 + g * 256 + b: index for index, (r, g, b, _) in enumerate(palette)}
    if any(int(colour) not in colour_ids for colour in np.unique(keys)):
        raise ValueError("CAIME查找位图包含未登记地区的颜色")
    indices = np.zeros(keys.shape, dtype=np.uint16)
    for colour, index in colour_ids.items():
        indices[keys == colour] = index
    # 原样复用已有16位索引TGA写入器；PNG直接显示真实的三地区轮廓作为占位。
    ecrit_tga_palette(folder / "fnvtw_prototype_lookup.tga", indices, palette)
    small = image.resize((max(1, image.width // 4), max(1, image.height // 4)), Image.Resampling.NEAREST)
    small_rgb = np.asarray(small)
    small_keys = small_rgb[:, :, 0].astype(np.uint32) * 65536 + small_rgb[:, :, 1].astype(np.uint32) * 256 + small_rgb[:, :, 2]
    small_indices = np.zeros(small_keys.shape, dtype=np.uint16)
    for colour, index in colour_ids.items():
        small_indices[small_keys == colour] = index
    ecrit_tga_palette(folder / "fnvtw_prototype_lookup_minimap.tga", small_indices, palette)
    image.convert("RGBA").save(folder / "fnvtw_prototype_map.png")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    make_map_images(parser.parse_args().workspace)
