# Seattle Aquarium pilot data

## Selected still-image sequence

The pilot uses processed JPEGs from `set02/output` in the Seattle Aquarium Coastal Climate Resilience benthic imagery dataset:

- Window: `2025_01_22_09-58-08.jpg` through `2025_01_22_10-01-03.jpg`
- Count: 59 consecutive files
- Nominal spacing: 3 seconds, with one 4-second interval
- Native dimensions: 4606 x 4030 pixels
- Scene: predominantly static gravel, shell hash, and small rocks with limited macroalgae

This sequence was selected after visually comparing representative frames from four long non-reject runs. It has less moving kelp and more uniformly distributed texture than the `set01` candidates. The 3-second acquisition cadence is a material risk: visual inspection shows useful scene continuity, but noticeably less overlap than a conventional photogrammetry capture. Treat this source as a challenging sparse-overlap benchmark rather than the only path to a successful reconstruction.

**License and attribution:** [Seattle Aquarium Coastal Climate Resilience benthic imagery](https://huggingface.co/datasets/Seattle-Aquarium/Seattle_Aquarium_benthic_imagery) by Seattle Aquarium Coastal Climate Resilience is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Use is restricted to non-commercial purposes, attribution is required, and adaptations must indicate changes.

## Selected video sequence

The denser-overlap pilot uses the Seattle Aquarium Pier 59 downward-facing “Light and mock transect tests at varying ROV altitudes and light power settings” video linked from the [ROV video index](https://github.com/zhrandell/Seattle_Aquarium_ROV_development/blob/main/ROV_videos.md).

- Source file: `2022_6_23_downward.mp4`
- Source metadata: 3840 x 2160 H.264, 29.97 fps, 5:53.59, 2,156,206,620 bytes
- Selected interval: 120–180 seconds
- Intended retained local clip: 1920-pixel width, H.264 CRF 18, no audio
- Intended extraction: 2 fps, 120 JPEG frames
- Scene: downward view of shell-rich static substrate and fixed structure; moderate green cast and limited peripheral algae

The public endpoint initially supported byte ranges and ffmpeg inspection: source metadata was read and three representative frames around 120 seconds were visually inspected. During the reproducibility run, direct ffmpeg seeking began returning an HTML denial; a bounded 32 MiB range fallback transferred 1,644,167,168 bytes before the host stopped honoring ranges. A separate `gdown` attempt confirmed Google Drive's “too many users have viewed or downloaded this file recently” public quota. The partial source was deleted automatically, so **no video clip or video frames are retained in the pilot**. The downloader remains implemented with direct seeking plus retryable range fallback and accepts `VIDEO_SOURCE=/local/file.mp4` for a browser-downloaded copy. Re-run `trim-video` when the quota resets, then extract and assess frames with the documented commands.

**Permission warning:** the ROV index describes stable public download links but does not specify a license for the linked videos. Do not assume the Hugging Face dataset’s CC BY-NC 4.0 license applies to this video. Verify reproduction, redistribution, model-training, and publication permissions with Seattle Aquarium (the source index lists `z.randell@seattleaquarium.org` and `m.williams@seattleaquarium.org`) before use beyond local evaluation.

## Quality records

The committed machine-readable records are:

- [`manifests/pilot-sources.json`](../manifests/pilot-sources.json): provenance, source metadata, acquisition details, checksums, counts, and selection rationale.
- [`reports/huggingface-quality.json`](../reports/huggingface-quality.json): per-image dimensions, sizes, checksums, blur proxy, RGB statistics, perceptual hashes, duplicates, and timestamp spacing.
- `reports/video-quality.json`: produced with the same measurements once the blocked video acquisition succeeds; it is intentionally absent from this validation run.

Blur is reported as variance of a four-neighbor Laplacian on a downscaled grayscale image. It is a relative sharpness proxy, not a universal pass/fail threshold. Adjacent 64-bit difference-hash distances and exact SHA-256 groups provide lightweight duplicate detection.

No source media, extracted frames, or contact sheets are committed.

## Validation run

Commands executed on 2026-09-14:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/pilot_data.py download-images
.venv/bin/python scripts/pilot_data.py quality-report --target huggingface
.venv/bin/python scripts/pilot_data.py prepare-colmap --target huggingface
```

Results:

- 59/59 selected JPEGs downloaded; 368,939,179 bytes (359 MiB on disk).
- All 59 images are 4606 x 4030; no exact duplicates.
- Timestamp intervals: 57 at 3 seconds and one at 4 seconds.
- Adjacent difference-hash Hamming distance: min 8, median 25, max 38.
- Laplacian-variance blur proxy: min 1021.696, median 1256.042, max 1787.964.
- 59 deterministically renamed images prepared under `data/colmap/huggingface-set02-pilot/images`.
- Aggregate selection checksum: `d06853104fced574dcc90668bbe034b6f4bfdba8e4428db36609692815cf4a60`.

The video trim/extract/report/COLMAP path was separately validated with a generated six-second 640 x 360 MP4: a three-second 320 x 180 clip produced six frames at 2 fps, six quality records, and six COLMAP-ready images. Synthetic media and reports were removed after validation. The real Pier 59 source remained blocked by Google Drive’s public quota as described above.
