# Underwater Gaussian Splatting Pilot

This repository provides a reproducible, small-data foundation for evaluating static-scene Gaussian splatting on public Seattle Aquarium imagery. Downloaded media and generated frames stay outside git; configuration, checksums, quality summaries, and preparation tools are versioned.

The initial pilot targets two complementary sources:

- **59 processed still images** from one continuous `set02` run in the [Seattle Aquarium benthic imagery dataset](https://huggingface.co/datasets/Seattle-Aquarium/Seattle_Aquarium_benthic_imagery), captured at approximately 3-second intervals.
- **A planned 60-second derived clip** from the [Pier 59 downward mock transect and light test](https://drive.google.com/file/d/1aWDrqq5DItRglgswjGO79yGcdP1AyOBX/view), sampled at 2 fps for a denser-overlap alternative. Google Drive quota blocked retention in the initial validation run.

See [docs/data-pilot.md](docs/data-pilot.md) for the selection rationale, exact results, licensing, and limitations. See [docs/pipeline.md](docs/pipeline.md) for the COLMAP-to-Gaussian-splatting boundary and the aquarium-specific technology shortlist.

## Quick start

Python 3.9 or newer and `ffmpeg` are required. On Apple Silicon, Homebrew ffmpeg is sufficient; no CUDA dependency is assumed for preprocessing.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# Download only the selected 59-image Hugging Face sequence.
python scripts/pilot_data.py download-images

# Attempt to fetch and transcode only the selected 60-second Pier 59 interval.
python scripts/pilot_data.py trim-video

# If the clip download succeeded, extract 120 video frames at 2 fps.
python scripts/pilot_data.py extract-video-frames

# Rebuild machine-readable reports and COLMAP-ready image directories.
python scripts/pilot_data.py quality-report --all
python scripts/pilot_data.py prepare-colmap --all
```

To use a non-PATH ffmpeg binary:

```bash
FFMPEG=/path/to/ffmpeg python scripts/pilot_data.py trim-video
```

If Google Drive's public quota blocks automation, download the file in a browser and point the trim command at it. The full source is not copied into the repository and can be deleted after trimming:

```bash
VIDEO_SOURCE="$HOME/Downloads/2022_6_23_downward.mp4" \
  python scripts/pilot_data.py trim-video
```

All commands default to [configs/pilot.json](configs/pilot.json). Run `python scripts/pilot_data.py --help` for overrides. The validated 2026-09-14 run collected the complete still-image pilot; Google Drive blocked completion of the selected video after initial public metadata/sample access and a partial transient transfer. A dedicated `gdown` attempt confirmed the public “too many users” quota. The script deletes partial source files on failure.

## Data policy

`data/raw/`, `data/processed/`, `data/colmap/`, contact sheets, and other generated media are gitignored. Do not commit Seattle Aquarium source media. The Hugging Face still-image dataset is licensed **CC BY-NC 4.0**; attribute Seattle Aquarium Coastal Climate Resilience and preserve the non-commercial restriction. The linked ROV video index does not state that its videos use the same license, so verify permission and intended use with Seattle Aquarium before redistribution or publication.
