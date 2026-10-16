#!/usr/bin/env python
"""环境自检：确认抽帧与 PDF 生成所需的全部依赖。

用法:
    python check_env.py [--json]

退出码 0 表示关键依赖齐备；1 表示存在阻塞项。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_browser, find_ffmpeg  # noqa: E402


def check() -> dict:
    r: dict = {"python": sys.version.split()[0], "items": [], "blockers": [], "warnings": []}

    def add(name: str, ok: bool, detail: str, level: str = "blocker"):
        r["items"].append({"name": name, "ok": ok, "detail": detail, "level": level})
        if not ok:
            (r["blockers"] if level == "blocker" else r["warnings"]).append(f"{name}: {detail}")

    # --- Python 包 ---
    try:
        import PIL  # noqa: F401

        add("pillow", True, f"Pillow {PIL.__version__}")
    except Exception as e:
        add("pillow", False, f"缺少 Pillow（pip install pillow）: {e}")

    try:
        try:
            import pymupdf as _mupdf
        except ImportError:
            import fitz as _mupdf  # 旧版 PyMuPDF

        ver = getattr(_mupdf, "VersionBind", None) or getattr(_mupdf, "__version__", "unknown")
        add("pymupdf", True, f"PyMuPDF {ver}")
    except Exception as e:
        add("pymupdf", False, f"缺少 PyMuPDF（pip install pymupdf）: {e}", level="warning")

    try:
        import markdown  # noqa: F401

        add("markdown", True, f"markdown {markdown.__version__}")
    except Exception as e:
        add("markdown", False, f"缺少 markdown（pip install markdown）: {e}")

    # --- ffmpeg ---
    try:
        exe = find_ffmpeg()
        add("ffmpeg", True, exe)
    except Exception as e:
        add("ffmpeg", False, str(e).splitlines()[0])

    # --- 浏览器（PDF 主通道） ---
    b = find_browser()
    add("browser(chromium)", bool(b), b or "未找到 Edge/Chrome，将降级为 PyMuPDF Story 排版（样式受限）", level="warning")

    # --- 中文字体 ---
    font_candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    found = [f for f in font_candidates if Path(f).exists()]
    add("cjk-font", bool(found), ", ".join(found) if found else "未找到中文字体，PDF 可能显示为方块", level="warning")

    r["ok"] = not r["blockers"]
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="百业战复盘环境自检")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    r = check()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"Python: {r['python']}")
        for it in r["items"]:
            mark = "OK  " if it["ok"] else ("FAIL" if it["level"] == "blocker" else "WARN")
            print(f"[{mark}] {it['name']:<20} {it['detail']}")
        print()
        if r["blockers"]:
            print("阻塞项：")
            for b in r["blockers"]:
                print("  -", b)
        else:
            print("关键依赖齐备，可以开始复盘流程。")
        if r["warnings"]:
            print("警告（可降级运行）：")
            for w in r["warnings"]:
                print("  -", w)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
