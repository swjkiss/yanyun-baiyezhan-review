#!/usr/bin/env python
"""HUD 放大条带生成器：把录像静帧中关键 HUD 区域（计时/比分/鹅血/人墙血量杯/播报）
按相对坐标裁剪并垂直堆叠成「可读竖条」，用于低成本目视读取小字证据。

为什么需要它：
    1440p / 2160p 录像里的 HUD 数字很小，整帧送视觉模型既贵又容易误读。
    本工具把指定区域放大（target_h）后逐帧竖向拼接，左侧标注时间，
    一次 Read 即可追踪整场的比分/击杀/鹅血/墙杯变化。

坐标约定：
    区域用「相对分数」表示 [x_frac, y_frac, w_frac, h_frac]（0~1，相对原图宽高），
    与分辨率无关；不同分辨率/版本只需调整坐标，详见 references/hud-layout.md。

用法:
    # 从 L1 抽帧清单生成全部默认区域条带
    python make_strips.py --manifest frames/L1/L1_manifest.json --out strips

    # 从目录（按文件名排序）生成指定区域
    python make_strips.py --dir frames/L3duel --out strips --regions-json '{"goose": {"box":[0.40,0.015,0.20,0.045],"target_h":200}}'

    # 从自定义区域配置文件（JSON）生成
    python make_strips.py --manifest frames/L1/L1_manifest.json --out strips --regions hud_regions.json

    # 只处理若干定点帧
    python make_strips.py --images a.jpg,b.jpg --out strips
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# 默认 HUD 区域（相对坐标，基于 1280x720 参考系标定，与分辨率无关）。
# 标定来源：《燕云十六声》百业战实测录像；详见 references/hud-layout.md。
# 若你的录像版本布局不同，请用 --regions / --regions-json 覆盖。
# --------------------------------------------------------------------------
DEFAULT_REGIONS: dict = {
    "top_bar":     {"box": [0.234, 0.000, 0.547, 0.056], "target_h": 150, "label": "顶栏(比分/计时)"},
    "hud_full":    {"box": [0.234, 0.000, 0.547, 0.160], "target_h": 300, "label": "顶栏+横幅区(比分/计时/鹅血/墙杯/播报)"},
    "score_ours":  {"box": [0.160, 0.000, 0.280, 0.056], "target_h": 150, "label": "我方比分/击杀"},
    "score_enemy": {"box": [0.545, 0.000, 0.280, 0.056], "target_h": 150, "label": "敌方比分/击杀"},
    "minimap":     {"box": [0.000, 0.000, 0.130, 0.244], "target_h": 340, "label": "左上小地图"},
    "chat_log":    {"box": [0.023, 0.755, 0.345, 0.240], "target_h": 150, "label": "左下聊天/系统播报"},
}

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


def build_strip_page(region: dict, frames: list[tuple[Path, str]], label_w: int = 130) -> Image.Image:
    """生成单页（一组帧）的竖条。frames 已是要画在这一页的所有帧。"""
    box = region["box"]
    target_h = int(region.get("target_h", 150))
    x0, y0, w0, h0 = box
    font = load_font(max(15, int(target_h * 0.12)))

    crops: list[tuple[str, Image.Image]] = []
    for path, tlabel in frames:
        try:
            im = Image.open(path).convert("RGB")
        except Exception:
            continue
        W, H = im.width, im.height
        px, py, pw, ph = (
            max(0, int(x0 * W)), max(0, int(y0 * H)),
            max(1, int(w0 * W)), max(1, int(h0 * H)),
        )
        crop = im.crop((px, py, min(W, px + pw), min(H, py + ph)))
        scale = target_h / max(1, crop.height)
        nw = max(1, int(crop.width * scale))
        crop = crop.resize((nw, target_h), Image.LANCZOS)
        crops.append((tlabel, crop))

    if not crops:
        raise RuntimeError("没有可用帧生成条带")

    cw = max(c.width for _, c in crops)
    gap = 10
    H_total = target_h * len(crops) + gap * (len(crops) + 1)
    W_total = label_w + cw + 20
    sheet = Image.new("RGB", (W_total, H_total), (12, 13, 16))
    draw = ImageDraw.Draw(sheet)
    for i, (tlabel, crop) in enumerate(crops):
        y = gap + i * (target_h + gap)
        draw.text((6, y + target_h // 2 - font.size // 2 - 2), tlabel, font=font, fill=(255, 220, 80))
        sheet.paste(crop, (label_w, y))
    return sheet


def build_strip(region: dict, frames: list[tuple[Path, str]], per_page: int = 0) -> list[Image.Image]:
    """返回若干页 Image。per_page<=0 时返回整列单页。"""
    if per_page and per_page > 0:
        pages: list[Image.Image] = []
        for i in range(0, len(frames), per_page):
            pages.append(build_strip_page(region, frames[i:i + per_page]))
        return pages or [build_strip_page(region, [])]
    return [build_strip_page(region, frames)]


def main() -> int:
    ap = argparse.ArgumentParser(description="HUD 放大条带生成器")
    ap.add_argument("--manifest", default="", help="抽帧清单 JSON（含 frames/t_hms）")
    ap.add_argument("--frames-dir", default="", help="manifest 中相对路径的基准目录")
    ap.add_argument("--dir", default="", help="按文件名排序读取目录下所有图片")
    ap.add_argument("--images", default="", help="逗号分隔的显式图片列表")
    ap.add_argument("--out", required=True, help="输出目录；每区域生成 <name>.jpg")
    ap.add_argument("--regions", default="", help="区域配置文件（JSON）：name -> {box,target_h,label}")
    ap.add_argument("--regions-json", default="", help="内联区域 JSON（覆盖默认）")
    ap.add_argument("--only", default="", help="只生成指定区域（逗号分隔，默认全部）")
    ap.add_argument("--per-page", type=int, default=0, help="每页帧数（>0 时分页，便于逐页阅读小字）")
    args = ap.parse_args()

    if not (args.manifest or args.dir or args.images):
        print("错误：必须提供 --manifest / --dir / --images 之一。", file=sys.stderr)
        return 2

    frames = collect(args)
    if not frames:
        print("错误：没有可用的帧图片。", file=sys.stderr)
        return 2

    # 区域配置优先级：--regions-json > --regions 文件 > 默认
    if args.regions_json:
        regions = json.loads(args.regions_json)
    elif args.regions:
        regions = json.loads(Path(args.regions).read_text(encoding="utf-8"))
    else:
        regions = DEFAULT_REGIONS

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    if only:
        regions = {k: v for k, v in regions.items() if k in only}

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for name, region in regions.items():
        try:
            pages = build_strip(region, frames, per_page=args.per_page)
        except Exception as e:
            print(f"[warn] 区域 {name} 生成失败：{e}", file=sys.stderr)
            continue
        if len(pages) == 1:
            outs = [out_dir / f"{name}.jpg"]
        else:
            outs = [out_dir / f"{name}_p{i + 1}.jpg" for i in range(len(pages))]
        for p_img, out in zip(pages, outs):
            p_img.save(out, quality=90)
            written.append(out)
        sz = " / ".join(f"{p.width}x{p.height}" for p in pages)
        print(f"已写出 {len(outs)} 页 {name}  [{sz}]  帧数={len(frames)}")

    if not written:
        print("错误：所有区域均未生成。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
