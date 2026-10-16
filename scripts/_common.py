"""公共工具：ffmpeg 定位、时间解析、输出辅助。

被 probe_video.py / extract_frames.py / make_contact_sheet.py 复用。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# ffmpeg 定位：优先系统 ffmpeg，其次 imageio-ffmpeg 自带二进制
# --------------------------------------------------------------------------

_FFMPEG_CACHE: str | None = None


def find_ffmpeg() -> str:
    """返回可用的 ffmpeg 可执行文件路径，找不到则抛 RuntimeError。"""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE

    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        _FFMPEG_CACHE = sys_ff
        return sys_ff

    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            _FFMPEG_CACHE = exe
            return exe
    except Exception:
        pass

    raise RuntimeError(
        "未找到 ffmpeg。请执行：\n"
        "  pip install imageio-ffmpeg\n"
        "或安装系统 ffmpeg 并加入 PATH。"
    )


def find_browser() -> str | None:
    """返回可用于 headless 导出 PDF 的 Chromium 系浏览器路径。"""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


# --------------------------------------------------------------------------
# 时间解析与格式化
# --------------------------------------------------------------------------

def parse_time(text: str | float | int) -> float:
    """把 'SS' / 'MM:SS' / 'HH:MM:SS' / '1:02:03.5' 解析为秒。"""
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if not s:
        raise ValueError("空时间字符串")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"无法解析时间：{text}")
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"无法解析时间：{text}") from exc
    total = 0.0
    for n in nums:
        total = total * 60.0 + n
    return total


def fmt_time(sec: float) -> str:
    """秒 -> HH:MM:SS.mmm"""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def fmt_clock(sec: float) -> str:
    """秒 -> MM:SS（用于对局计时展示）"""
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"


def parse_range(text: str) -> tuple[float, float]:
    """解析 '0:03:00-0:03:30' 或 '180-210' 为 (start, end) 秒。"""
    t = text.strip()
    for sep in ("-", "~", ".."):
        if sep in t:
            a, b = t.split(sep, 1)
            return parse_time(a), parse_time(b)
    raise ValueError(f"无法解析区间（需形如 0:03:00-0:03:30）：{text}")


# --------------------------------------------------------------------------
# ffmpeg 调用
# --------------------------------------------------------------------------

def run_ffmpeg(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess:
    exe = find_ffmpeg()
    cmd = [exe, "-hide_banner", "-nostdin", "-y"] + args
    if verbose:
        print("[ffmpeg]", " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


PROBE_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
PROBE_VIDEO_LINE_RE = re.compile(r"Video:\s*(.+)")
PROBE_RES_RE = re.compile(r"(\d{2,5})x(\d{2,5})")
PROBE_FPS_RE = re.compile(r"([\d.]+)\s*(?:fps|tbr)")


def ffmpeg_probe(path: str) -> dict:
    """用 ffmpeg -i 读取媒体信息（无 ffprobe 时的兜底方案）。"""
    res = run_ffmpeg(["-i", str(path)])
    text = (res.stderr or "") + (res.stdout or "")

    out: dict = {"path": str(path), "exists": Path(path).exists()}
    m = PROBE_DURATION_RE.search(text)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        out["duration_sec"] = h * 3600 + mi * 60 + s

    # Video 流整行（不含换行）用于解析分辨率与帧率；取首段作为编码名
    vline = ""
    vm = PROBE_VIDEO_LINE_RE.search(text)
    if vm:
        vline = vm.group(1).strip()
        out["codec"] = vline.split(",")[0].strip()
    if vline:
        rm = PROBE_RES_RE.search(vline)
        if rm:
            out["width"], out["height"] = int(rm.group(1)), int(rm.group(2))
        fm = PROBE_FPS_RE.search(vline)
        if fm:
            try:
                out["fps"] = float(fm.group(1))
            except ValueError:
                pass
    if "duration_sec" not in out:
        out["error"] = "无法读取时长，请确认文件是有效视频，或 ffmpeg 版本是否支持该封装格式。"
    return out


def ensure_dir(p: str | Path) -> Path:
    d = Path(p)
    d.mkdir(parents=True, exist_ok=True)
    return d
