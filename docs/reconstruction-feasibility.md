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

The latest published Brush v0.3.0 Apple ARM archive was downloaded to a
temporary directory and verified against its upstream SHA-256:

```text
65b2631398c839be3c1d4d7160fe2326389dec87830aac0710985e6690a1048c
```

Two 10-step, 512-pixel smoke tests first confirmed that Brush could load both
generated COLMAP projects, optimize, and export PLY files:

| Input | Wall time | Smoke artifact |
|---|---:|---:|
| 59 stills | 2.52 s | 7,244,390 bytes |
| 86 video frames | 1.46 s | 12,124,634 bytes |

The first bounded real training run then used the refined Pier 59 sequence. It
held out every tenth registered image, trained for 10,000 steps at a maximum
dimension of 1536 pixels, stopped densification at step 7,000, and capped the
model at two million splats. The undistorted inputs are 1927 x 1080; Brush's
training/evaluation resolution was 1536 x 861.

```bash
# After downloading and verifying Brush as shown below:
BRUSH=/tmp/brush-app-aarch64-apple-darwin/brush_app \
  python scripts/run_brush.py --clean
python scripts/evaluate_brush.py
```

The runner expands to:

```bash
/tmp/brush-app-aarch64-apple-darwin/brush_app \
  --total-steps 10000 \
  --max-resolution 1536 \
  --max-frames 86 \
  --max-splats 2000000 \
  --growth-stop-iter 7000 \
  --eval-split-every 10 \
  --eval-every 1000 \
  --eval-save-to-disk \
  --export-every 2500 \
  --export-path data/training/pier59-brush-preview-10k \
  --export-name 'pier59_{iter}.ply' \
  data/sfm/pier59-video-pilot/undistorted
```

| Training metric | Result |
|---|---:|
| Registered input frames | 86 / 86 |
| Optimization steps | 10,000 |
| Wall-clock time | 228.660 s |
| Maximum resident set size | 1,193,050,112 bytes |
| Peak memory footprint | 2,888,402,816 bytes |
| Page faults / swaps | 527 / 0 |
| Final splats | 330,908 |
| Total local training output | 354,114,798 bytes (96 files) |
| Brush warnings in log | None |

| Checkpoint | Splats | Bytes | SHA-256 |
|---|---:|---:|---|
| 2,500 | 118,559 | 27,981,475 | `f208bd64a5fd3256eea8b17ef5b572c33f3980a0e61292b432d5fefbadcb7311` |
| 5,000 | 229,336 | 54,124,847 | `5a5e904fd03137da352ca66f22976f5725499985613eb10726741d2b7f919b45` |
| 7,500 | 330,908 | 78,095,839 | `61458080501cb3eed7f81b200b65879a295e7dc83b100d8d56c2dfb0b4264879` |
| 10,000 | 330,908 | 78,095,839 | `99a7dd677623e8ff0ff647ce52e579c1c1240af2d4c6fe758f6c8e6048a0599e` |

Brush saved nine held-out registered-camera renders every 1,000 steps. Brush
v0.3.0 did not print numeric metrics, so `scripts/evaluate_brush.py` compares
those renders with Lanczos-resized ground truth:

| Step | Mean PSNR | Mean absolute error | Global SSIM proxy |
|---|---:|---:|---:|
| 1,000 | 28.6245 dB | 7.0075 | 0.904721 |
| 5,000 | 31.1966 dB | 5.3443 | 0.952169 |
| 10,000 | 32.0507 dB | 4.6879 | 0.959408 |

The final held-out PSNR ranged from 26.4957 dB (`000070.png`) to 35.0168 dB
(`000010.png`). The reported `global_ssim` is a lightweight global,
per-channel proxy rather than standard windowed SSIM.

Representative and worst-case held-out views show coherent seafloor geometry
and stable shell/rock structure. There is no scene-boundary jump and no
catastrophic floater field from the tested cameras. Remaining defects are
softening and edge smearing in low-texture regions, occasional dark/soft
peripheral regions, and modest green/yellow color drift. This is sufficient
evidence for a reconstruction/training proof of feasibility, not a
publication-quality model.

Brush v0.3.0's CLI does not expose a noninteractive arbitrary-camera render
command, so this run did not fabricate a separate novel camera path. It
exported the final PLY for interactive novel-view inspection and used genuinely
held-out registered views for quantitative evaluation. Local-only artifacts:

- `data/training/pier59-brush-preview-10k/pier59_10000.ply`
- `data/training/pier59-brush-preview-10k/eval_10000/`
- `data/training/pier59-brush-preview-10k/training.log`
- `data/training/pier59-brush-preview-10k/resource-usage.txt`

These files remain ignored because the source video's redistribution license is
unspecified. No source frames, evaluation renders, or trained PLYs are
committed. Exact metadata and per-view results are in
`reports/pier59-brush-training.json` and
`reports/pier59-brush-evaluation.json`.

To reproduce the external Brush installation:

```bash
# Download and verify the upstream Apple ARM release outside the repository.
curl -fL \
  https://github.com/ArthurBrussee/brush/releases/download/v0.3.0/brush-app-aarch64-apple-darwin.tar.xz \
  -o /tmp/brush-app.tar.xz
printf '%s  %s\n' \
  65b2631398c839be3c1d4d7160fe2326389dec87830aac0710985e6690a1048c \
  /tmp/brush-app.tar.xz | shasum -a 256 -c -
tar -xJf /tmp/brush-app.tar.xz -C /tmp
```

The bounded direct-Brush path is the practical M4 baseline. Splat Local remains
the preferred next orchestration/viewer layer, but increasing to its 18k/2048
"High" profile should wait until the final PLY has been interactively inspected
from off-trajectory viewpoints. Moving fauna, lighting changes, and suspended
particles should be masked or treated as outliers if they produce floaters.

## High-quality and haze-reduction follow-up

Interactive inspection of the baseline showed that reducing the viewer's
Splat Scale did not remove the soft, fog-like appearance at close range. Two
matched 7,000-step, full-resolution previews therefore compared detail-first
training with moderate opacity/scale regularization. The regularized preview
slightly improved PSNR, SSIM, and contrast while retaining a zero conservative
dark-hole fraction, so it was promoted to the final 18,000-step run.

```bash
BRUSH=/tmp/brush-app-aarch64-apple-darwin/brush_app \
  python scripts/run_brush.py \
    --config configs/brush-pier59-high-quality.json \
    --clean

python scripts/evaluate_brush.py \
  --training-dir data/training/pier59-brush-high-quality-18k \
  --report reports/pier59-brush-high-quality-evaluation.json
```

The selected preset uses the full 1920-pixel input width, a 1.5M-splat cap,
18,000 steps, refinement every 100 steps, densification through step 12,000,
a 0.15 growth-selection fraction, `3e-9` opacity loss, and `3e-8` scale loss.

| Metric | Baseline 10k | Selected 18k |
|---|---:|---:|
| Render resolution | 1536 x 861 | 1920 x 1076 |
| Final splats | 330,908 | 1,500,000 |
| Wall-clock time | 228.660 s | 995.617 s |
| Peak memory footprint | 2,888,402,816 bytes | 6,181,112,712 bytes |
| Mean PSNR | 32.0507 dB | 32.2906 dB |
| Mean absolute error | 4.6879 | 4.6544 |
| Global SSIM proxy | 0.959408 | 0.963730 |
| Mean sharpness ratio | 0.3429 | 0.4642 |
| Mean luminance contrast ratio | 0.9752 | 0.9831 |
| Excess dark-pixel fraction | 0 | 0 |

The sharpness proxy improved by 35.37% relative to the baseline. Representative
held-out views show visibly crisper shell and rock boundaries, better local
contrast, and complete coverage without visible black holes. Moderate haze
remains where it is present in the source imagery, and extreme close-ups or
off-trajectory views still expose the limits of the 1920 x 1080 source video.

The final local PLY is:

`data/training/pier59-brush-high-quality-18k/pier59-high-quality-18000.ply`

It contains 1,500,000 splats, is 354,001,552 bytes, and has SHA-256
`0661d3a8319a795b2b5a5d1eadc4b4d83bf5e9a96091743e307e926c12b0defe`.
All preview/final PLYs, evaluation renders, and local comparison sheets remain
ignored because the source video's redistribution license is unspecified.
