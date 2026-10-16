#!/usr/bin/env python
"""生成帧拼图（contact sheet）：把抽帧结果压成可直接目视浏览的网格图。

用法:
    # 从抽帧清单生成（自动带时间戳标签）
    python make_contact_sheet.py --manifest frames/L1/L1_manifest.json --out sheets/L1.jpg

    # 从目录生成
    python make_contact_sheet.py --dir frames/L2 --out sheets/L2.jpg --cols 4 --per-page 12

    # 指定图片列表
    python make_contact_sheet.py --images a.jpg,b.jpg,c.jpg --out sheets/x.jpg
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return ImageFont.load_default()


def collect(args) -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    if args.manifest:
        data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        base = Path(data.get("frames_dir") or Path(args.manifest).parent)
        if args.frames_dir:
            base = Path(args.frames_dir)
        for fr in data.get("frames", []):
            p = Path(fr["file"])
            if not p.is_absolute():
                p = base / p
            label = fr.get("t_hms") or fr.get("file", "")
            if fr.get("range"):
                label = f"{label} [{fr['range']}]"
            items.append((p, label))
    elif args.dir:
        d = Path(args.dir)
        for p in sorted(list(d.glob("*.jpg")) + list(d.glob("*.png"))):
            items.append((p, p.stem))
    elif args.images:
        for raw in args.images.split(","):
            p = Path(raw.strip())
            items.append((p, p.stem))
    return [(p, lb) for p, lb in items if p.exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成帧拼图")
    ap.add_argument("--manifest", default="")
    ap.add_argument("--frames-dir", default="", help="manifest 中相对路径的基准目录")
    ap.add_argument("--dir", default="")
    ap.add_argument("--images", default="")
    ap.add_argument("--out", required=True, help="输出图片路径；多页时自动加 _pN 后缀")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--per-page", type=int, default=12)
    ap.add_argument("--thumb-width", type=int, default=480)
    ap.add_argument("--label-height", type=int, default=34)
    ap.add_argument("--gap", type=int, default=8)
    ap.add_argument("--bg", default="#111418")
    ap.add_argument("--fg", default="#f2f4f6")
    ap.add_argument("--no-label", action="store_true")
    args = ap.parse_args()

    items = collect(args)
    if not items:
        print("错误：没有可用的帧图片。", file=sys.stderr)
        return 2

    cols = max(1, args.cols)
    per_page = max(1, args.per_page)
    label_h = 0 if args.no_label else args.label_height
    font = load_font(max(14, int(args.label_height * 0.55)))

    # 以第一张图推算缩略图高度
    with Image.open(items[0][0]) as im0:
        ratio = im0.height / im0.width if im0.width else 0.5625
    tw = args.thumb_width
    th = int(tw * ratio)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pages = math.ceil(len(items) / per_page)
    written: list[Path] = []

    for pi in range(pages):
        chunk = items[pi * per_page:(pi + 1) * per_page]
        rows = math.ceil(len(chunk) / cols)
        W = cols * tw + (cols + 1) * args.gap
        H = rows * (th + label_h) + (rows + 1) * args.gap
        sheet = Image.new("RGB", (W, H), args.bg)
        draw = ImageDraw.Draw(sheet)

        for i, (path, label) in enumerate(chunk):
            r, c = divmod(i, cols)
            x = args.gap + c * (tw + args.gap)
            y = args.gap + r * (th + label_h + args.gap)
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    scale = min(tw / im.width, th / im.height)
                    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
                    im = im.resize((nw, nh), Image.LANCZOS)
                    sheet.paste(im, (x + (tw - nw) // 2, y + (th - nh) // 2))
            except Exception as e:
                draw.rectangle([x, y, x + tw, y + th], outline="#7a1f1f", width=2)
                draw.text((x + 8, y + 8), f"读取失败: {e}", font=font, fill="#ff9a9a")
            if label_h:
                draw.rectangle([x, y + th, x + tw, y + th + label_h], fill="#1b2027")
                draw.text((x + 10, y + th + (label_h - font.size) // 2 - 1), str(label), font=font, fill=args.fg)

        if pages == 1:
            page_path = out
        else:
            page_path = out.with_name(f"{out.stem}_p{pi + 1}{out.suffix}")
        sheet.save(page_path, quality=88)
        written.append(page_path)

    print(f"帧数={len(items)}  分页={pages}  列数={cols}  每页={per_page}")
    for w in written:
        print("已写出:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
