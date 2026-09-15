#!/usr/bin/env python3
"""Run and measure a CPU COLMAP sparse-reconstruction feasibility test."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pycolmap


ROOT = Path(__file__).resolve().parents[1]
SFM_ROOT = (ROOT / "data" / "sfm").resolve()


def timed(name: str, operation: Callable[[], Any], runtimes: dict[str, float]) -> Any:
    started = time.perf_counter()
    try:
        return operation()
    finally:
        runtimes[name] = round(time.perf_counter() - started, 3)


def summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"minimum": None, "median": None, "maximum": None}
    return {
        "minimum": round(min(values), 6),
        "median": round(statistics.median(values), 6),
        "maximum": round(max(values), 6),
    }


def clean_workspace(workspace: Path) -> None:
    resolved = workspace.resolve()
    if resolved == SFM_ROOT or SFM_ROOT not in resolved.parents:
        raise RuntimeError(
            f"Refusing to clean workspace outside a child of {SFM_ROOT}: {resolved}"
        )
    shutil.rmtree(resolved)


def database_metrics(database_path: Path) -> dict[str, Any]:
    database = pycolmap.Database.open(str(database_path))
    try:
        images = database.read_all_images()
        keypoint_counts = [
            float(database.num_keypoints_for_image(image.image_id)) for image in images
        ]
        _, geometries = database.read_two_view_geometries()
        inlier_counts = [
            float(geometry.inlier_matches.shape[0]) for geometry in geometries
        ]
        return {
            "cameras": database.num_cameras(),
            "images": database.num_images(),
            "keypoints": database.num_keypoints(),
            "descriptors": database.num_descriptors(),
            "matched_image_pairs": database.num_matched_image_pairs(),
            "verified_image_pairs": database.num_verified_image_pairs(),
            "inlier_matches": database.num_inlier_matches(),
            "keypoints_per_image": summary(keypoint_counts),
            "inliers_per_verified_pair": summary(inlier_counts),
        }
    finally:
        database.close()


def reconstruction_metrics(
    reconstruction: pycolmap.Reconstruction, total_images: int
) -> dict[str, Any]:
    registered = sorted(
        (reconstruction.image(image_id) for image_id in reconstruction.reg_image_ids()),
        key=lambda image: image.name,
    )
    centers = [image.projection_center().tolist() for image in registered]
    vectors = [
        [current[index] - previous[index] for index in range(3)]
        for previous, current in zip(centers, centers[1:])
    ]
    steps = [math.sqrt(sum(component * component for component in vector)) for vector in vectors]
    turn_angles = []
    for previous, current in zip(vectors, vectors[1:]):
        previous_length = math.sqrt(sum(value * value for value in previous))
        current_length = math.sqrt(sum(value * value for value in current))
        if previous_length == 0 or current_length == 0:
            continue
        cosine = sum(a * b for a, b in zip(previous, current)) / (
            previous_length * current_length
        )
        turn_angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    median_step = statistics.median(steps) if steps else None
    path_length = sum(steps)
    endpoint_displacement = math.dist(centers[0], centers[-1]) if len(centers) > 1 else 0
    return {
        "registered_images": reconstruction.num_reg_images(),
        "registered_percentage": round(
            100.0 * reconstruction.num_reg_images() / total_images, 3
        ),
        "registered_image_names": [image.name for image in registered],
        "cameras": reconstruction.num_cameras(),
        "sparse_points": reconstruction.num_points3D(),
        "observations": reconstruction.compute_num_observations(),
        "mean_track_length": reconstruction.compute_mean_track_length(),
        "mean_observations_per_registered_image": (
            reconstruction.compute_mean_observations_per_reg_image()
        ),
        "mean_reprojection_error_pixels": reconstruction.compute_mean_reprojection_error(),
        "camera_path": {
            "ordered_projection_centers": centers,
            "consecutive_step_distance": summary(steps),
            "consecutive_turn_angle_degrees": summary(turn_angles),
            "path_length_reconstruction_units": round(path_length, 6),
            "endpoint_displacement_reconstruction_units": round(
                endpoint_displacement, 6
            ),
            "endpoint_displacement_to_path_length": (
                round(endpoint_displacement / path_length, 6)
                if path_length > 0
                else None
            ),
            "maximum_to_median_step_ratio": (
                round(max(steps) / median_step, 6)
                if steps and median_step and median_step > 0
                else None
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images",
        type=Path,
        default=ROOT / "data/colmap/huggingface-set02-pilot/images",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=ROOT / "data/sfm/huggingface-set02-pilot",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports/huggingface-sfm.json",
    )
    parser.add_argument(
        "--matcher", choices=("sequential", "exhaustive"), default="sequential"
    )
    parser.add_argument("--max-image-size", type=int, default=3200)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--skip-undistort", action="store_true")
    args = parser.parse_args()

    images = args.images.resolve()
    workspace = args.workspace.resolve()
    database_path = workspace / "database.db"
    sparse_path = workspace / "sparse"
    image_count = len(list(images.glob("*.jpg")))
    if not images.is_dir() or image_count == 0:
        raise SystemExit(f"No JPEG images found in {images}")
    if args.clean and workspace.exists():
        clean_workspace(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    sparse_path.mkdir(parents=True, exist_ok=True)

    runtimes: dict[str, float] = {}
    extraction_options = pycolmap.FeatureExtractionOptions()
    extraction_options.max_image_size = args.max_image_size
    extraction_options.use_gpu = False
    timed(
        "feature_extraction_seconds",
        lambda: pycolmap.extract_features(
            database_path=str(database_path),
            image_path=str(images),
            camera_mode=pycolmap.CameraMode.SINGLE,
            camera_model="SIMPLE_RADIAL",
            extraction_options=extraction_options,
            device=pycolmap.Device.cpu,
        ),
        runtimes,
    )

    matching_options = pycolmap.FeatureMatchingOptions()
    matching_options.use_gpu = False
    if args.matcher == "sequential":
        pairing_options = pycolmap.SequentialPairingOptions()
        pairing_options.overlap = 15
        pairing_options.quadratic_overlap = True
        timed(
            "matching_seconds",
            lambda: pycolmap.match_sequential(
                database_path=str(database_path),
                matching_options=matching_options,
                pairing_options=pairing_options,
                device=pycolmap.Device.cpu,
            ),
            runtimes,
        )
    else:
        timed(
            "matching_seconds",
            lambda: pycolmap.match_exhaustive(
                database_path=str(database_path),
                matching_options=matching_options,
                device=pycolmap.Device.cpu,
            ),
            runtimes,
        )

    mapping_options = pycolmap.IncrementalPipelineOptions()
    mapping_options.multiple_models = True
    mapping_options.min_model_size = 3
    mapping_options.max_num_models = 10
    reconstructions = timed(
        "incremental_mapping_seconds",
        lambda: pycolmap.incremental_mapping(
            database_path=str(database_path),
            image_path=str(images),
            output_path=str(sparse_path),
            options=mapping_options,
        ),
        runtimes,
    )

    ordered_reconstructions = sorted(
        reconstructions.values(),
        key=lambda reconstruction: reconstruction.num_reg_images(),
        reverse=True,
    )
    models = [
        reconstruction_metrics(reconstruction, image_count)
        for reconstruction in ordered_reconstructions
    ]
    models.sort(key=lambda model: model["registered_images"], reverse=True)
    best_registered = models[0]["registered_images"] if models else 0
    training_input = None
    if ordered_reconstructions and not args.skip_undistort:
        best_path = workspace / "best"
        undistorted_path = workspace / "undistorted"
        shutil.rmtree(best_path, ignore_errors=True)
        shutil.rmtree(undistorted_path, ignore_errors=True)
        best_path.mkdir(parents=True)
        ordered_reconstructions[0].write(str(best_path))
        timed(
            "undistortion_seconds",
            lambda: pycolmap.undistort_images(
                output_path=str(undistorted_path),
                input_path=str(best_path),
                image_path=str(images),
                output_type="COLMAP",
            ),
            runtimes,
        )
        undistorted_model = pycolmap.Reconstruction(str(undistorted_path / "sparse"))
        training_input = {
            "path": str(undistorted_path.relative_to(ROOT)),
            "image_count": len(list((undistorted_path / "images").glob("*.jpg"))),
            "camera_models": sorted(
                {camera.model.name for camera in undistorted_model.cameras.values()}
            ),
            "sparse_points": undistorted_model.num_points3D(),
        }
    runtimes["total_seconds"] = round(sum(runtimes.values()), 3)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pycolmap_version": pycolmap.__version__,
        "backend": "COLMAP via official pycolmap macOS arm64 wheel; CPU SIFT",
        "images_directory": str(images.relative_to(ROOT)),
        "workspace": str(workspace.relative_to(ROOT)),
        "input_image_count": image_count,
        "camera_mode": "SINGLE",
        "camera_model": "SIMPLE_RADIAL",
        "max_image_size": args.max_image_size,
        "matcher": args.matcher,
        "runtimes": runtimes,
        "database": database_metrics(database_path),
        "model_count": len(models),
        "best_registered_images": best_registered,
        "best_registered_percentage": round(100.0 * best_registered / image_count, 3),
        "pose_gate": {
            "threshold_percentage": 80.0,
            "passed": best_registered / image_count >= 0.8,
            "reason": (
                "At least 80% of the ordered sequence registered."
                if best_registered / image_count >= 0.8
                else "Fewer than 80% of input images registered in one model."
            ),
        },
        "training_input": training_input,
        "models": models,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({key: report[key] for key in ("model_count", "best_registered_images", "best_registered_percentage", "pose_gate", "runtimes")}, indent=2))


if __name__ == "__main__":
    main()
