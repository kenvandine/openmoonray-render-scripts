#!/usr/bin/env python3
# Copyright 2025 Ken VanDine
# SPDX-License-Identifier: Apache-2.0
"""
render_orbit.py — Render an orbiting camera animation using OpenMoonRay.

Usage:
    python3 render_orbit.py [options]

Example:
    python3 render_orbit.py --frames 72 --radius 1.5 --height 0.4 --parallel 4
    python3 render_orbit.py --dry-run   # write delta files only, no rendering
"""

import argparse
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


# ---------------------------------------------------------------------------
# Camera math
# ---------------------------------------------------------------------------

def lookat_mat4(pos, target, world_up=(0.0, 1.0, 0.0)):
    """Compute a row-major 4×4 camera world-transform for MoonRay.

    MoonRay cameras look along their local -Z axis, so row 2 of the matrix
    stores the 'backward' direction (+Z local = −forward in world space).

    Returns a flat 16-element tuple of floats ordered row-by-row:
        row0: right,      row1: cam_up,
        row2: -forward,   row3: translation (tx, ty, tz, 1)
    """
    px, py, pz = pos
    tx, ty, tz = target
    ux, uy, uz = world_up

    # Forward (look direction)
    fx = tx - px;  fy = ty - py;  fz = tz - pz
    fl = math.sqrt(fx*fx + fy*fy + fz*fz)
    if fl < 1e-10:
        raise ValueError(f"Camera position and target are the same: {pos}")
    fx /= fl;  fy /= fl;  fz /= fl

    # Right = forward × world_up
    rx = fy*uz - fz*uy
    ry = fz*ux - fx*uz
    rz = fx*uy - fy*ux
    rl = math.sqrt(rx*rx + ry*ry + rz*rz)
    if rl < 1e-10:
        raise ValueError(f"Forward vector is parallel to world_up at position {pos}")
    rx /= rl;  ry /= rl;  rz /= rl

    # Camera up = right × forward  (orthogonalised)
    cux = ry*fz - rz*fy
    cuy = rz*fx - rx*fz
    cuz = rx*fy - ry*fx

    return (
        rx,   ry,   rz,   0.0,   # row 0: right
        cux,  cuy,  cuz,  0.0,   # row 1: cam_up
        -fx,  -fy,  -fz,  0.0,   # row 2: -forward (backward)
        px,   py,   pz,   1.0,   # row 3: translation
    )


def mat4_str(m):
    """Format a 16-element tuple as a MoonRay Mat4 literal."""
    vals = ", ".join(f"{v!r}" for v in m)
    return f"Mat4({vals})"


# ---------------------------------------------------------------------------
# RDLA delta file
# ---------------------------------------------------------------------------

def write_camera_delta(path, camera_name, mat):
    """Write a per-frame RDLA file that overrides only node_xform."""
    m = mat4_str(mat)
    with open(path, "w") as f:
        f.write(f'PerspectiveCamera("{camera_name}") {{\n')
        f.write(f'    ["node_xform"] = blur({m}, {m}),\n')
        f.write("}\n")


# ---------------------------------------------------------------------------
# Orbit positions
# ---------------------------------------------------------------------------

def orbit_positions(num_frames, radius, height, center,
                    center_angle_deg=0.0, arc_deg=360.0):
    """Return list of (frame_index, angle_deg, world_pos) for each frame.

    For a full 360° arc the last frame is NOT the same as the first so that
    the sequence loops cleanly.  For a partial arc both endpoints are included.
    """
    cx, cy, cz = center
    # For a full orbit, center_angle is the start position.
    # For a partial arc, center_angle is the midpoint (sweep ±arc/2).
    first = center_angle_deg if arc_deg >= 360.0 else center_angle_deg - arc_deg / 2.0
    # Full loop: divide by N (endpoint == startpoint, so skip it).
    # Partial arc: divide by N-1 (include both endpoints).
    divisor = num_frames if arc_deg >= 360.0 else max(1, num_frames - 1)
    result = []
    for i in range(num_frames):
        angle = math.radians(first + arc_deg * i / divisor)
        x = cx + radius * math.cos(angle)
        y = cy + height
        z = cz + radius * math.sin(angle)
        result.append((i, math.degrees(angle) % 360.0, (x, y, z)))
    return result


# ---------------------------------------------------------------------------
# Rendering and conversion helpers
# ---------------------------------------------------------------------------

def render_frame(scene_path, delta_path, exr_path, layer_name,
                 threads_per_render):
    """Run one moonray render. Returns (returncode, combined stderr)."""
    cmd = [
        "openmoonray.moonray",
        "-in", str(scene_path),
        "-in", str(delta_path),
        "-out", str(exr_path),
    ]
    if layer_name:
        cmd += ["-layer", layer_name]
    if threads_per_render:
        cmd += ["-threads", str(threads_per_render)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stderr


def convert_exr_to_png(exr_path, png_path, exposure=0.0):
    """Convert a single EXR to PNG via ffmpeg. Returns (returncode, stderr)."""
    filters = f"exposure={exposure}" if exposure != 0.0 else "format=rgb24"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(exr_path),
        "-vf", filters,
        str(png_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stderr


def assemble_video(frames_dir, video_path, fps, frame_pattern="frame_%04d.png"):
    """Assemble sequential PNG frames into an MP4 video via ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / frame_pattern),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        str(video_path),
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cpu_count = os.cpu_count() or 4
    default_parallel = max(1, min(4, cpu_count // 4))

    parser = argparse.ArgumentParser(
        description="Render an orbiting camera animation using OpenMoonRay.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--scene", default="curves.rdla",
                        help="Input RDLA scene file")
    parser.add_argument("--frames", type=int, default=72,
                        help="Number of frames (72 = 5° steps for full 360°)")
    parser.add_argument("--radius", type=float, default=1.5,
                        help="Orbit radius")
    parser.add_argument("--height", type=float, default=0.1,
                        help="Camera height above scene center")
    parser.add_argument("--center", default="0,0.1,0",
                        help="Scene center to orbit around (x,y,z)")
    parser.add_argument("--arc", type=float, default=360.0,
                        help="Total arc to sweep in degrees (default 360). "
                             "Values <360 are centred on --center-angle, so "
                             "--arc 90 spans 45° left to 45° right of center.")
    parser.add_argument("--center-angle", type=float, default=0.0,
                        help="Centre angle of the arc in degrees (default 0)")
    parser.add_argument("--camera-name",
                        default="/scene/cameras/PerspectiveCamera_1",
                        help="Camera node name in the RDLA scene")
    parser.add_argument("--layer-name", default="/scene/layers/Layer1",
                        help="Layer node name (empty string to omit -layer flag)")
    parser.add_argument("--fps", type=int, default=24,
                        help="Output video framerate")
    parser.add_argument("--output-dir", default="orbit_frames",
                        help="Directory for rendered frames and delta files")
    parser.add_argument("--video", default="orbit.mp4",
                        help="Output video filename")
    parser.add_argument("--parallel", type=int, default=default_parallel,
                        help="Number of concurrent moonray render processes")
    parser.add_argument("--threads-per-render", type=int, default=None,
                        help="moonray -threads value per process "
                             "(default: cpu_count // parallel)")
    parser.add_argument("--exposure", type=float, default=0.0,
                        help="EXR exposure adjustment for PNG conversion")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write delta files only; skip rendering and video")
    parser.add_argument("--no-video", action="store_true",
                        help="Render frames but skip video assembly")
    args = parser.parse_args()

    # --- Resolve scene path (check cwd and script dir) ---------------------
    scene_path = Path(args.scene)
    if not scene_path.is_absolute():
        # Try relative to cwd first, then relative to this script
        script_dir = Path(__file__).parent
        if not scene_path.exists() and (script_dir / scene_path).exists():
            scene_path = script_dir / scene_path
    scene_path = scene_path.resolve()
    if not scene_path.exists():
        sys.exit(f"Error: scene file not found: {args.scene}")

    # --- Parse center ------------------------------------------------------
    try:
        center = tuple(float(v) for v in args.center.split(","))
        assert len(center) == 3
    except Exception:
        sys.exit(f"Error: --center must be 'x,y,z', got: {args.center!r}")

    # --- Directories -------------------------------------------------------
    output_dir = Path(args.output_dir)
    deltas_dir = output_dir / "deltas"
    output_dir.mkdir(parents=True, exist_ok=True)
    deltas_dir.mkdir(parents=True, exist_ok=True)

    # --- Threads -----------------------------------------------------------
    threads_per_render = args.threads_per_render
    if threads_per_render is None:
        threads_per_render = max(1, cpu_count // max(1, args.parallel))

    layer_name = args.layer_name if args.layer_name else None

    print(f"Scene:              {scene_path}")
    arc = args.arc
    step = arc / args.frames if arc >= 360 else arc / max(1, args.frames - 1)
    arc_desc = (f"{arc:.1f}° arc centred on {args.center_angle:.1f}°  "
                f"({step:.1f}° steps)")
    print(f"Frames:             {args.frames} — {arc_desc}")
    print(f"Orbit radius:       {args.radius}  height: {args.height}")
    print(f"Scene center:       {center}")
    print(f"Camera node:        {args.camera_name}")
    print(f"Layer:              {layer_name or '(none)'}")
    print(f"Output directory:   {output_dir.resolve()}")
    print(f"Parallel renders:   {args.parallel} × {threads_per_render} threads each")
    print(f"Video:              {args.video} @ {args.fps} fps")
    if args.dry_run:
        print("Mode:               DRY RUN (delta files only)")
    print()

    # --- Generate delta files ----------------------------------------------
    positions = orbit_positions(
        args.frames, args.radius, args.height, center,
        args.center_angle, args.arc,
    )
    jobs = []  # (frame_idx, delta_path, exr_path, png_path, angle_deg)
    for frame_idx, angle_deg, cam_pos in positions:
        try:
            mat = lookat_mat4(cam_pos, center)
        except ValueError as e:
            sys.exit(f"Error computing camera for frame {frame_idx}: {e}")
        delta_path = deltas_dir / f"frame_{frame_idx:04d}.rdla"
        exr_path   = output_dir / f"frame_{frame_idx:04d}.exr"
        png_path   = output_dir / f"frame_{frame_idx:04d}.png"
        write_camera_delta(delta_path, args.camera_name, mat)
        jobs.append((frame_idx, delta_path, exr_path, png_path, angle_deg))

    print(f"Wrote {len(jobs)} camera delta files → {deltas_dir}/")

    if args.dry_run:
        print("\nDry run complete. Sample delta (frame 0000):")
        print(open(deltas_dir / "frame_0000.rdla").read())
        return

    # --- Render frames in parallel -----------------------------------------
    print(f"\nRendering {args.frames} frames with {args.parallel} worker(s)…")
    failed_renders = set()

    def _render_job(job):
        idx, delta_path, exr_path, png_path, angle_deg = job
        rc, stderr = render_frame(
            scene_path, delta_path, exr_path,
            layer_name, threads_per_render,
        )
        return idx, rc, stderr, angle_deg

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(_render_job, job): job[0] for job in jobs}
        for future in as_completed(futures):
            idx, rc, stderr, angle_deg = future.result()
            status = "OK" if rc == 0 else f"FAILED (rc={rc})"
            print(f"  frame {idx:04d}  {angle_deg:6.1f}°  {status}")
            if rc != 0:
                failed_renders.add(idx)
                if stderr:
                    print(f"    {stderr[:300].rstrip()}")

    if failed_renders:
        print(f"\n⚠  {len(failed_renders)} frame(s) failed: "
              f"{sorted(failed_renders)}")
    else:
        print(f"\n✓  All {args.frames} frames rendered.")

    if args.no_video:
        print("Skipping video assembly (--no-video).")
        return

    # --- Convert EXR → PNG -------------------------------------------------
    successful_jobs = [j for j in jobs if j[0] not in failed_renders]
    print(f"\nConverting {len(successful_jobs)} EXR → PNG…")
    failed_png = set()

    def _convert_job(job):
        idx, _, exr_path, png_path, _ = job
        rc, stderr = convert_exr_to_png(exr_path, png_path, args.exposure)
        return idx, rc, stderr

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(_convert_job, job): job[0]
                   for job in successful_jobs}
        for future in as_completed(futures):
            idx, rc, stderr = future.result()
            if rc != 0:
                failed_png.add(idx)
                print(f"  frame {idx:04d} PNG conversion failed: "
                      f"{stderr[:200].rstrip()}")

    if failed_png:
        print(f"⚠  PNG conversion failed for {len(failed_png)} frame(s): "
              f"{sorted(failed_png)}")

    # --- Assemble video ----------------------------------------------------
    video_path = Path(args.video)
    print(f"\nAssembling video: {video_path}")
    try:
        assemble_video(output_dir, video_path, args.fps)
        print(f"✓  Video saved to: {video_path.resolve()}")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Error assembling video: {e}")


if __name__ == "__main__":
    main()
