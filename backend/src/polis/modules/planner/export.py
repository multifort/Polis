"""结果导出（V2-P3b，design v2/05 §7）：渲染执行结果为 md/pdf。

md：直接输出拼装的 Markdown 全文（复用观测页已有的节点产出/用量数据）。
pdf：reportlab 渲染，**必须嵌入真实 TrueType 中文字体轮廓**——不用 reportlab 内置的
CID 引用式字体（如 STSong-Light）：那种字体不内嵌字形，依赖阅读器本地装有对应中文
字体，在很多环境（服务器/无中文字体的阅读器）会渲染成空白（已实测踩坑）。
"""

from __future__ import annotations

import os
import re
from typing import Any

from polis.config import get_settings

CJK_FONT_NAME = "PolisCJK"

# 常见中文字体候选路径（按优先级）；生产 Linux 建议 `apt install fonts-noto-cjk` 后
# 用 POLIS_PDF_CJK_FONT_PATH 显式指定（Noto CJK 发行为 .ttc，reportlab 按 index 0 加载）。
_CJK_FONT_CANDIDATES = (
    "/Library/Fonts/Arial Unicode.ttf",  # macOS：单体 TTF，多语种含中文，无需猜 ttc 子字体索引
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


class ExportError(Exception):
    """导出失败（如缺中文字体资源）。"""


_font_registered = False


def _ensure_cjk_font() -> str:
    """注册一个内嵌真实轮廓的中文字体（进程内只需一次）。找不到就报错，绝不静默产出空白 PDF。"""
    global _font_registered
    if _font_registered:
        return CJK_FONT_NAME
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    path = get_settings().pdf_cjk_font_path or next(
        (p for p in _CJK_FONT_CANDIDATES if os.path.exists(p)), ""
    )
    if not path:
        raise ExportError(
            "找不到中文字体用于 PDF 渲染；请设置 POLIS_PDF_CJK_FONT_PATH 指向一个 "
            "TrueType 中文字体（如安装 fonts-noto-cjk 后的 NotoSansCJK-Regular.ttc）"
        )
    pdfmetrics.registerFont(TTFont(CJK_FONT_NAME, path))
    _font_registered = True
    return CJK_FONT_NAME


def build_markdown(
    *,
    goal: str,
    status: str,
    started_at: str | None,
    finished_at: str | None,
    duration_seconds: float | None,
    nodes: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
) -> str:
    """拼装导出用的 Markdown 全文：标题/状态/节点产出/用量。"""
    lines = [f"# 执行结果：{goal}", "", f"- 状态：{status}"]
    if started_at:
        lines.append(f"- 开始：{started_at}")
    if finished_at:
        lines.append(f"- 结束：{finished_at}")
    if duration_seconds is not None:
        lines.append(f"- 总耗时：{duration_seconds:.1f} 秒")
    lines.append("")
    for n in nodes:
        lines.append(f"## 节点 {n.get('node_id')}")
        lines.append("")
        lines.append(str(n.get("content") or n.get("summary") or "（无产出）"))
        lines.append("")
    if usage:
        lines.append("## 用量与成本")
        lines.append("")
        lines.append(f"- LLM 调用次数：{usage.get('calls', 0)}")
        lines.append(f"- 总 token：{usage.get('total_tokens', 0)}")
        lines.append(f"- 预估成本：¥{float(usage.get('cost') or 0):.6f}")
        lines.append("")
    return "\n".join(lines)


_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_pdf(markdown_text: str) -> bytes:
    """把导出用的 markdown 全文渲染成一份简版 PDF（标题分级 + 段落；不追求精确排版 MVP）。"""
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font = _ensure_cjk_font()
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("cn_h1", parent=base["Heading1"], fontName=font, fontSize=18, leading=24)
    h2 = ParagraphStyle("cn_h2", parent=base["Heading2"], fontName=font, fontSize=14, leading=20)
    h3 = ParagraphStyle("cn_h3", parent=base["Heading3"], fontName=font, fontSize=12, leading=18)
    body = ParagraphStyle(
        "cn_body", parent=base["BodyText"], fontName=font, fontSize=10.5, leading=16
    )
    level_styles = {1: h1, 2: h2, 3: h3}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    story: list[Any] = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 8))
            continue
        m = _HEADER_RE.match(line)
        if m:
            level = min(len(m.group(1)), 3)
            story.append(Paragraph(_escape(m.group(2)), level_styles[level]))
        elif line.startswith("- "):
            story.append(Paragraph("• " + _escape(line[2:]), body))
        else:
            story.append(Paragraph(_escape(line), body))
    doc.build(story)
    return buf.getvalue()
