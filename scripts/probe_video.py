#!/usr/bin/env python
"""媒体探针：读取录像时长/分辨率/帧率/编码，并给出建议抽帧参数。

用法:
    python probe_video.py match.mp4
    python probe_video.py match.mp4 --json probe.json

输出 JSON（stdout 或 --json 指定文件）：
    {duration_sec, width, height, fps, codec, duration_hms, suggestion:{...}}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ffmpeg_probe, fmt_time  # noqa: E402


def suggest(info: dict) -> dict:
    """根据时长给出分层抽帧建议（对应 analysis-framework.md §3）。"""
    dur = float(info.get("duration_sec") or 0)
    fps = float(info.get("fps") or 30)
    s = {
        "L1_overview_interval": 12,
        "L2_stage_interval": 4,
        "L3_event_interval": 0.5,
        "L3_event_window": 5,
        "L4_precise_interval": 0.1,
        "half_split_sec": round(dur / 2, 2),
    }
    if dur:
        s["L1_est_frames"] = int(dur / s["L1_overview_interval"]) + 1
        s["L2_est_frames"] = int(dur / s["L2_stage_interval"]) + 1
    s["total_frames_est"] = int(dur * fps) if dur else None
    s["note"] = (
        "half_split_sec 为默认的上下半场等分切分点（兜底方案）。"
        "若能识别游戏内对局计时器或中场事件，应改用事件切分，"
        "详见 references/analysis-framework.md §2。"
    )
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="百业战录像媒体探针")
    ap.add_argument("video", help="录像文件路径")
    ap.add_argument("--json", dest="json_out", help="把结果写入指定 JSON 文件")
    args = ap.parse_args()

    p = Path(args.video)
    if not p.exists():
        print(f"错误：文件不存在 —— {args.video}", file=sys.stderr)
        return 2

    info = ffmpeg_probe(str(p))
    if "duration_sec" in info:
        info["duration_hms"] = fmt_time(info["duration_sec"])
    info["suggestion"] = suggest(info)

    text = json.dumps(info, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
        print(f"已写出：{args.json_out}")
    print(text)
    return 0 if "duration_sec" in info else 1


if __name__ == "__main__":
    raise SystemExit(main())
