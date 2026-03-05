# Orbiting Camera Animation — curves.rdla

Renders a full 360° orbit animation of [`curves.rdla`](curves.rdla) using
[OpenMoonRay](https://openmoonray.org), then assembles the frames into a video.

## Requirements

- `openmoonray.moonray` (snap: `openmoonray`)
- `ffmpeg`
- Python 3.6+

## Quick start

```bash
python3 render_orbit.py
```

This renders 72 frames (5° steps) in parallel and produces `orbit.mp4`.

## How it works

1. **Delta files** — a tiny per-frame RDLA file is written to
   `orbit_frames/deltas/frame_NNNN.rdla` that overrides only the
   `node_xform` of the scene camera with a new look-at matrix.
2. **Rendering** — each frame is rendered with:
   ```
   openmoonray.moonray -in curves.rdla -in <delta>.rdla -out <frame>.exr …
   ```
3. **Conversion** — EXR frames are converted to PNG via `ffmpeg`.
4. **Assembly** — PNGs are assembled into `orbit.mp4` via `ffmpeg`.

## Options

| Flag | Default | Description |
|---|---|---|
| `--scene` | `curves.rdla` | Input RDLA scene file |
| `--frames` | `72` | Number of frames (72 = 5° steps) |
| `--radius` | `1.5` | Orbit radius |
| `--height` | `0.1` | Camera height above scene centre |
| `--center` | `0,0.2,0` | Scene centre to orbit around |
| `--start-angle` | `0.0` | Starting angle in degrees |
| `--camera-name` | `/scene/cameras/PerspectiveCamera_1` | Camera node in the scene |
| `--layer-name` | `/scene/layers/Layer1` | Layer node in the scene |
| `--fps` | `24` | Output video framerate |
| `--output-dir` | `orbit_frames` | Directory for frames and delta files |
| `--video` | `orbit.mp4` | Output video filename |
| `--parallel` | `cpu_count // 4` | Concurrent moonray processes |
| `--threads-per-render` | `cpu_count // parallel` | moonray `-threads` per process |
| `--exposure` | `0.0` | EXR exposure adjustment for PNG conversion |
| `--dry-run` | off | Write delta files only; skip rendering |
| `--no-video` | off | Render frames but skip video assembly |

## Examples

```bash
# Preview the camera positions without rendering
python3 render_orbit.py --dry-run

# Faster render on a 16-core machine: 4 parallel renders × 4 threads each
python3 render_orbit.py --parallel 4 --threads-per-render 4

# Wider orbit from above, rendered at higher quality
python3 render_orbit.py --radius 2.5 --height 1.2

# Render frames only, assemble video later
python3 render_orbit.py --no-video
ffmpeg -framerate 24 -i orbit_frames/frame_%04d.png -c:v libx264 -pix_fmt yuv420p orbit.mp4

# 120 frames (3° steps) for a smoother animation
python3 render_orbit.py --frames 120

# Brighten output if frames are too dark
python3 render_orbit.py --exposure 1.5
```

## Output structure

```
orbit_frames/
  deltas/          per-frame camera RDLA override files
  frame_0000.exr
  frame_0000.png
  …
  frame_0071.exr
  frame_0071.png
orbit.mp4
```

## Performance notes

Each frame renders in roughly 60–90 seconds at the default 800×1000 resolution.
Tune `--parallel` and `--threads-per-render` so that their product does not
exceed the number of logical CPU cores on your machine.

| Cores | Suggested flags |
|---|---|
| 8 | `--parallel 2 --threads-per-render 4` |
| 16 | `--parallel 4 --threads-per-render 4` |
| 32 | `--parallel 8 --threads-per-render 4` |
