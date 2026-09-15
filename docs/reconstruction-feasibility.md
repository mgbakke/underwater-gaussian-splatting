# Reconstruction feasibility

## Method

The real feasibility test uses the official `pycolmap` 3.13.0 macOS ARM wheel and CPU SIFT:

```bash
python -m pip install -r requirements-sfm.txt
python scripts/run_sfm.py --clean
```

Configuration:

- One shared `SIMPLE_RADIAL` camera during reconstruction.
- Features downscaled to at most 3200 pixels for 4606 x 4030 stills.
- Sequential matching with overlap 15 and quadratic overlap.
- Incremental mapping, followed by COLMAP undistortion to a training-ready `PINHOLE` project.
- Pose gate: at least 80% of inputs registered in one model.

The script records feature/match database statistics, phase runtimes, registered images, sparse points, observations, reprojection error, and ordered camera-center coherence.

## Processed still-image result

| Metric | Result |
|---|---:|
| Input / registered | 59 / 59 (100%) |
| Sparse models | 1 |
| SIFT keypoints | 803,376 |
| Verified image pairs | 291 |
| Inlier matches | 177,659 |
| Sparse points | 30,690 |
| Observations | 111,268 |
| Mean track length | 3.626 |
| Mean reprojection error | 1.089 px |
| Feature extraction | 48.621 s |
| Matching | 13.483 s |
| Incremental mapping | 43.032 s |
| Undistortion | 4.058 s |
| Total | 109.194 s |

The ordered path is broadly linear: endpoint displacement is 92.7% of total path length, median consecutive step is 0.231 reconstruction units, and the maximum step is only 1.21x the median. The maximum turn angle (127.8 degrees) occurs among the very small initial steps; it is a local initialization wobble rather than a large positional jump. The 100% registration and smooth dominant path make the still sequence viable for a first static-splat experiment despite its 3-second cadence.

## Pier 59 video result

The first 60-second window registered only 86/120 frames in its largest model. Inspection of membership showed a scene boundary: frames 0–31 belonged to the opening view, frames 32–117 to the main transect, and the final two frames did not join. The retained source interval was refined from 120–180 seconds to 136–179 seconds.

```bash
python scripts/run_sfm.py --clean \
  --images data/colmap/pier59-video-pilot/images \
  --workspace data/sfm/pier59-video-pilot \
  --report reports/pier59-video-sfm.json \
  --max-image-size 1920
```

| Metric | Result |
|---|---:|
| Input / registered | 86 / 86 (100%) |
| SIFT keypoints | 843,006 |
| Verified image pairs | 475 |
| Inlier matches | 504,625 |
| Sparse points | 51,369 |
| Observations | 318,918 |
| Mean track length | 6.208 |
| Mean reprojection error | 0.717 px |
| Feature extraction | 10.767 s |
| Matching | 9.648 s |
| Incremental mapping | 115.826 s |
| Undistortion | 0.637 s |
| Total | 136.878 s |

The video path is especially coherent: endpoint displacement is 95.8% of path length, median turn is 2.23 degrees, median step is 0.147 reconstruction units, and maximum step is 1.90x median. It is the preferred first training input because it has denser overlap, longer tracks, and lower reprojection error.

`pycolmap` returned a second tiny alternative model in some nondeterministic mapper runs. The complete 86-camera model remains the clear primary output; downstream tooling uses the model with the greatest registered-image count.

## Metal-native training gate

No long training run was started. The latest published Brush v0.3.0 Apple ARM archive was downloaded to a temporary directory and verified against its upstream SHA-256:

```text
65b2631398c839be3c1d4d7160fe2326389dec87830aac0710985e6690a1048c
```

Two 10-step, 512-pixel smoke tests successfully loaded the generated COLMAP projects, optimized, and exported PLY files:

| Input | Wall time | Smoke artifact |
|---|---:|---:|
| 59 stills | 2.52 s | 7,244,390 bytes |
| 86 video frames | 1.46 s | 12,124,634 bytes |

Temporary binaries and PLYs were not committed. A practical first preview run on the preferred video sequence is:

```bash
# Download and verify the upstream Apple ARM release outside the repository.
curl -fL \
  https://github.com/ArthurBrussee/brush/releases/download/v0.3.0/brush-app-aarch64-apple-darwin.tar.xz \
  -o /tmp/brush-app.tar.xz
printf '%s  %s\n' \
  65b2631398c839be3c1d4d7160fe2326389dec87830aac0710985e6690a1048c \
  /tmp/brush-app.tar.xz | shasum -a 256 -c -
tar -xJf /tmp/brush-app.tar.xz -C /tmp

/tmp/brush-app-aarch64-apple-darwin/brush_app \
  --total-steps 10000 \
  --max-resolution 1536 \
  --eval-split-every 10 \
  --eval-every 1000 \
  --export-every 5000 \
  --export-path /path/out \
  data/sfm/pier59-video-pilot/undistorted
```

Equivalent command after installing `brush_app` on `PATH`:

```bash
brush_app \
  --total-steps 10000 \
  --max-resolution 1536 \
  --eval-split-every 10 \
  --eval-every 1000 \
  --export-every 5000 \
  --export-path /path/out \
  data/sfm/pier59-video-pilot/undistorted
```

That command is documented, not executed. Review held-out views and trajectory-aligned artifacts before increasing to Splat Local's 18k/2048 “High” profile. Moving fauna, lighting changes, and suspended particles should be masked or treated as outliers if they produce floaters.
