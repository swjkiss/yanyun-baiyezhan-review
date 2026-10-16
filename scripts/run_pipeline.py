#!/usr/bin/env python
"""百业战复盘一键编排：probe → L1/L2/scene 抽帧 → HUD 条带。

把「机械准备阶段」压缩成一条命令，产出结构化摘要与下一步提示；
随后的「读条带 → 建时间轴 → 三维度分析 → 写报告」由智能体按 SKILL.md 阶段 3–5 完成。

用法:
    python run_pipeline.py "D:\\game\\yysls\\百业战\\match.mp4" --work work
    python run_pipeline.py match.mp4 --work work --l1 20 --l2 5 --skip-scene

产出:
    work/probe.json              媒体信息与建议参数
    work/frames/L1|L2|scene/     分层抽帧 + manifest
    work/strips/                 HUD 放大条带（hud_full / chat_log / top_bar ...）
    work/PIPELINE_DIGEST.json    供智能体直接读取的摘要

退出码 0 = 全部成功；非 0 = 某阶段失败（stderr 有原因，摘要仍会写出已完成部分）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PY = sys.executable


def run(cmd: list[str], timeout: int | None = None) -> tuple[int, str]:
    """跑子脚本，返回 (returncode, 合并输出尾部)。"""
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        out = ((res.stdout or "") + (res.stderr or "")).strip()
        return res.returncode, out[-1500:]
    except subprocess.TimeoutExpired:
        return 124, f"[timeout] 超过 {timeout}s，被中止。长视频请调大 --timeout 或手动分步执行。"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="百业战复盘一键编排（机械准备阶段）")
    ap.add_argument("video")
    ap.add_argument("--work", default="work", help="工作目录（默认 ./work）")
    ap.add_argument("--l1", type=float, default=0, help="L1 间隔秒（0=按探针建议）")
    ap.add_argument("--l2", type=float, default=0, help="L2 间隔秒（0=按探针建议）")
    ap.add_argument("--scale", type=int, default=1280, help="抽帧输出宽度")
    ap.add_argument("--scene-threshold", type=float, default=0.3)
    ap.add_argument("--skip-scene", action="store_true", help="跳过场景切点检测（省时）")
    ap.add_argument("--strips", default="hud_full,chat_log,top_bar", help="条带区域列表")
    ap.add_argument("--per-page", type=int, default=13, help="条带每页帧数")
    ap.add_argument("--timeout", type=int, default=600, help="单步超时秒")
    args = ap.parse_args()

    video = str(Path(args.video).resolve())
    if not Path(video).exists():
        print(f"错误：录像不存在 —— {video}", file=sys.stderr)
        return 2

    work = Path(args.work).resolve()
    (work / "frames").mkdir(parents=True, exist_ok=True)
    digest: dict = {"video": video, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "steps": {}, "next_steps": []}

    def step(name: str, cmd: list[str], timeout: int) -> tuple[bool, str]:
        t0 = time.time()
        code, out = run(cmd, timeout=timeout)
        digest["steps"][name] = {"cmd": " ".join(cmd[1:]), "code": code,
                                 "sec": round(time.time() - t0, 1), "tail": out}
        print(f"\n===== [{name}] 退出码 {code}  耗时 {digest['steps'][name]['sec']}s =====")
        print(out or "(无输出)")
        return code == 0, out

    # ---- 阶段 1：探针 ----
    ok1, out1 = step("probe",
                     [PY, str(SCRIPTS / "probe_video.py"), video, "--json", str(work / "probe.json")],
                     timeout=60)
    dur = fps = None
    if ok1:
        try:
            info = json.loads((work / "probe.json").read_text(encoding="utf-8"))
            dur = float(info.get("duration_sec") or 0)
            fps = info.get("fps")
            digest["media"] = {k: info.get(k) for k in ("duration_sec", "duration_hms", "width", "height", "fps", "codec")}
            sug = info.get("suggestion", {})
            digest["suggestion"] = sug
        except Exception as e:
            digest["steps"]["probe"]["tail"] += f"\n[warn] 解析 probe.json 失败: {e}"
    if not dur:
        digest["next_steps"].append("探针未读到时长：确认文件为有效视频后再重试。")

    # ---- 阶段 2：分层抽帧 ----
    l1 = args.l1 or 10
    l2 = args.l2 or 4
    ok2, _ = step("L1", [PY, str(SCRIPTS / "extract_frames.py"), video,
                         "--out", str(work / "frames" / "L1"), "--interval", str(l1),
                         "--scale", str(args.scale), "--prefix", "L1"], timeout=args.timeout)
    ok3, _ = step("L2", [PY, str(SCRIPTS / "extract_frames.py"), video,
                         "--out", str(work / "frames" / "L2"), "--interval", str(l2),
                         "--scale", str(args.scale), "--prefix", "L2"], timeout=args.timeout)
    ok4 = True
    if not args.skip_scene:
        ok4, _ = step("scene", [PY, str(SCRIPTS / "extract_frames.py"), video,
                                "--out", str(work / "frames" / "scene"), "--mode", "scene",
                                "--scene-threshold", str(args.scene_threshold),
                                "--scale", str(args.scale), "--prefix", "SC"], timeout=args.timeout)

    # ---- 阶段 3：HUD 条带 ----
    ok5, _ = step("strips", [PY, str(SCRIPTS / "make_strips.py"),
                             "--manifest", str(work / "frames" / "L1" / "L1_manifest.json"),
                             "--out", str(work / "strips"),
                             "--only", args.strips, "--per-page", str(args.per_page)],
                  timeout=args.timeout)

    # ---- 摘要 ----
    digest["ok"] = {"probe": ok1, "L1": ok2, "L2": ok3, "scene": ok4, "strips": ok5}
    if dur:
        digest["next_steps"] += [
            f"1) Read work/strips/hud_full_*.jpg 与 chat_log_*.jpg，建立比分/击杀/鹅血/横幅时间线"
            f"（分段页数见 strips 目录）。",
            "2) 发现可疑段落后，用 extract_frames.py --mode ranges 对事件窗做 L3 精查。",
            "3) 按 SKILL.md 阶段 3–5 建时间轴 → 三维度分析 → 填 assets/report_template.md → build_report.py 渲染 PDF。",
        ]
    if dur and dur < 600:
        digest["next_steps"].insert(0,
            "注意：时长 <10 分钟，疑似剪辑/集锦 —— 按 highlight 模式处理，禁止输出全场节奏结论。")

    (work / "PIPELINE_DIGEST.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 摘要 =====")
    print(json.dumps({k: digest[k] for k in ("ok", "media", "next_steps") if k in digest},
                     ensure_ascii=False, indent=2))
    print(f"完整摘要：{work / 'PIPELINE_DIGEST.json'}")
    return 0 if all(digest["ok"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
