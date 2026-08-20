#!/usr/bin/env python3
"""Print compact JSON metadata for PNG/APNG and GIF sticker files."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunks(path: Path):
    with path.open("rb") as handle:
        if handle.read(8) != PNG_SIGNATURE:
            raise ValueError("not PNG")
        while True:
            raw_length = handle.read(4)
            if not raw_length:
                break
            length = struct.unpack(">I", raw_length)[0]
            chunk_type = handle.read(4)
            data = handle.read(length)
            handle.read(4)
            yield chunk_type, data
            if chunk_type == b"IEND":
                break


def inspect_png(path: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path),
        "format": "PNG",
        "frames": 1,
        "plays": None,
        "delays_ms": [],
        "color_type": None,
        "has_trns": False,
    }
    for chunk_type, data in png_chunks(path):
        if chunk_type == b"IHDR":
            width, height, _, color_type, _, _, _ = struct.unpack(">IIBBBBB", data)
            result.update(width=width, height=height, color_type=color_type)
        elif chunk_type == b"acTL":
            result["frames"], result["plays"] = struct.unpack(">II", data)
            result["format"] = "APNG"
        elif chunk_type == b"fcTL":
            numerator, denominator = struct.unpack(">HH", data[20:24])
            result["delays_ms"].append(round(numerator / (denominator or 100) * 1000))
        elif chunk_type == b"tRNS":
            result["has_trns"] = True
    result["alpha"] = result["color_type"] in (4, 6) or result["has_trns"]
    result["cycle_ms"] = sum(result["delays_ms"])
    plays = result["plays"]
    result["total_ms"] = None if plays in (None, 0) else result["cycle_ms"] * plays
    return result


def inspect_gif(path: Path) -> dict[str, object]:
    durations: list[int] = []
    alpha_frames = 0
    with Image.open(path) as image:
        frame_count = getattr(image, "n_frames", 1)
        loop = image.info.get("loop")
        width, height = image.size
        for index in range(frame_count):
            image.seek(index)
            durations.append(int(image.info.get("duration", 0)))
            if image.convert("RGBA").getchannel("A").getextrema()[0] < 255:
                alpha_frames += 1
    return {
        "path": str(path),
        "format": "GIF",
        "width": width,
        "height": height,
        "frames": frame_count,
        "loop": loop,
        "delays_ms": durations,
        "cycle_ms": sum(durations),
        "alpha_frames": alpha_frames,
        "alpha": alpha_frames > 0,
    }


def inspect(path: Path) -> dict[str, object]:
    signature = path.read_bytes()[:8]
    if signature == PNG_SIGNATURE:
        return inspect_png(path)
    if signature[:6] in (b"GIF87a", b"GIF89a"):
        return inspect_gif(path)
    raise ValueError(f"unsupported file: {path}")


def main() -> None:
    target = Path(sys.argv[1])
    if target.is_dir():
        paths = sorted(path for path in target.iterdir() if path.suffix.lower() in {".png", ".gif"})
    else:
        paths = [target]
    for path in paths:
        try:
            print(json.dumps(inspect(path), ensure_ascii=False, sort_keys=True))
        except Exception as error:
            print(json.dumps({"path": str(path), "error": str(error)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
