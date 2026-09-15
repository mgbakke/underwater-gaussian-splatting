#!/usr/bin/env python3
"""Compare Brush held-out renders with their COLMAP source images."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def global_ssim(reference: np.ndarray, rendered: np.ndarray) -> float:
    """Compute a global RGB SSIM proxy without adding a heavy image dependency."""
    scores = []
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    for channel in range(3):
        x = reference[..., channel]
        y = rendered[..., channel]
        mean_x = float(np.mean(x))
        mean_y = float(np.mean(y))
        var_x = float(np.var(x))
        var_y = float(np.var(y))
        covariance = float(np.mean((x - mean_x) * (y - mean_y)))
        scores.append(
            ((2 * mean_x * mean_y + c1) * (2 * covariance + c2))
            / ((mean_x**2 + mean_y**2 + c1) * (var_x + var_y + c2))
        )
    return float(np.mean(scores))


def luminance(image: np.ndarray) -> np.ndarray:
    return (
        image[..., 0] * 0.2126
        + image[..., 1] * 0.7152
        + image[..., 2] * 0.0722
    )


def laplacian_variance(image: np.ndarray) -> float:
    gray = luminance(image)
    center = gray[1:-1, 1:-1]
    laplacian = (
        gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
        - 4.0 * center
    )
    return float(np.var(laplacian))


def aggregate(records: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "mean_psnr_db": round(statistics.mean(item["psnr_db"] for item in records), 4),
        "median_psnr_db": round(
            statistics.median(item["psnr_db"] for item in records), 4
        ),
        "mean_absolute_error_0_255": round(
            statistics.mean(item["mean_absolute_error_0_255"] for item in records),
            4,
        ),
        "mean_global_ssim": round(
            statistics.mean(item["global_ssim"] for item in records), 6
        ),
        "mean_sharpness_ratio": round(
            statistics.mean(item["sharpness_ratio"] for item in records), 4
        ),
        "mean_luminance_contrast_ratio": round(
            statistics.mean(item["luminance_contrast_ratio"] for item in records),
            4,
        ),
        "mean_excess_dark_pixel_fraction": round(
            statistics.mean(
                item["excess_dark_pixel_fraction"] for item in records
            ),
            6,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--training-dir",
        type=Path,
        default=ROOT / "data/training/pier59-brush-preview-10k",
    )
    parser.add_argument(
        "--ground-truth-dir",
        type=Path,
        default=ROOT / "data/sfm/pier59-video-pilot/undistorted/images",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports/pier59-brush-evaluation.json",
    )
    args = parser.parse_args()
    training_dir = args.training_dir.resolve()
    ground_truth_dir = args.ground_truth_dir.resolve()
    report_path = args.report.resolve()

    stages = []
    for evaluation_dir in sorted(
        training_dir.glob("eval_*"),
        key=lambda path: int(path.name.split("_", 1)[1]),
    ):
        iteration = int(evaluation_dir.name.split("_", 1)[1])
        records = []
        for rendered_path in sorted(evaluation_dir.glob("*.png")):
            reference_path = ground_truth_dir / f"{rendered_path.stem}.jpg"
            if not reference_path.is_file():
                raise SystemExit(f"Missing held-out source image: {reference_path}")
            with Image.open(rendered_path) as rendered_image:
                rendered = np.asarray(rendered_image.convert("RGB"), dtype=np.float32)
            with Image.open(reference_path) as reference_image:
                resized = reference_image.convert("RGB").resize(
                    (rendered.shape[1], rendered.shape[0]), Image.Resampling.LANCZOS
                )
                reference = np.asarray(resized, dtype=np.float32)
            difference = reference - rendered
            mse = float(np.mean(difference * difference))
            psnr = float("inf") if mse == 0 else 10.0 * math.log10(255.0**2 / mse)
            reference_luma = luminance(reference)
            rendered_luma = luminance(rendered)
            reference_sharpness = laplacian_variance(reference)
            rendered_sharpness = laplacian_variance(rendered)
            reference_contrast = float(np.std(reference_luma))
            rendered_contrast = float(np.std(rendered_luma))
            records.append(
                {
                    "image": rendered_path.name,
                    "width": rendered.shape[1],
                    "height": rendered.shape[0],
                    "psnr_db": round(psnr, 4),
                    "mean_absolute_error_0_255": round(
                        float(np.mean(np.abs(difference))), 4
                    ),
                    "global_ssim": round(global_ssim(reference, rendered), 6),
                    "sharpness_ratio": round(
                        rendered_sharpness / reference_sharpness, 4
                    ),
                    "luminance_contrast_ratio": round(
                        rendered_contrast / reference_contrast, 4
                    ),
                    "excess_dark_pixel_fraction": round(
                        float(
                            np.mean(
                                (rendered_luma < 10.0) & (reference_luma > 30.0)
                            )
                        ),
                        6,
                    ),
                }
            )
        stages.append(
            {
                "iteration": iteration,
                "held_out_image_count": len(records),
                **aggregate(records),
                "images": records,
            }
        )
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "training_directory": str(training_dir.relative_to(ROOT)),
        "ground_truth_directory": str(ground_truth_dir.relative_to(ROOT)),
        "metrics": {
            "psnr": "RGB PSNR after Lanczos-resizing ground truth to render dimensions.",
            "mean_absolute_error": "Mean absolute RGB error on the 0-255 scale.",
            "global_ssim": "Global per-channel SSIM averaged over RGB; a lightweight proxy, not windowed SSIM.",
            "sharpness_ratio": "Rendered/reference luminance Laplacian variance. Values below 1 indicate softer output.",
            "luminance_contrast_ratio": "Rendered/reference luminance standard deviation. Values below 1 indicate reduced contrast.",
            "excess_dark_pixel_fraction": "Fraction of pixels below luminance 10 where ground truth exceeds 30; a conservative hole indicator.",
        },
        "stages": stages,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            [
                {
                    key: stage[key]
                    for key in (
                        "iteration",
                        "held_out_image_count",
                        "mean_psnr_db",
                        "mean_absolute_error_0_255",
                        "mean_global_ssim",
                    )
                }
                for stage in stages
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
