#!/usr/bin/env python
"""把复盘 Markdown 渲染为带封面、目录、页眉页脚与书签的 PDF。

三级降级：
    1) Chromium/Edge headless --print-to-pdf（推荐，排版最完整）
    2) PyMuPDF Story（无浏览器时的离线排版，样式受限）
    3) 报错退出（绝不产出半成品 PDF）

用法:
    python build_report.py report.md --out report.pdf
    python build_report.py report.md --out report.pdf --title "百业战复盘" --no-page-number
"""
from __future__ import annotations

import argparse
import html as html_mod
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_browser  # noqa: E402

COVER_RE = re.compile(r"<!--\s*COVER(.*?)-->", re.S | re.I)
SEV_RE = re.compile(r"\*\*\s*([SABCsabc])\s*级\s*\*\*")
PRI_RE = re.compile(r"\*\*\s*(P[012])\s*\*\*")
BLOCKQUOTE_RE = re.compile(r"<blockquote>(.*?)</blockquote>", re.S | re.I)
SEV_IN_BQ_RE = re.compile(r"([SABC])\s*级")
H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S | re.I)
H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S | re.I)
IMG_SRC_RE = re.compile(r'(<img[^>]+src=")([^"]+)(")', re.I)
TOC_SENTINEL = "ZZTOCENDMARKER"
MD_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$")


def _fitz():
    """兼容 PyMuPDF 的新旧导入名。"""
    try:
        import pymupdf  # >= 1.24
        return pymupdf
    except ImportError:
        import fitz  # 旧版
        return fitz


def extract_md_headings(md_text: str) -> list[tuple[int, str]]:
    """从 Markdown 抽取 h2/h3 标题（跳过围栏代码块），用于生成 PDF 书签。"""
    out: list[tuple[int, str]] = []
    in_fence = False
    for line in md_text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = MD_HEADING_RE.match(line)
        if m:
            title = strip_tags(m.group(2)).strip()
            if title:
                out.append((len(m.group(1)), title))
    return out


# --------------------------------------------------------------------------
# 预处理
# --------------------------------------------------------------------------

def parse_cover(md_text: str) -> dict:
    m = COVER_RE.search(md_text)
    cover = {}
    if m:
        for line in m.group(1).strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                cover[k.strip().lower()] = v.strip()
    return cover


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def absolutize_images(html: str, base_dir: Path) -> str:
    def repl(m: re.Match) -> str:
        src = m.group(2)
        if re.match(r"^(https?:|file:|data:)", src, re.I):
            return m.group(0)
        p = (base_dir / src).resolve()
        return f"{m.group(1)}{p.as_uri()}{m.group(3)}" if p.exists() else m.group(0)

    return IMG_SRC_RE.sub(repl, html)


def decorate(html: str) -> str:
    """HTML 阶段兜底：处理已被 Markdown 转成 <strong> 的定级/优先级标记。"""
    html = re.sub(
        r"<strong>\s*([SABCsabc])\s*级\s*</strong>",
        lambda m: f'<span class="sev {m.group(1).lower()}">{m.group(1).upper()} 级</span>',
        html,
    )
    html = re.sub(
        r"<strong>\s*(P[012])\s*</strong>",
        lambda m: f'<span class="pri {m.group(1).lower()}">{m.group(1).upper()}</span>',
        html,
    )

    def bq(m: re.Match) -> str:
        inner = m.group(1)
        s = SEV_IN_BQ_RE.search(inner)
        cls = f' class="sev-{s.group(1).lower()}"' if s else ""
        return f"<blockquote{cls}>{inner}</blockquote>"

    return BLOCKQUOTE_RE.sub(bq, html)


def premangle_md(md_text: str) -> str:
    """Markdown 阶段预处理：把 **A 级** / **P0** 换成行内 HTML，避免被包成 <strong>。"""
    md_text = SEV_RE.sub(lambda m: f'<span class="sev {m.group(1).lower()}">{m.group(1).upper()} 级</span>', md_text)
    md_text = PRI_RE.sub(lambda m: f'<span class="pri {m.group(1).lower()}">{m.group(1).upper()}</span>', md_text)
    return md_text


def build_toc(html: str) -> str:
    items = []
    for m in re.finditer(r"<h([23])[^>]*>(.*?)</h\1>", html, re.S | re.I):
        lvl = int(m.group(1))
        title = strip_tags(m.group(2))
        if not title:
            continue
        cls = "lv3" if lvl == 3 else "lv2"
        items.append(f'<li class="{cls}">{html_mod.escape(title)}</li>')
    if not items:
        return ""
    return '<section class="toc"><h2 class="no-break">目录</h2><ol>' + "".join(items) + "</ol></section>"


def build_cover(cover: dict, fallback_title: str) -> str:
    title = html_mod.escape(cover.get("title") or fallback_title or "燕云十六声 · 百业战对局复盘报告")
    subtitle = html_mod.escape(cover.get("subtitle", ""))
    meta_raw = cover.get("meta", "")
    stamp = html_mod.escape(cover.get("stamp", ""))
    d = html_mod.escape(cover.get("date") or date.today().isoformat())

    meta_lines = []
    if meta_raw:
        for part in [p.strip() for p in re.split(r"[｜|]", meta_raw) if p.strip()]:
            meta_lines.append(f"<div>{html_mod.escape(part)}</div>")
    meta_lines.append(f"<div>报告生成日期：{d}</div>")

    stamp_html = f'<div class="stamp">{stamp}</div>' if stamp else ""
    sub_html = f'<p class="subtitle">{subtitle}</p>' if subtitle else '<p class="subtitle"></p>'

    return f"""<section class="cover">
  <div class="rule"></div>
  <h1>{title}</h1>
  {sub_html}
  <div class="meta">{''.join(meta_lines)}</div>
  {stamp_html}
</section>"""


def assemble(md_text: str, css: str, md_path: Path, cli_title: str | None) -> str:
    try:
        import markdown
    except ImportError:
        raise SystemExit("缺少 markdown 库：pip install markdown")

    cover = parse_cover(md_text)
    body_md = COVER_RE.sub("", md_text)
    body_md = premangle_md(body_md)
    body_html = markdown.markdown(
        body_md, extensions=["tables", "fenced_code", "sane_lists", "attr_list", "md_in_html"]
    )
    body_html = decorate(body_html)
    body_html = absolutize_images(body_html, md_path.parent)

    toc = build_toc(body_html)
    cover_html = build_cover(cover, cli_title or "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{html_mod.escape(cover.get('title') or cli_title or '百业战复盘报告')}</title>
<style>{css}
.toc-sentinel {{ font-size: 4px; color: #ffffff; }}</style></head>
<body>
{cover_html}
{toc}
<span class="toc-sentinel">{TOC_SENTINEL}</span>
{body_html}
</body></html>"""


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

def render_with_browser(html_path: Path, pdf_path: Path, timeout: int = 180) -> None:
    browser = find_browser()
    if not browser:
        raise RuntimeError("no-browser")
    tmp_profile = Path(tempfile.mkdtemp(prefix="wb_pdf_"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-scrollbars",
        "--no-pdf-header-footer",
        "--virtual-time-budget=20000",
        f"--user-data-dir={tmp_profile}",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout)
    finally:
        shutil.rmtree(tmp_profile, ignore_errors=True)

    if not pdf_path.exists() or pdf_path.stat().st_size < 1024:
        raise RuntimeError(
            "浏览器导出 PDF 失败。\nSTDOUT:\n" + (res.stdout or "")[-800:] + "\nSTDERR:\n" + (res.stderr or "")[-800:]
        )


def render_with_story(html: str, pdf_path: Path, base_dir: Path) -> None:
    fitz = _fitz()

    story = fitz.Story(html=html, archive=fitz.Archive(str(base_dir)))
    writer = fitz.DocumentWriter(str(pdf_path))
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (45, 46, -45, -50)
    more, pages = 1, 0
    while more and pages < 400:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
    writer.close()
    if pages == 0:
        raise RuntimeError("PyMuPDF Story 排版失败")


# --------------------------------------------------------------------------
# 后处理：页眉页脚 + 书签
# --------------------------------------------------------------------------

def stamp(pdf_path: Path, title: str, page_number: bool, outline: bool,
          headings: list[tuple[int, str]] | None = None) -> None:
    try:
        fitz = _fitz()
    except ImportError:
        print("[warn] 未安装 PyMuPDF，跳过页眉页脚与书签。", file=sys.stderr)
        return

    doc = fitz.open(str(pdf_path))
    n = doc.page_count
    short = (title or "").strip()
    if len(short) > 34:
        short = short[:33] + "…"

    for i, page in enumerate(doc):
        if i == 0:  # 封面不印
            continue
        w, h = page.rect.width, page.rect.height
        grey = (0.42, 0.45, 0.5)
        line = (0.87, 0.89, 0.91)
        if short:
            page.insert_text((45, 30), short, fontname="china-s", fontsize=7.5, color=grey)
        page.draw_line(fitz.Point(45, 36), fitz.Point(w - 45, 36), color=line, width=0.6)
        page.draw_line(fitz.Point(45, h - 40), fitz.Point(w - 45, h - 40), color=line, width=0.6)
        if page_number:
            txt = f"第 {i + 1} 页 / 共 {n} 页"
            tw = fitz.get_text_length(txt, fontname="china-s", fontsize=7.5)
            page.insert_text(((w - tw) / 2, h - 27), txt, fontname="china-s", fontsize=7.5, color=grey)
        page.insert_text((w - 150, h - 27), "百业战复盘", fontname="china-s", fontsize=7.5, color=grey)

    if outline and headings:
        toc_entries = _build_outline(doc, headings)
        if toc_entries:
            try:
                doc.set_toc(toc_entries)
            except Exception as e:
                print(f"[warn] 写入书签失败：{e}", file=sys.stderr)
        else:
            print("[warn] 未能定位任何标题位置，已跳过书签。", file=sys.stderr)

    doc.set_metadata({"title": title or "百业战复盘报告", "author": "WorkBuddy 百业战复盘技能", "subject": "燕云十六声 · 百业战对局分析"})
    doc.save(str(pdf_path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()


def _find_content_start(doc) -> int:
    """定位正文起始页：包含目录结束哨兵的页之后。"""
    for i in range(doc.page_count):
        if TOC_SENTINEL in doc[i].get_text():
            return i + 1
    return 2


def _build_outline(doc, headings: list[tuple[int, str]]) -> list:
    """依据 Markdown 标题在 PDF 中检索页码，生成书签。定位失败则跳过该条。"""
    start = _find_content_start(doc)
    min_level = min((h[0] for h in headings), default=2)
    entries: list = []
    cursor = start
    for level, title in headings:
        found = None
        for pno in range(cursor, doc.page_count):
            rects = doc[pno].search_for(title)
            if not rects:
                probe = title[:20]
                rects = doc[pno].search_for(probe) if len(title) > 20 else []
            if rects:
                found = pno + 1
                cursor = pno
                break
        if found:
            entries.append([max(1, level - min_level + 1), title, found])
    # 去除同一页重复标题
    seen, dedup = set(), []
    for e in entries:
        key = (e[1], e[2])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(e)
    return dedup


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="复盘 Markdown → PDF")
    ap.add_argument("md", help="Markdown 报告路径")
    ap.add_argument("--out", required=True, help="输出 PDF 路径")
    ap.add_argument("--css", default=str(Path(__file__).resolve().parent.parent / "assets" / "report.css"))
    ap.add_argument("--title", default="", help="标题（覆盖 COVER 中的 title）")
    ap.add_argument("--no-page-number", action="store_true")
    ap.add_argument("--no-outline", action="store_true")
    ap.add_argument("--keep-html", action="store_true", help="保留中间 HTML 便于排查")
    args = ap.parse_args()

    md_path = Path(args.md).resolve()
    if not md_path.exists():
        print(f"错误：Markdown 不存在 —— {md_path}", file=sys.stderr)
        return 2

    css_path = Path(args.css).resolve()
    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    md_text = md_path.read_text(encoding="utf-8")
    html = assemble(md_text, css, md_path, args.title or None)

    out_pdf = Path(args.out).resolve()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    build_dir = out_pdf.parent / "_build"
    build_dir.mkdir(exist_ok=True)
    html_path = build_dir / (out_pdf.stem + ".html")
    html_path.write_text(html, encoding="utf-8")

    engine = ""
    try:
        render_with_browser(html_path, out_pdf)
        engine = "chromium-headless"
    except RuntimeError as e:
        if "no-browser" not in str(e):
            print(f"[warn] 浏览器渲染失败，改用离线排版引擎。原因：{e}", file=sys.stderr)
        try:
            render_with_story(html, out_pdf, md_path.parent)
            engine = "pymupdf-story"
        except Exception as e2:
            print(f"错误：两种渲染方式均失败。\n  browser: {e}\n  story: {e2}", file=sys.stderr)
            return 1

    title = args.title or parse_cover(md_text).get("title", "")
    stamp(out_pdf, title or "燕云十六声 · 百业战对局复盘报告",
          page_number=not args.no_page_number, outline=not args.no_outline,
          headings=extract_md_headings(md_text))

    if not args.keep_html:
        shutil.rmtree(build_dir, ignore_errors=True)

    size_kb = out_pdf.stat().st_size / 1024
    print(f"渲染引擎：{engine}")
    print(f"PDF 已生成：{out_pdf}  ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
