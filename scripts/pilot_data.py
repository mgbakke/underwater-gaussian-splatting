#!/usr/bin/env python3
"""Download, prepare, and assess the bounded Seattle Aquarium pilot data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "pilot.json"
TIMESTAMP_RE = re.compile(r"(\d{4}_\d{2}_\d{2}_\d{2}-\d{2}-\d{2})")


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def root_path(value: str) -> Path:
    return ROOT / value


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "ugs-pilot/1.0"})
    try:
        with urllib.request.urlopen(request) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def hf_selected_paths(config: dict[str, Any]) -> list[str]:
    hf = config["hugging_face"]
    metadata_url = (
        f"https://huggingface.co/datasets/{hf['dataset']}/resolve/"
        f"{hf['revision']}/metadata.jsonl?download=true"
    )
    with urllib.request.urlopen(metadata_url) as response:
        lines = response.read().decode("utf-8").splitlines()
    prefix = f"{hf['subset']}/{hf['variant']}/"
    selected = []
    for line in lines:
        record = json.loads(line)
        path = record["output_file_name"]
        stem = Path(path).stem
        if prefix == str(Path(path).parent) + "/" and hf["start"] <= stem <= hf["end"]:
            selected.append(path)
    selected.sort()
    if len(selected) != hf["expected_count"]:
        raise RuntimeError(
            f"Expected {hf['expected_count']} selected images, found {len(selected)}"
        )
    return selected


def download_images(config: dict[str, Any]) -> None:
    hf = config["hugging_face"]
    destination = root_path(hf["destination"])
    destination.mkdir(parents=True, exist_ok=True)
    paths = hf_selected_paths(config)
    for index, source_path in enumerate(paths, start=1):
        output = destination / Path(source_path).name
        if output.exists():
            print(f"[{index:02d}/{len(paths)}] exists {output.name}")
            continue
        url = (
            f"https://huggingface.co/datasets/{hf['dataset']}/resolve/"
            f"{hf['revision']}/{source_path}?download=true"
        )
        print(f"[{index:02d}/{len(paths)}] download {output.name}")
        download(url, output)


def executable(name: str) -> str:
    override = os.environ.get(name.upper())
    candidate = override or shutil.which(name)
    if not candidate:
        raise RuntimeError(
            f"{name} is required. Install ffmpeg or set {name.upper()}=/path/to/{name}."
        )
    return candidate


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True)


def download_ranged_source(url: str, destination: Path) -> dict[str, Any]:
    chunk_size = 32 * 1024 * 1024
    digest = hashlib.sha256()
    total_size: int | None = None
    offset = 0
    with destination.open("wb") as output:
        while total_size is None or offset < total_size:
            end = offset + chunk_size - 1
            error: Exception | None = None
            for attempt in range(1, 6):
                request = urllib.request.Request(
                    url,
                    headers={
                        "Range": f"bytes={offset}-{end}",
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                try:
                    with urllib.request.urlopen(request, timeout=120) as response:
                        content_range = response.headers.get("Content-Range")
                        if not content_range:
                            raise RuntimeError(
                                "Video host did not honor the bounded range request"
                            )
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                        if not match:
                            raise RuntimeError(f"Unexpected Content-Range: {content_range}")
                        start, actual_end, parsed_total = map(int, match.groups())
                        if start != offset:
                            raise RuntimeError(
                                f"Expected byte {offset}, received byte {start}"
                            )
                        data = response.read()
                        expected_size = actual_end - start + 1
                        if len(data) != expected_size:
                            raise RuntimeError(
                                f"Expected {expected_size} bytes, received {len(data)}"
                            )
                        total_size = parsed_total
                        output.write(data)
                        digest.update(data)
                        offset += len(data)
                        print(f"video source: {offset}/{total_size} bytes")
                        error = None
                        break
                except (OSError, RuntimeError) as caught:
                    error = caught
                    if attempt < 5:
                        print(
                            f"Range {offset}-{end} failed; retrying ({attempt}/5)",
                            file=sys.stderr,
                        )
                        time.sleep(attempt * 2)
            if error:
                raise RuntimeError(
                    f"Could not download video range {offset}-{end}: {error}"
                ) from error
    return {"bytes": offset, "sha256": digest.hexdigest()}


def video_ffmpeg_command(
    config: dict[str, Any], source: str, output: Path
) -> list[str]:
    video = config["video"]
    return [
        executable("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-ss",
        str(video["start_seconds"]),
        "-i",
        source,
        "-t",
        str(video["duration_seconds"]),
        "-map",
        "0:v:0",
        "-vf",
        f"scale={video['output_width']}:-2",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-movflags",
        "+faststart",
        "-y",
        str(output),
    ]


def trim_video(config: dict[str, Any]) -> None:
    video = config["video"]
    output = root_path(video["clip_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    local_source = os.environ.get("VIDEO_SOURCE")
    if local_source:
        source = Path(local_source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"VIDEO_SOURCE does not exist: {source}")
        run(video_ffmpeg_command(config, str(source), output))
        return
    source_url = video["download_url"]
    try:
        command = video_ffmpeg_command(config, source_url, output)
        command[4:4] = ["-user_agent", "Mozilla/5.0"]
        run(command)
        return
    except subprocess.CalledProcessError:
        output.unlink(missing_ok=True)
        print(
            "Direct ffmpeg seeking was rejected; downloading the source temporarily "
            "with bounded HTTP range requests.",
            file=sys.stderr,
        )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix="pier59-source-",
            suffix=".source.mp4",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        source_record = download_ranged_source(video["download_url"], temporary_path)
        source_record.update(
            {
                "source_url": video["source_page"],
                "download_url": video["download_url"],
                "temporary_source_deleted_after_trim": True,
            }
        )
        record_path = root_path(config["reports"]["directory"]) / "video-source.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        with record_path.open("w", encoding="utf-8") as handle:
            json.dump(source_record, handle, indent=2)
            handle.write("\n")
        run(video_ffmpeg_command(config, str(temporary_path), output))
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def extract_video_frames(config: dict[str, Any]) -> None:
    video = config["video"]
    source = root_path(video["clip_path"])
    if not source.exists():
        raise FileNotFoundError(f"Missing clip: {source}")
    destination = root_path(video["frames_destination"])
    destination.mkdir(parents=True, exist_ok=True)
    for old_frame in destination.glob("frame-*.jpg"):
        old_frame.unlink()
    run(
        [
            executable("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            str(source),
            "-vf",
            f"fps={video['frame_rate']}",
            "-q:v",
            "2",
            "-start_number",
            "0",
            "-y",
            str(destination / "frame-%06d.jpg"),
        ]
    )


def image_paths(directory: Path) -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    return sorted(path for path in directory.iterdir() if path.suffix.lower() in extensions)


def laplacian_variance(gray: np.ndarray) -> float:
    pixels = gray.astype(np.float32)
    center = pixels[1:-1, 1:-1]
    laplacian = (
        -4 * center
        + pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
    )
    return float(np.var(laplacian))


def difference_hash(gray_image: Image.Image, width: int = 9, height: int = 8) -> int:
    values = np.asarray(gray_image.resize((width, height), Image.Resampling.LANCZOS))
    bits = values[:, 1:] > values[:, :-1]
    result = 0
    for bit in bits.ravel():
        result = (result << 1) | int(bit)
    return result


def timestamp_from_name(path: Path) -> datetime | None:
    match = TIMESTAMP_RE.search(path.stem)
    return datetime.strptime(match.group(1), "%Y_%m_%d_%H-%M-%S") if match else None


def analyze_directory(directory: Path, expected_spacing: float | None) -> dict[str, Any]:
    paths = image_paths(directory)
    if not paths:
        raise RuntimeError(f"No images found in {directory}")
    records = []
    exact_hashes: Counter[str] = Counter()
    dimensions: Counter[str] = Counter()
    previous_dhash: int | None = None
    adjacent_hamming = []
    timestamps = []
    for path in paths:
        with Image.open(path) as source:
            image = source.convert("RGB")
            dimensions[f"{image.width}x{image.height}"] += 1
            analysis = image.copy()
            analysis.thumbnail((768, 768), Image.Resampling.LANCZOS)
            gray = analysis.convert("L")
            stat = ImageStat.Stat(analysis)
            dhash = difference_hash(gray)
            if previous_dhash is not None:
                adjacent_hamming.append(bin(previous_dhash ^ dhash).count("1"))
            previous_dhash = dhash
            digest = sha256_file(path)
            exact_hashes[digest] += 1
            timestamp = timestamp_from_name(path)
            if timestamp:
                timestamps.append(timestamp)
            records.append(
                {
                    "file": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                    "width": image.width,
                    "height": image.height,
                    "blur_laplacian_variance": round(laplacian_variance(np.asarray(gray)), 3),
                    "mean_rgb": [round(value, 3) for value in stat.mean],
                    "stddev_rgb": [round(value, 3) for value in stat.stddev],
                    "dhash_64": f"{dhash:016x}",
                }
            )
    spacings = [
        (current - previous).total_seconds()
        for previous, current in zip(timestamps, timestamps[1:])
    ]
    duplicate_groups = [
        {"sha256": digest, "count": count}
        for digest, count in exact_hashes.items()
        if count > 1
    ]
    blur_values = [record["blur_laplacian_variance"] for record in records]
    byte_total = sum(record["bytes"] for record in records)
    report = {
        "directory": str(directory.relative_to(ROOT)),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "image_count": len(records),
        "total_bytes": byte_total,
        "dimensions": dict(dimensions),
        "exact_duplicate_groups": duplicate_groups,
        "adjacent_dhash_hamming": {
            "minimum": min(adjacent_hamming) if adjacent_hamming else None,
            "median": float(np.median(adjacent_hamming)) if adjacent_hamming else None,
            "maximum": max(adjacent_hamming) if adjacent_hamming else None,
        },
        "blur_laplacian_variance": {
            "minimum": min(blur_values),
            "median": float(np.median(blur_values)),
            "maximum": max(blur_values),
        },
        "temporal_spacing_seconds": {
            "expected": expected_spacing,
            "values": dict(Counter(str(value) for value in spacings)),
            "minimum": min(spacings) if spacings else None,
            "median": float(np.median(spacings)) if spacings else None,
            "maximum": max(spacings) if spacings else None,
        },
        "files": records,
    }
    return report


def write_report(config: dict[str, Any], name: str, directory: Path, spacing: float | None) -> None:
    report = analyze_directory(directory, spacing)
    destination = root_path(config["reports"]["directory"]) / f"{name}-quality.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(
        f"{name}: {report['image_count']} images, {report['total_bytes']} bytes, "
        f"report -> {destination.relative_to(ROOT)}"
    )


def quality_report(config: dict[str, Any], target: str) -> None:
    if target in {"huggingface", "all"}:
        hf = config["hugging_face"]
        write_report(config, "huggingface", root_path(hf["destination"]), 3.0)
    if target in {"video", "all"}:
        video = config["video"]
        write_report(
            config,
            "video",
            root_path(video["frames_destination"]),
            1.0 / float(video["frame_rate"]),
        )


def link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def prepare_one_colmap(name: str, source: Path, destination_root: Path) -> None:
    destination = destination_root / name / "images"
    destination.mkdir(parents=True, exist_ok=True)
    for existing in image_paths(destination):
        existing.unlink()
    for index, path in enumerate(image_paths(source)):
        output = destination / f"{index:06d}{path.suffix.lower()}"
        link_or_copy(path, output)
    print(f"{name}: {len(image_paths(destination))} COLMAP-ready images -> {destination}")


def prepare_colmap(config: dict[str, Any], target: str) -> None:
    destination = root_path(config["colmap"]["destination"])
    if target in {"huggingface", "all"}:
        prepare_one_colmap(
            "huggingface-set02-pilot",
            root_path(config["hugging_face"]["destination"]),
            destination,
        )
    if target in {"video", "all"}:
        prepare_one_colmap(
            "pier59-video-pilot",
            root_path(config["video"]["frames_destination"]),
            destination,
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = result.add_subparsers(dest="command", required=True)
    subparsers.add_parser("download-images")
    subparsers.add_parser("trim-video")
    subparsers.add_parser("extract-video-frames")
    for command in ("quality-report", "prepare-colmap"):
        child = subparsers.add_parser(command)
        child.add_argument(
            "--all",
            action="store_true",
            help="Process both the Hugging Face and video datasets.",
        )
        child.add_argument(
            "--target",
            choices=("huggingface", "video"),
            default="huggingface",
        )
    return result


def main() -> None:
    args = parser().parse_args()
    config = load_config(args.config)
    commands = {
        "download-images": download_images,
        "trim-video": trim_video,
        "extract-video-frames": extract_video_frames,
    }
    try:
        if args.command in commands:
            commands[args.command](config)
        else:
            target = "all" if args.all else args.target
            if args.command == "quality-report":
                quality_report(config, target)
            else:
                prepare_colmap(config, target)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
