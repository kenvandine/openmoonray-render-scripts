# OpenMoonRay Render Scripts

Scripts for rendering animations with [OpenMoonRay](https://openmoonray.org)
using a delta-file approach: a tiny per-frame RDLA override file changes only
the attributes that differ from the base scene, keeping the workflow
non-destructive and fast to iterate.

## Requirements

- `openmoonray.moonray` (snap: `openmoonray`)
- `ffmpeg`
- Python 3.6+

---

## render_orbit.py — Orbiting camera animation

Renders an orbiting camera animation of [`curves.rdla`](curves.rdla). The
camera moves around the scene on a circular path while always pointing at the
scene centre. The orbit can be a full 360° loop or any partial arc.

### Quick start

```bash
python3 render_orbit.py
```

Renders 72 frames (5° steps) and produces `orbit.mp4`.

### How it works

1. **Delta files** — a tiny per-frame RDLA file written to
   `orbit_frames/deltas/frame_NNNN.rdla` overrides only the camera's
   `node_xform` with a new look-at matrix.
2. **Rendering** — each frame is rendered with:
   ```
   openmoonray.moonray -in curves.rdla -in <delta>.rdla -out <frame>.exr …
   ```
3. **Conversion** — EXR frames are converted to PNG via `ffmpeg`.
4. **Assembly** — PNGs are assembled into `orbit.mp4` via `ffmpeg`.

### Options

| Flag | Default | Description |
|---|---|---|
| `--scene` | `curves.rdla` | Input RDLA scene file |
| `--frames` | `72` | Number of frames (72 = 5° steps) |
| `--radius` | `1.5` | Orbit radius |
| `--height` | `0.1` | Camera height above scene centre |
| `--center` | `0,0.1,0` | Scene centre to orbit around |
| `--arc` | `360` | Total arc to sweep in degrees. Values <360 are centred on `--center-angle` |
| `--center-angle` | `0.0` | For a full 360° orbit: starting angle. For a partial arc: midpoint of the sweep |
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

### Examples

```bash
# Preview the camera positions without rendering
python3 render_orbit.py --dry-run

# 120 frames (3° steps) for a smoother full orbit
python3 render_orbit.py --frames 120

# 90° arc centred straight-on: sweeps from -45° to +45°
python3 render_orbit.py --arc 90 --center-angle 0 --frames 36

# Brighten output if frames are too dark
python3 render_orbit.py --exposure 1.5
```

### Output structure

```
orbit_frames/
  deltas/          per-frame camera RDLA override files
  frame_0000.exr
  frame_0000.png
  …
orbit.mp4
```

### Performance notes

Each frame renders in roughly 60–90 seconds at the default resolution.
A single moonray job uses all available CPU cores; use `--parallel` to run
multiple jobs concurrently at the cost of fewer threads per job.

---

## render_turntable.py — Turntable object rotation animation

Renders a 360° turntable animation where the camera stays fixed and the scene
object rotates around the Y axis. Intended for product visualisation — showing
every side of an object in a smooth looping video.

For a full specification including known issues and MoonRay quirks discovered
during development, see [SPEC.md](SPEC.md).

### Quick start

```bash
# 4-frame preview (0°, 90°, 180°, 270°)
python3 render_turntable.py --frames 4 --scene /path/to/scene.rdla

# Full 72-frame smooth 360° animation
python3 render_turntable.py --frames 72 --scene /path/to/scene.rdla
```

### How it works

1. **Scene parsing** — the script reads the RDLA file to find all geometry
   nodes and their existing transforms.
2. **Delta files** — a per-frame RDLA file written to
   `turntable_frames/deltas/frame_NNNN.rdla` overrides `node_xform` on every
   geometry node with `original_xform × R(θ)`.
3. **Rendering / conversion / assembly** — same pipeline as `render_orbit.py`.

### Options

| Flag | Default | Description |
|---|---|---|
| `--scene` | *(coffee maker scene)* | Input RDLA scene file |
| `--frames` | `4` | Number of frames (4 = 90° preview; 72 = 5° smooth) |
| `--arc` | `360.0` | Total arc to sweep in degrees |
| `--rotate-lights` | off | Rotate lights with the object (not recommended — lights become visible in frame near 180°) |
| `--layer-name` | `/scene/layers/Layer1` | Layer node name |
| `--fps` | `24` | Output video framerate |
| `--output-dir` | `turntable_frames` | Directory for frames and delta files |
| `--video` | `turntable.mp4` | Output video filename |
| `--parallel` | `1` | Concurrent moonray processes (default 1 — a single job uses all CPU cores) |
| `--threads-per-render` | `cpu_count // parallel` | moonray `-threads` per process |
| `--exposure` | `0.0` | EXR exposure adjustment |
| `--dry-run` | off | Write delta files only; skip rendering |
| `--no-video` | off | Render frames but skip video assembly |
| `--only-frames` | — | Comma-separated frame indices to render (e.g. `33,34,35`). Implies `--no-video`. |

### Output structure

```
turntable_frames/
  deltas/          per-frame geometry RDLA override files
  frame_0000.exr
  frame_0000.png
  …
turntable.mp4
```
