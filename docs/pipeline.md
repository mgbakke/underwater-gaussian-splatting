# Pipeline boundary and technology shortlist

## Current boundary

This repository now validates the complete bounded pilot path through sparse
registration and a first static Gaussian-splat model:

```text
selected source frames
  -> quality report and duplicate checks
  -> data/colmap/<pilot>/images
  -> COLMAP camera registration and PINHOLE undistortion
  -> bounded Brush/Metal static Gaussian splatting training
  -> held-out registered-view evaluation
```

`scripts/run_sfm.py` performs feature extraction, sequential matching,
incremental mapping, and image undistortion through the official `pycolmap`
wheel. `scripts/run_brush.py` consumes the resulting COLMAP project, while
`scripts/evaluate_brush.py` measures its held-out registered-camera renders.
For underwater footage, inspect registration coverage, reprojection error, and
camera trajectory before training; color cast, particles, caustics, moving
organisms, and low inter-frame overlap can all produce plausible-looking but
incorrect poses.

The feasibility run now produces training-ready, undistorted `PINHOLE` projects under:

- `data/sfm/huggingface-set02-pilot/undistorted`
- `data/sfm/pier59-video-pilot/undistorted`

Both media-derived directories remain gitignored. Metrics are committed in `reports/*-sfm.json`.

The refined Pier 59 project also has a completed 10,000-step Brush v0.3.0
reference run: 330,908 final splats, 228.660 seconds wall time, and 32.0507 dB
mean PSNR on nine held-out registered views. Training outputs remain ignored
under `data/training/pier59-brush-preview-10k`; committed measurements are in
`reports/pier59-brush-training.json` and
`reports/pier59-brush-evaluation.json`.

## Aquarium-specific evaluation order

The following projects are **optional references, not installed or executed by this pilot**. Confirm each upstream license at the pinned revision before integration.

| Order | Role | Project | Upstream license | Aquarium-specific use |
|---|---|---|---|---|
| 1 | Baseline training | [Nerfstudio Splatfacto](https://docs.nerf.studio/nerfology/methods/splat.html) with [gsplat](https://github.com/nerfstudio-project/gsplat) | Apache-2.0 | Maintained Python pipeline and viewer; preferred reference on a CUDA-capable host. |
| 1b | Benchmark reference | [graphdeco-inria/gaussian-splatting](https://github.com/graphdeco-inria/gaussian-splatting) | Non-commercial research/evaluation license; verify current terms | Keep as the original-method benchmark, not the primary local workflow. |
| 2 | Camera poses | [COLMAP](https://github.com/colmap/colmap) / [GLOMAP](https://github.com/colmap/glomap) | COLMAP custom BSD-style / GLOMAP BSD-3-Clause; verify current files | First attempt for both pilots; assess whether 3-second still spacing registers reliably. |
| 2b | Pose fallback | [VGGT Factor Refinement](https://github.com/jashshah999/vggt-factor-refinement) | Verify upstream before integration | Fallback when underwater appearance changes or sparse overlap defeat feature matching; exports COLMAP format. |
| 3 | Long-transect scaling | [splatreg](https://github.com/Archerkattri/splatreg) | BSD-3-Clause | Segment long transects into local reconstructions, then align/merge splats rather than optimize one huge scene. |
| 4 | Inspection/editing | [SuperSplat](https://github.com/playcanvas/supersplat) | MIT | Browser-based cleanup and inspection of static results. |
| 4 | Conversion/delivery | [SplatTransform](https://github.com/playcanvas/splat-transform), [SOG](https://blog.playcanvas.com/playcanvas-open-sources-sog-format-for-gaussian-splatting/), and [SPZ](https://github.com/nianticlabs/spz) | SplatTransform MIT / SPZ MIT / verify SOG specification terms | Convert and compress accepted splats for web delivery. |
| 4 | Lightweight web viewing | [gsplat.js](https://github.com/huggingface/gsplat.js) or [SuperSplat Viewer](https://github.com/playcanvas/supersplat-viewer) | MIT / MIT | Candidate viewers after a static asset exists. |
| 5 | Dynamic scenes | [splaTV](https://github.com/antimatter15/splaTV), DynGSplat references | splaTV MIT / verify the selected DynGSplat implementation | Defer until static substrate works; moving kelp and fish should first be treated as outliers. |

## Apple Silicon path

The local reference machine is a MacBook Pro with an M4 Max, 40-core GPU, Metal 4, and 64 GB unified memory. Preprocessing in this repository is Mac-native and does not assume CUDA.

- [Splat Local](https://github.com/michael-L-i/splat-local) combines COLMAP/GLOMAP poses with Metal-native [Brush](https://github.com/ArthurBrussee/brush) training and is the preferred next orchestration and interactive-viewer layer.
- [MetalSplat](https://github.com/tchauffi/metalsplat) is an MIT-licensed PyTorch/Metal experiment worth benchmarking on the M4 Max.
- [LichtFeld Studio](https://github.com/MrNeRF/LichtFeld-Studio) is a GPL-3.0 desktop training/inspection option, but its CUDA-oriented platform support and integration license must be checked before adoption.

**Recommended local order:** use the checksum-verified prebuilt Brush ARM binary directly on the generated undistorted COLMAP project, then adopt Splat Local's orchestration/UI if desired. Splat Local's setup currently requires Homebrew and `uv`, neither of which was present; a source Brush build also needs Rust 1.88+. The prebuilt Brush v0.3.0 archive is only 41,447,012 bytes and avoids those setup dependencies. MetalSplat is promising but currently requires Python 3.12+, PyTorch 2.14+, and pycolmap 4.2+, making it a less conservative first integration than the verified standalone Brush binary.

The CUDA/Nerfstudio path remains the reproducibility baseline on a compatible remote workstation. Local Metal results should be compared against it using the same registered cameras and held-out views.

This shortlist is informed by [Awesome 3D Gaussian Splatting](https://github.com/MrNeRF/awesome-3D-gaussian-splatting); the curated list is a discovery source, not evidence that every linked project is suitable or license-compatible.
