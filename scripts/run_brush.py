#!/usr/bin/env python3
"""Run a bounded Brush training job and record reproducibility metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TRAINING_ROOT = (ROOT / "data" / "training").resolve()
DEFAULT_CONFIG = ROOT / "configs" / "brush-pier59-preview.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ply_vertex_count(path: Path) -> int:
    with path.open("rb") as handle:
        while line := handle.readline():
            decoded = line.decode("ascii").strip()
            if decoded.startswith("element vertex "):
                return int(decoded.rsplit(maxsplit=1)[1])
            if decoded == "end_header":
                break
    raise ValueError(f"PLY vertex count not found in {path}")


def image_dimensions(path: Path) -> list[int]:
    with Image.open(path) as image:
        return [image.width, image.height]


def parse_resource_usage(text: str) -> dict[str, int | None]:
    patterns = {
        "maximum_resident_set_size_bytes": r"^\s*(\d+)\s+maximum resident set size$",
        "peak_memory_footprint_bytes": r"^\s*(\d+)\s+peak memory footprint$",
        "page_reclaims": r"^\s*(\d+)\s+page reclaims$",
        "page_faults": r"^\s*(\d+)\s+page faults$",
        "swaps": r"^\s*(\d+)\s+swaps$",
    }
    result: dict[str, int | None] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        result[key] = int(match.group(1)) if match else None
    return result


def safe_clean(path: Path) -> None:
    resolved = path.resolve()
    if resolved == TRAINING_ROOT or TRAINING_ROOT not in resolved.parents:
        raise RuntimeError(
            f"Refusing to clean output outside a child of {TRAINING_ROOT}: {resolved}"
        )
    shutil.rmtree(resolved)


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the command without training."
    )
    args = parser.parse_args()

    config = load_config(args.config)
    brush_value = os.environ.get("BRUSH") or shutil.which("brush_app")
    if not brush_value:
        raise SystemExit("Set BRUSH=/path/to/brush_app or install brush_app on PATH.")
    brush = Path(brush_value).expanduser().resolve()
    input_path = (ROOT / config["input"]).resolve()
    output_path = (ROOT / config["output"]).resolve()
    report_path = (ROOT / config["report"]).resolve()
    if not input_path.is_dir():
        raise SystemExit(f"Missing training input: {input_path}")
    input_images = sorted(
        path
        for path in (input_path / "images").glob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not input_images:
        raise SystemExit(f"No training images found under {input_path / 'images'}")
    if args.clean and output_path.exists():
        safe_clean(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    command = [
        str(brush),
        "--total-steps",
        str(config["total_steps"]),
        "--max-resolution",
        str(config["max_resolution"]),
        "--max-frames",
        str(config["max_frames"]),
        "--max-splats",
        str(config["max_splats"]),
        "--growth-stop-iter",
        str(config["growth_stop_iter"]),
        "--eval-split-every",
        str(config["eval_split_every"]),
        "--eval-every",
        str(config["eval_every"]),
        "--eval-save-to-disk",
        "--export-every",
        str(config["export_every"]),
        "--export-path",
        str(output_path),
        "--export-name",
        config["export_name"],
        str(input_path),
    ]
    print(shlex.join(command))
    if args.dry_run:
        return

    log_path = output_path / "training.log"
    resource_path = output_path / "resource-usage.txt"
    timed_command = ["/usr/bin/time", "-l", "-o", str(resource_path), *command]
    started_at = datetime.now().astimezone()
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(
            timed_command,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    wall_seconds = time.perf_counter() - started
    completed_at = datetime.now().astimezone()
    resource_text = resource_path.read_text(encoding="utf-8")
    all_output_files = sorted(path for path in output_path.rglob("*") if path.is_file())
    exports = []
    for path in all_output_files:
        if path.is_file() and path not in {log_path, resource_path}:
            artifact = {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            if path.suffix.lower() == ".ply":
                artifact["splat_count"] = ply_vertex_count(path)
            exports.append(artifact)
    report = {
        "name": config["name"],
        "status": "completed" if process.returncode == 0 else "failed",
        "return_code": process.returncode,
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "wall_clock_seconds": round(wall_seconds, 3),
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "brush": {
            "version": config["brush_version"],
            "binary_path": str(brush),
            "archive_sha256": config["brush_archive_sha256"],
        },
        "input": {
            "path": config["input"],
            "image_count": len(input_images),
            "image_resolution": image_dimensions(input_images[0]),
        },
        "parameters": {
            key: config[key]
            for key in (
                "total_steps",
                "max_resolution",
                "max_frames",
                "max_splats",
                "growth_stop_iter",
                "eval_split_every",
                "eval_every",
                "export_every",
                "export_name",
            )
        },
        "command": command,
        "resource_usage": parse_resource_usage(resource_text),
        "local_artifacts": {
            "output_directory": config["output"],
            "file_count": len(all_output_files),
            "total_bytes": sum(path.stat().st_size for path in all_output_files),
            "training_log": str(log_path.relative_to(ROOT)),
            "resource_usage": str(resource_path.relative_to(ROOT)),
            "evaluation_render_resolution": next(
                (
                    image_dimensions(path)
                    for path in sorted(output_path.glob("eval_*/*.png"))
                ),
                None,
            ),
            "files": exports,
        },
        "warnings": [],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"report: {report_path.relative_to(ROOT)}")
    if process.returncode != 0:
        print(f"Brush failed; inspect {log_path}", file=sys.stderr)
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
