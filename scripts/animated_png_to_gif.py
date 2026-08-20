#!/usr/bin/env python3
"""Convert animated PNG stickers to transparent, infinite-loop GIF89a files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


TRANSPARENT_INDEX = 255
DISPOSAL_METHOD = 2
COMMENT = b"WeCom transparent infinite-loop sticker"


@dataclass(frozen=True)
class GifControl:
    delay_ms: int
    disposal: int
    transparent: bool
    transparent_index: int


def sticker_id(path: Path) -> str:
    stem = path.stem
    return stem[:-3] if stem.endswith("@2x") else stem


def gif_durations(milliseconds: list[float]) -> list[int]:
    result: list[int] = []
    previous_centiseconds = 0
    cumulative_milliseconds = 0.0
    for duration in milliseconds:
        cumulative_milliseconds += duration
        cumulative_centiseconds = round(cumulative_milliseconds / 10)
        centiseconds = max(2, cumulative_centiseconds - previous_centiseconds)
        result.append(centiseconds * 10)
        previous_centiseconds += centiseconds
    return result


def fit_on_canvas(frame: Image.Image, canvas_size: int) -> Image.Image:
    rgba = frame.convert("RGBA")
    scale = min(canvas_size / rgba.width, canvas_size / rgba.height)
    size = (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale)))
    resized = rgba.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    offset = ((canvas_size - resized.width) // 2, (canvas_size - resized.height) // 2)
    canvas.alpha_composite(resized, offset)
    return canvas


def quantize(frame: Image.Image, alpha_threshold: int) -> Image.Image:
    rgba = frame.convert("RGBA")
    paletted = rgba.convert("RGB").quantize(
        colors=255,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    palette = (paletted.getpalette() or [])[: 255 * 3]
    palette.extend([0] * (255 * 3 - len(palette)))
    palette.extend([0, 0, 0])
    paletted.putpalette(palette)
    mask = rgba.getchannel("A").point(lambda alpha: 255 if alpha <= alpha_threshold else 0)
    paletted.paste(TRANSPARENT_INDEX, mask=mask)
    paletted.info["transparency"] = TRANSPARENT_INDEX
    return paletted


def load_source(path: Path, canvas_size: int, alpha_threshold: int) -> tuple[list[Image.Image], list[int]]:
    frames: list[Image.Image] = []
    durations: list[float] = []
    with Image.open(path) as source:
        if not getattr(source, "is_animated", False) or source.n_frames < 2:
            raise ValueError(f"source is not animated: {path}")
        for index in range(source.n_frames):
            source.seek(index)
            frames.append(quantize(fit_on_canvas(source.convert("RGBA"), canvas_size), alpha_threshold))
            durations.append(float(source.info.get("duration", 100)))
    return frames, gif_durations(durations)


def skip_subblocks(data: bytes, offset: int) -> int:
    while True:
        if offset >= len(data):
            raise RuntimeError("truncated GIF sub-block")
        size = data[offset]
        offset += 1
        if size == 0:
            return offset
        offset += size


def parse_gif(path: Path) -> tuple[tuple[int, int], int | None, list[GifControl]]:
    data = path.read_bytes()
    if data[:6] != b"GIF89a":
        raise RuntimeError("output is not GIF89a")
    width, height = struct.unpack_from("<HH", data, 6)
    packed = data[10]
    offset = 13
    if packed & 0x80:
        offset += (2 ** ((packed & 7) + 1)) * 3

    loop: int | None = None
    pending: GifControl | None = None
    controls: list[GifControl] = []
    while offset < len(data):
        marker = data[offset]
        offset += 1
        if marker == 0x3B:
            break
        if marker == 0x21:
            label = data[offset]
            offset += 1
            if label == 0xF9:
                if data[offset] != 4:
                    raise RuntimeError("unexpected GIF control size")
                control_packed = data[offset + 1]
                delay = struct.unpack_from("<H", data, offset + 2)[0] * 10
                pending = GifControl(
                    delay,
                    (control_packed >> 2) & 7,
                    bool(control_packed & 1),
                    data[offset + 4],
                )
                offset += 6
                continue
            if label == 0xFF:
                size = data[offset]
                offset += 1
                identifier = data[offset : offset + size]
                offset += size
                if identifier == b"NETSCAPE2.0" and data[offset] == 3:
                    loop = struct.unpack_from("<H", data, offset + 2)[0]
                offset = skip_subblocks(data, offset)
                continue
            offset = skip_subblocks(data, offset)
            continue
        if marker != 0x2C or pending is None:
            raise RuntimeError(f"unexpected GIF structure at {offset - 1}")
        image_packed = data[offset + 8]
        offset += 9
        if image_packed & 0x80:
            offset += (2 ** ((image_packed & 7) + 1)) * 3
        offset += 1
        offset = skip_subblocks(data, offset)
        controls.append(pending)
        pending = None
    return (width, height), loop, controls


def convert_one(source: Path, output: Path, canvas_size: int, alpha_threshold: int) -> dict[str, object]:
    frames, durations = load_source(source, canvas_size, alpha_threshold)
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=DISPOSAL_METHOD,
        transparency=TRANSPARENT_INDEX,
        optimize=False,
        interlace=False,
        comment=COMMENT,
    )

    size, loop, controls = parse_gif(output)
    if size != (canvas_size, canvas_size):
        raise RuntimeError(f"unexpected canvas: {size}")
    if loop != 0:
        raise RuntimeError(f"GIF is not infinite-loop: {loop}")
    if len(controls) != len(frames):
        raise RuntimeError(f"frame count changed: {len(controls)} != {len(frames)}")
    if [control.delay_ms for control in controls] != durations:
        raise RuntimeError("frame durations changed")
    if any(control.disposal != DISPOSAL_METHOD for control in controls):
        raise RuntimeError("unexpected disposal method")
    if any(not control.transparent for control in controls):
        raise RuntimeError("a frame has no transparency flag")
    if any(control.transparent_index != TRANSPARENT_INDEX for control in controls):
        raise RuntimeError("unexpected transparent palette index")

    return {
        "source_frames": len(frames),
        "gif_frames": len(controls),
        "durations_ms": json.dumps(durations, separators=(",", ":")),
        "cycle_ms": sum(durations),
        "width": canvas_size,
        "height": canvas_size,
        "loop": loop,
        "disposal": DISPOSAL_METHOD,
        "transparent_index": TRANSPARENT_INDEX,
        "transparent": True,
        "byte_size": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--canvas", type=int, default=240)
    parser.add_argument("--alpha-threshold", type=int, default=127)
    args = parser.parse_args()
    if not 0 <= args.alpha_threshold <= 255:
        raise ValueError("--alpha-threshold must be between 0 and 255")

    if args.source.is_file():
        destination = args.output / f"{sticker_id(args.source)}.gif" if args.output.is_dir() else args.output
        metadata = convert_one(args.source, destination, args.canvas, args.alpha_threshold)
        print(f"verified {destination} sha256={metadata['sha256']}")
        return

    sources = sorted(
        path
        for path in args.source.glob("*.png")
        if not path.stem.endswith("_thumbnail")
    )
    if not sources:
        raise ValueError(f"no animated PNG files found in {args.source}")
    identifiers = [sticker_id(path) for path in sources]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate sticker IDs after removing @2x")

    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for source in sources:
        destination = args.output / f"{sticker_id(source)}.gif"
        metadata = convert_one(source, destination, args.canvas, args.alpha_threshold)
        rows.append(
            {
                "id": sticker_id(source),
                "source": source.name,
                "output": destination.name,
                **metadata,
            }
        )
        print(f"verified {source.name} -> {destination.name}")

    fields = list(rows[0].keys())
    with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"created={len(rows)} manifest={args.output / 'manifest.csv'}")


if __name__ == "__main__":
    main()
