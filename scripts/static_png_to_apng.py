#!/usr/bin/env python3
"""Wrap transparent palette PNGs as finite, LINE-style APNG files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import struct
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FRAMES = 6
PLAYS = 4
DISPOSALS = (1, 0, 2, 0, 2, 0)


def read_chunks(path: Path) -> list[tuple[bytes, bytes]]:
    raw = path.read_bytes()
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError(f"not a PNG: {path}")

    chunks: list[tuple[bytes, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError(f"truncated PNG: {path}")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        data = raw[data_start:data_end]
        expected_crc = struct.unpack(">I", raw[data_end : data_end + 4])[0]
        actual_crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"bad CRC in {chunk_type!r}: {path}")
        chunks.append((chunk_type, data))
        offset = data_end + 4
        if chunk_type == b"IEND":
            break
    return chunks


def encode_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def frame_control(
    sequence: int,
    width: int,
    height: int,
    delay_num: int,
    delay_den: int,
    dispose: int,
) -> bytes:
    return struct.pack(
        ">IIIIIHHBB",
        sequence,
        width,
        height,
        0,
        0,
        delay_num,
        delay_den,
        dispose,
        0,
    )


def inspect_apng(path: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "frames": 1,
        "plays": None,
        "color_type": None,
        "has_trns": False,
        "delays": [],
    }
    for chunk_type, data in read_chunks(path):
        if chunk_type == b"IHDR":
            result["color_type"] = data[9]
        elif chunk_type == b"acTL":
            result["frames"], result["plays"] = struct.unpack(">II", data)
        elif chunk_type == b"fcTL":
            delay_num, delay_den = struct.unpack(">HH", data[20:24])
            result["delays"].append(delay_num / (delay_den or 100))
        elif chunk_type == b"tRNS":
            result["has_trns"] = True
    delays = result["delays"]
    color_type = result["color_type"]
    result["cycle_seconds"] = round(sum(delays), 3)
    result["total_seconds"] = round(sum(delays) * int(result["plays"] or 0), 3)
    result["alpha"] = color_type in (4, 6) or bool(result["has_trns"])
    return result


def convert_one(source: Path, destination: Path) -> dict[str, object]:
    chunks = read_chunks(source)
    chunk_types = [chunk_type for chunk_type, _ in chunks]
    if any(item in chunk_types for item in (b"acTL", b"fcTL", b"fdAT")):
        raise ValueError(f"source is already APNG: {source}")
    if not chunks or chunk_types[0] != b"IHDR" or chunk_types[-1] != b"IEND":
        raise ValueError(f"unexpected PNG chunk order: {source}")

    ihdr = chunks[0][1]
    width, height = struct.unpack(">II", ihdr[:8])
    color_type = ihdr[9]
    if color_type != 3:
        raise ValueError(f"source must be palette PNG (color type 3): {source}")

    first_idat = chunk_types.index(b"IDAT")
    last_idat = len(chunk_types) - 1 - chunk_types[::-1].index(b"IDAT")
    if any(t != b"IDAT" for t in chunk_types[first_idat : last_idat + 1]):
        raise ValueError(f"non-contiguous IDAT chunks: {source}")

    before_idat = chunks[1:first_idat]
    after_idat = chunks[last_idat + 1 : -1]
    compressed_frame = b"".join(data for _, data in chunks[first_idat : last_idat + 1])
    trns = next((data for chunk_type, data in before_idat if chunk_type == b"tRNS"), b"")
    try:
        transparent_index = trns.index(0)
    except ValueError as error:
        raise ValueError(f"palette PNG has no fully transparent entry: {source}") from error

    output = bytearray(PNG_SIGNATURE)
    output += encode_chunk(b"IHDR", ihdr)
    output += encode_chunk(b"acTL", struct.pack(">II", FRAMES, PLAYS))
    for chunk_type, data in before_idat:
        if chunk_type != b"sRGB":
            output += encode_chunk(chunk_type, data)

    sequence = 0
    output += encode_chunk(
        b"fcTL", frame_control(sequence, width, height, 1, FRAMES, DISPOSALS[0])
    )
    sequence += 1
    output += encode_chunk(b"IDAT", compressed_frame)

    for frame_index in range(1, FRAMES - 1):
        output += encode_chunk(
            b"fcTL",
            frame_control(
                sequence, width, height, 1, FRAMES, DISPOSALS[frame_index]
            ),
        )
        sequence += 1
        output += encode_chunk(b"fdAT", struct.pack(">I", sequence) + compressed_frame)
        sequence += 1

    transparent_pixel = zlib.compress(b"\x00" + bytes([transparent_index]))
    output += encode_chunk(
        b"fcTL", frame_control(sequence, 1, 1, 1, FRAMES, DISPOSALS[-1])
    )
    sequence += 1
    output += encode_chunk(b"fdAT", struct.pack(">I", sequence) + transparent_pixel)

    for chunk_type, data in after_idat:
        output += encode_chunk(chunk_type, data)
    output += encode_chunk(b"tEXt", b"Software\x00APNG Assembler 3.0")
    output += encode_chunk(b"IEND", b"")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output)
    metadata = inspect_apng(destination)
    expected = {
        "frames": FRAMES,
        "plays": PLAYS,
        "cycle_seconds": 1.0,
        "total_seconds": 4.0,
        "alpha": True,
    }
    for key, value in expected.items():
        if metadata[key] != value:
            raise RuntimeError(f"verification failed for {destination}: {metadata}")
    metadata["sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    return metadata


def sticker_id(path: Path) -> str:
    stem = path.stem
    return stem[:-3] if stem.endswith("@2x") else stem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    if args.source.is_file():
        destination = args.output / args.source.name if args.output.is_dir() else args.output
        metadata = convert_one(args.source, destination)
        print(f"verified {destination} sha256={metadata['sha256']}")
        return

    sources = sorted(
        path
        for path in args.source.glob("*.png")
        if not path.stem.endswith("_thumbnail")
    )
    if not sources:
        raise ValueError(f"no PNG files found in {args.source}")
    identifiers = [sticker_id(path) for path in sources]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate sticker IDs after removing @2x")

    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for source in sources:
        destination = args.output / source.name
        metadata = convert_one(source, destination)
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
