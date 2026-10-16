#!/usr/bin/env python
"""分层抽帧：把录像按 analysis-framework.md §3 的 L1–L4 策略抽成静帧 + 时间轴清单。

模式:
    uniform  均匀抽帧（L1 概览 / L2 阶段）
    ranges   指定区间密集抽帧（L3 事件窗）
    scene    场景切换检测抽帧（自动定位团战/转场）
    times    定点抽帧（已知时间点取样）

示例:
    # L1 概览：每 12 秒 1 帧
    python extract_frames.py match.mp4 --out frames/L1 --interval 12

    # 只抽下半场
    python extract_frames.py match.mp4 --out frames/L2b --interval 4 --start 0:16:30

    # L3 事件窗：上半场 06:30-06:45 每 0.5 秒 1 帧
    python extract_frames.py match.mp4 --out frames/L3_1 --mode ranges --ranges "0:06:30-0:06:45" --interval 0.5

    # 场景切换
    python extract_frames.py match.mp4 --out frames/scene --mode scene --scene-threshold 0.35

    # 定点
    python extract_frames.py match.mp4 --out frames/pts --mode times --times "0:03:00,0:16:30,0:31:00"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    ensure_dir,
    ffmpeg_probe,
    fmt_clock,
    fmt_time,
    parse_range,
    parse_time,
    run_ffmpeg,
)

PTS_RE = re.compile(r"pts_time:\s*([\d.]+)")


def build_vf(scale: int, extra: str | None = None) -> str:
    parts = []
    if extra:
        parts.append(extra)
    if scale and scale > 0:
        parts.append(f"scale={scale}:-2")
    return ",".join(parts) if parts else "null"


def extract_uniform(
    video: str, out_dir: Path, prefix: str, start: float, end: float | None,
    interval: float, scale: int, quality: int, verbose: bool
) -> list[Path]:
    if interval <= 0:
        raise ValueError("--interval 必须大于 0")
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{prefix}_%06d.jpg")
    args = ["-ss", f"{start:.3f}", "-i", video]
    if end is not None:
        args += ["-t", f"{max(0.0, end - start):.3f}"]
    args += [
        "-vf", build_vf(scale, f"fps=1/{interval}"),
        "-q:v", str(quality),
        "-start_number", "1",
        pattern,
    ]
    res = run_ffmpeg(args, verbose=verbose)
    files = sorted(out_dir.glob(f"{prefix}_*.jpg"))
    if not files:
        sys.stderr.write("[warn] 均匀抽帧未产出任何帧。ffmpeg 输出尾部：\n" + (res.stderr or "")[-800:] + "\n")
    return files


def extract_scene(
    video: str, out_dir: Path, prefix: str, start: float, end: float | None,
    threshold: float, scale: int, quality: int, verbose: bool
) -> tuple[list[Path], list[float]]:
    """返回 (帧文件列表, 对应时间戳列表)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{prefix}_%06d.jpg")
    args = ["-ss", f"{start:.3f}", "-i", video]
    if end is not None:
        args += ["-t", f"{max(0.0, end - start):.3f}"]
    sel = f"select='gt(scene,{threshold})',showinfo"
    args += [
        "-vf", build_vf(scale, sel),
        "-fps_mode", "vfr",
        "-q:v", str(quality),
        "-start_number", "1",
        pattern,
    ]
    res = run_ffmpeg(args, verbose=verbose)
    stamps = [start + float(m) for m in PTS_RE.findall(res.stderr or "")]
    files = sorted(out_dir.glob(f"{prefix}_*.jpg"))
    if not files:
        sys.stderr.write("[warn] 场景检测未产出任何帧，可调低 --scene-threshold。\n")
    if len(stamps) != len(files):
        # 数量不一致时退化为等间隔估算，并标注
        n = len(files)
        stamps = [start + (end - start) * (i / max(1, n - 1)) if end else start for i in range(n)] if n else []
    return files, stamps


def extract_times(
    video: str, out_dir: Path, prefix: str, times: list[float],
    scale: int, quality: int, verbose: bool
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for i, t in enumerate(times, 1):
        out = out_dir / f"{prefix}_{i:06d}.jpg"
        run_ffmpeg(
            ["-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-vf", build_vf(scale),
             "-q:v", str(quality), str(out)],
            verbose=verbose,
        )
        if out.exists():
            files.append(out)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="百业战录像分层抽帧")
    ap.add_argument("video")
    ap.add_argument("--out", default="frames", help="输出目录")
    ap.add_argument("--mode", choices=["uniform", "ranges", "scene", "times"], default="uniform")
    ap.add_argument("--interval", type=float, default=12.0, help="uniform/ranges 模式的采样间隔（秒）")
    ap.add_argument("--ranges", default="", help="ranges 模式区间，逗号分隔，如 '0:06:30-0:06:45,0:16:00-0:16:30'")
    ap.add_argument("--times", default="", help="times 模式时间点，逗号分隔")
    ap.add_argument("--start", default="0", help="起始时间 SS / MM:SS / HH:MM:SS")
    ap.add_argument("--end", default="", help="结束时间，留空表示到片尾")
    ap.add_argument("--scale", type=int, default=1280, help="输出宽度像素，0=保持原尺寸")
    ap.add_argument("--quality", type=int, default=3, help="JPEG 质量 2(最高)-31(最低)")
    ap.add_argument("--scene-threshold", type=float, default=0.35)
    ap.add_argument("--prefix", default="", help="文件名前缀，默认按模式自动生成")
    ap.add_argument("--manifest", default="", help="时间轴清单输出路径（JSON）")
    ap.add_argument("--max-frames", type=int, default=4000, help="安全上限，超过则中止")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    video = str(Path(args.video).resolve())
    if not Path(video).exists():
        print(f"错误：文件不存在 —— {video}", file=sys.stderr)
        return 2

    info = ffmpeg_probe(video)
    dur = float(info.get("duration_sec") or 0.0)
    start = parse_time(args.start)
    end = parse_time(args.end) if args.end else (dur if dur > 0 else None)
    if end is not None and end <= start:
        print(f"错误：结束时间 {fmt_time(end)} 不大于起始时间 {fmt_time(start)}", file=sys.stderr)
        return 2

    out_dir = ensure_dir(args.out)
    prefix = args.prefix or f"{args.mode}"
    entries: list[dict] = []

    if args.mode == "uniform":
        files = extract_uniform(video, out_dir, prefix, start, end, args.interval, args.scale, args.quality, args.verbose)
        entries = [
            {"file": f.name, "t": start + i * args.interval, "t_hms": fmt_time(start + i * args.interval)}
            for i, f in enumerate(files)
        ]
    elif args.mode == "ranges":
        if not args.ranges:
            print("错误：--mode ranges 需要 --ranges", file=sys.stderr)
            return 2
        for ri, raw in enumerate([r for r in args.ranges.split(",") if r.strip()], 1):
            a, b = parse_range(raw)
            sub_prefix = f"{prefix}_r{ri}"
            files = extract_uniform(video, out_dir, sub_prefix, a, b, args.interval, args.scale, args.quality, args.verbose)
            for i, f in enumerate(files):
                t = a + i * args.interval
                entries.append({
                    "file": f.name, "t": t, "t_hms": fmt_time(t),
                    "range": f"{fmt_clock(a)}-{fmt_clock(b)}",
                })
    elif args.mode == "scene":
        files, stamps = extract_scene(video, out_dir, prefix, start, end, args.scene_threshold, args.scale, args.quality, args.verbose)
        entries = [
            {"file": f.name, "t": stamps[i] if i < len(stamps) else None,
             "t_hms": fmt_time(stamps[i]) if i < len(stamps) else None}
            for i, f in enumerate(files)
        ]
    else:  # times
        if not args.times:
            print("错误：--mode times 需要 --times", file=sys.stderr)
            return 2
        pts = [parse_time(x) for x in [t for t in args.times.split(",") if t.strip()]]
        files = extract_times(video, out_dir, prefix, pts, args.scale, args.quality, args.verbose)
        entries = [
            {"file": f.name, "t": pts[i] if i < len(pts) else None,
             "t_hms": fmt_time(pts[i]) if i < len(pts) else None}
            for i, f in enumerate(files)
        ]

    if len(entries) > args.max_frames:
        print(f"错误：产出帧数 {len(entries)} 超过上限 {args.max_frames}，请收紧参数。", file=sys.stderr)
        return 3

    manifest = {
        "source": video,
        "source_duration_sec": dur or None,
        "mode": args.mode,
        "interval": args.interval if args.mode in ("uniform", "ranges") else None,
        "start": start,
        "end": end,
        "scale": args.scale,
        "count": len(entries),
        "frames": entries,
    }
    mpath = Path(args.manifest) if args.manifest else (out_dir / f"{prefix}_manifest.json")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"模式={args.mode}  产出帧数={len(entries)}  输出目录={out_dir}")
    print(f"时间轴清单={mpath}")
    if entries:
        print(f"首帧 {entries[0]['file']} @ {entries[0]['t_hms']} ｜ 末帧 {entries[-1]['file']} @ {entries[-1]['t_hms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
