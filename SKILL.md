---
name: yanyun-baiyezhan-review
description: 对《燕云十六声》百业战（50v50 团队 PVP）对局录像做逐帧级复盘，从「队伍整体问题 / 个人决策问题 / 操作问题」三个维度按上下半场展开，指出失误、可优化点与改进建议，并输出带封面、目录、书签与关键帧的 PDF 报告。当用户提供百业战录像、录屏、VOD、回放文件，或提出「百业战复盘」「百业战录像分析」「逐帧分析对局」「分析这场百业战」「帮我看看这场打得怎么样」「上半场下半场分析」等请求时使用本技能。关键词：燕云十六声、百业战、录像复盘、对局分析、逐帧分析、上下半场、失误分析、改进建议、PDF 报告。
agent_created: true
---

# 燕云十六声 · 百业战对局复盘

## 目的

把一段百业战录像转化为可执行、可验证的复盘报告：先抽取静帧建立时间轴，再按三维度逐条给出「事实 → 规则依据 → 定级 → 影响 → 建议」，最终产出 PDF。

核心裁判依据是 `references/rules.md`；分析口径是 `references/analysis-framework.md`；报告结构是 `references/report-structure.md`。**开始分析前必须先读取 `references/analysis-framework.md` 与 `references/rules.md`。**

## 铁律

1. **证据优先**：任何结论必须带时间戳与帧编号。看不清的内容写「不可判定」，**绝不编造**技能名、血量、比分、身份。
2. **不做真逐帧**：33 分钟 30fps 约 59,400 帧，全部送模既不可行也无必要。用 `analysis-framework.md` §3 的 L1–L5 分层策略逼近逐帧精度，并在报告中披露抽帧参数。
3. **三维度分离**：队伍问题 ≠ 个人问题；决策问题 ≠ 操作问题。归因时说明责任归属。
4. **上下半场必须分别成章**：不允许只写全场综述。
5. **每条问题配建议**，且建议必须可验证（可量化）。
6. **失败要暴露**：任一步骤失败时如实报告错误原文与已完成的中间产物，不产出半成品 PDF。

---

## 阶段 0 · 环境自检

先确定解释器与脚本目录。默认使用受管环境（已装好全部依赖）：

```bash
# Windows
PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
# macOS / Linux
# PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
SK="<本技能目录>/scripts"
```

**解释器选择规则**：优先用上面这个受管环境；若该路径不存在，按序回退到 `~/.workbuddy/binaries/python/envs/*/Scripts/python.exe`（或 `bin/python`）→ 任意可用的 `python3`/`python`。回退后若 `check_env.py` 报缺包，执行 `pip install pillow pymupdf markdown imageio-ffmpeg`。

```bash
"$PY" "$SK/check_env.py"
```

- 若提示缺 ffmpeg，`imageio-ffmpeg` 自带二进制，无需系统安装 ffmpeg。
- 若提示缺浏览器（warning），PDF 会降级为离线排版引擎，仍可产出，但样式受限——**应在报告「说明」中注明**。

> 脚本为纯 Python，任何 Python 3.9+ 环境均可运行，只需上述四个包。

---

## 阶段 1 · 媒体探针

```bash
"$PY" "$SK/probe_video.py" "<录像路径>" --json work/probe.json
```

读取 `duration_sec / width / height / fps`，并取得 `suggestion.half_split_sec` 作为兜底的中场切分点。

- 若 `duration_sec` 缺失 → **停止**，向用户确认文件是否为有效视频。
- 若时长明显小于一场对局（如 < 10 分钟）→ 判定为剪辑/集锦，按 `highlight` 模式处理，**禁止输出全场节奏类结论**。

> **一键编排（推荐）**：阶段 1–2 的机械部分可用 `run_pipeline.py` 一次完成（探针 → L1/L2/scene 抽帧 → HUD 条带），并产出 `work/PIPELINE_DIGEST.json` 摘要：
>
> ```bash
> "$PY" "$SK/run_pipeline.py" "<录像路径>" --work work
> ```
>
> 长视频单步可能超过默认超时，可加 `--timeout 900` 或按下方分步命令执行。

---

## 阶段 2 · 分层抽帧

在 `work/` 下建立抽帧目录。默认参数（时长 33 分钟时）：

| 层级 | 命令要点 | 目的 |
| --- | --- | --- |
| L1 概览 | `--interval 20` | 全场节奏、阶段划分 |
| L2 阶段 | `--interval 4` | 团战/推进/僵持识别 |
| L3 事件窗 | `--mode ranges --ranges "a-b,c-d" --interval 0.5` | 关键事件前后精查 |
| L4 精确 | `--mode ranges ... --interval 0.1` | 争议操作复核 |
| 场景切点 | `--mode scene --scene-threshold 0.3` | 自动定位转场与团战爆发点 |

示例：

```bash
"$PY" "$SK/extract_frames.py" "<录像>" --out work/frames/L1 --interval 20 --prefix L1
"$PY" "$SK/extract_frames.py" "<录像>" --out work/frames/L2 --interval 4  --prefix L2
"$PY" "$SK/extract_frames.py" "<录像>" --out work/frames/scene --mode scene --scene-threshold 0.3 --prefix SC
"$PY" "$SK/extract_frames.py" "<录像>" --out work/frames/L3 --mode ranges \
    --ranges "0:14:00-0:14:40,0:28:20-0:29:00" --interval 0.5 --prefix L3
```

**送模预算（硬约束）**：交给视觉模型的静帧总量控制在 **120–250 帧**。超量时按此顺序降用量：先提高 L1/L2 间隔 → 只在事件窗做 L3 → 仅对争议点做 L4。宁少而准，不以量取胜。

---

## 阶段 3 · 建轴与事件识别

1. 先生成**拼图**，用最少调用建立全局印象：

```bash
"$PY" "$SK/make_contact_sheet.py" --manifest work/frames/L1/L1_manifest.json \
    --out work/sheets/L1.jpg --cols 4 --per-page 16
```

2. **读 HUD 条带建立客观时间线（关键步骤）**：比分/击杀/鹅血量/人墙血量杯/指挥横幅/系统播报都是小字，
   整帧读容易误读，必须先用条带放大：

```bash
"$PY" "$SK/make_strips.py" --manifest work/frames/L1/L1_manifest.json \
    --out work/strips --only hud_full,chat_log,top_bar --per-page 13
```

   然后逐页 Read `work/strips/hud_full_p*.jpg`（顶栏+横幅区：比分/计时/击杀/鹅血%/墙杯/指挥横幅/中场对决面板）
   与 `chat_log_p*.jpg`（左下播报）。坐标与重标定见 `references/hud-layout.md`。
   从条带中提取：**对局钟↔视频时间映射、比分曲线、击杀曲线、鹅血量拐点、横幅指令变化**。

3. 用 Read 工具逐张阅读 L1/L2 拼图；发现可疑段落 → 再读该段落的单帧原图（更清晰）。

4. 重点抓取以下**锚点**（每确认一个就记录：视频时间、对局时间、帧文件名）：

   - 准备阶段结束 / 开局
   - **中场分界**（中场表演提示、HUD 倒计时重置、明显转场）
   - 首座人墙被摧毁（我方 / 敌方）
   - 张豹 出现与归属、朱骨 出现与归属
   - 鹅 被击杀（我方 / 敌方）、树 出现与被搬运
   - 终局结算画面与判定依据

5. 产出 `work/timeline.json`，字段规范见 `references/analysis-framework.md` §2.3。

6. 判定上下半场切分：优先用对局计时器；否则用中场事件；都用不上才等分，并标注「估算分界」。

> 若画面存在小地图与 HUD，可读取破塔状态、鹅的血量条、比分等客观字段，填入报告「对局概览」。

---

## 阶段 4 · 三维度分析

按 `references/analysis-framework.md` §4 的检查项清单逐项过，**未观察到就写「未观察到」**，不得空着或补默认值。

- 维度一（队伍整体）：T1–T10
- 维度二（个人决策）：P1–P8
- 维度三（操作）：O1–O7

每条问题严格套用 `analysis-framework.md` §7 的六段式结构，并按 §5 定级（S/A/B/C）。

**上下半场分别走一遍三维度**，各自按 §6 量表给分。

动笔前先读取：

```
references/rules.md               # 裁判依据
references/analysis-framework.md  # 分析口径与检查项
references/report-structure.md    # 报告章节与 Markdown 约定
```

---

## 阶段 5 · 生成报告与 PDF

1. **复制模板** `assets/report_template.md` 到工作目录（如 `work/report/report.md`），逐节替换 `{{占位符}}`，删除模板内注释指引。章节顺序与必填内容见 `references/report-structure.md`，**不要从零自由发挥章节结构**（避免图号错位、漏章节）。图片路径相对该 md 文件（例：`figs/fig01_opening.jpg`）。

2. 封面用注释块声明：

```markdown
<!-- COVER
title: 燕云十六声 · 百业战对局复盘报告
subtitle: 录像：xxx.mp4 ｜ 视角：pov
meta: 上半场 0:00–16:30 ｜ 下半场 16:30–33:00
date: 2026-10-16
stamp: 规则依据 references/rules.md；不可判定项已显式标注。
-->
```

3. 渲染 PDF：

```bash
"$PY" "$SK/build_report.py" "report.md" --out "report.pdf"
```

脚本自动完成：注入封面与目录 → Chromium 无头导出 → 盖页眉页脚与页码 → 写入书签大纲。失败时降级为离线排版引擎；两种方式都失败则报错退出，不产出半成品。

4. **用 present_files 把 PDF 交付给用户**，并在回复中给出核心结论摘要（不能只丢文件）。

---

## 参数速查

| 场景 | 调整 |
| --- | --- |
| 视频很长（>40 分钟） | L1 间隔提到 30–40 s；只在事件窗做 L3 |
| 只想看某一段 | 用 `--start` / `--end` 限定范围 |
| 画质低、细节糊 | 提高 `--scale`（如 1920），降低 `--quality`（2 最清晰） |
| 抽帧太多 | 收紧 `--interval`，或降低 `--max-frames` 触发保护 |
| 场景检测无结果 | 调低 `--scene-threshold`（0.2 或 0.15） |
| 无浏览器 | 自动降级，无需干预，但需在报告中注明样式受限 |

## 降级与失败处理

| 现象 | 处理 |
| --- | --- |
| 探针读不到时长 | 停止，请用户确认文件/格式 |
| 抽帧 0 帧 | 检查 `--start/--end` 是否越界；查看 ffmpeg stderr |
| 某段画面不可判定 | 标注「不可判定」，必要时用 L4/L5 回看原片 |
| PDF 渲染双通道均失败 | 报告错误原文，保留 Markdown 与拼图作为可交付中间产物 |
| 用户只要分析不要 PDF | 省略阶段 5，直接输出结构化 Markdown |

## 资源索引

| 路径 | 内容 |
| --- | --- |
| `references/rules.md` | 百业战规则与机制库、常见失误对照表（裁判依据） |
| `references/analysis-framework.md` | 三维度检查项、抽帧策略、定级标准、评分量表、时间轴规范 |
| `references/report-structure.md` | PDF 章节骨架、Markdown 书写约定、写作红线 |
| `references/hud-layout.md` | HUD 区域坐标标定与重标定指南（配合 make_strips.py） |
| `scripts/check_env.py` | 环境自检 |
| `scripts/probe_video.py` | 媒体探针 |
| `scripts/extract_frames.py` | 分层抽帧（uniform / ranges / scene / times） |
| `scripts/make_contact_sheet.py` | 帧拼图，用于低成本目视浏览 |
| `scripts/make_strips.py` | HUD 放大条带（比分/计时/鹅血/墙杯/播报小字的唯一可靠读法） |
| `scripts/run_pipeline.py` | 一键编排：probe → L1/L2/scene → HUD 条带 |
| `scripts/build_report.py` | Markdown → HTML → PDF（含封面、目录、页眉页脚、书签） |
| `assets/report_template.md` | 填空式报告骨架（每次复盘从这里开始写） |
| `assets/report.css` | 报告版式样式 |

## 复用与安装

- 本技能位于用户级目录 `~/.workbuddy/skills/yanyun-baiyezhan-review/`，**所有项目可用**；触发词见文件头部 `description`。
- **团队共享**：把整个技能文件夹复制到项目的 `.workbuddy/skills/yanyun-baiyezhan-review/` 即成为项目级技能。
- **换机器**：整目录复制 + `pip install pillow pymupdf markdown imageio-ffmpeg` 即可（ffmpeg 由 imageio-ffmpeg 自带，浏览器缺失自动降级）。
- **每场复盘的标准开场**：`run_pipeline.py <录像> --work work` → 读 `PIPELINE_DIGEST.json` → 读 HUD 条带。
- **版本升级**：游戏 HUD 改版时按 `references/hud-layout.md` §3 重新标定，同步更新 `make_strips.py` 的 `DEFAULT_REGIONS`。 |
