"""Pixel-based caption boxes shared by the main renderer and selection preview."""
import math
import re
from pathlib import Path

from PIL import ImageFont

DEFAULT_CAPTION_LAYOUT = {"x": 70, "y": 1220, "width": 940, "font_size": 64, "max_lines": 2}

DEFAULT_OVERLAY_LAYOUT = {
    "title": {"y": 400, "font_size": 80},
    "subtitle": {"y": 1470, "font_size": 80},
    "popup": {"y": 750, "font_size": 42},
}


def overlay_layout(value=None):
    """Normalize older profiles without changing their existing appearance."""
    if value is not None and not isinstance(value, dict):
        raise ValueError("标题与弹幕布局必须是对象")
    result = {}
    for name, default in DEFAULT_OVERLAY_LAYOUT.items():
        item = (value or {}).get(name, {})
        if not isinstance(item, dict):
            raise ValueError(f"{name} 布局必须是对象")
        item = {**default, **item}
        size, y = item["font_size"], item["y"]
        if type(size) is not int or not 24 <= size <= 120:
            raise ValueError("标题与弹幕字号应为 24–120")
        if type(y) is not int or not 0 <= y <= 1920-size:
            raise ValueError("标题或弹幕位置超出竖屏")
        result[name] = item
    return result


def validate_caption_layout(layout):
    if not isinstance(layout, dict):
        raise ValueError("字幕布局必须是对象")
    for key in DEFAULT_CAPTION_LAYOUT:
        if type(layout.get(key)) is not int:
            raise ValueError(f"字幕 {key} 必须是整数")
    x, y, width = layout["x"], layout["y"], layout["width"]
    size, lines = layout["font_size"], layout["max_lines"]
    if not 24 <= size <= 96 or not 1 <= lines <= 4:
        raise ValueError("字幕字号应为 24–96，最多行数应为 1–4")
    if not 160 <= width <= 1080 or not 0 <= x <= 1080-width:
        raise ValueError("字幕总宽度或水平位置超出竖屏")
    if not 0 <= y <= 1920-caption_box_height(layout):
        raise ValueError("字幕区域超出竖屏底部，请上移或减少行数/字号")
    return layout


def caption_box_height(layout):
    return math.ceil(layout["font_size"]*1.3)*layout["max_lines"]+16


def wrap_caption(text, font, width):
    """Measure actual glyph widths and preserve every character when wrapping."""
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for token in re.findall(r"[A-Za-z0-9]+|[^A-Za-z0-9]", paragraph):
            if line and font.getlength(line+token) > width:
                lines.append(line)
                line = ""
            for character in token:
                if line and font.getlength(line+character) > width:
                    lines.append(line)
                    line = ""
                line += character
        lines.append(line)
    return lines


def _milliseconds(value):
    hour, minute, second, fraction = map(int, re.split(r"[:,.]", value))
    return ((hour*60+minute)*60+second)*1000+fraction


def read_srt(path):
    pattern = re.compile(r"(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)", re.S)
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    rows = [( _milliseconds(start), _milliseconds(end), content.strip())
            for start, end, content in pattern.findall(text)]
    if not rows:
        raise ValueError("字幕文件为空或 SRT 格式无效")
    return rows


def _ass_time(ms):
    cs = round(ms/10)
    return f"{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}"


def write_caption_ass(rows, destination, layout):
    """Keep width/line limits; overflow becomes sequential pages in the same cue."""
    from core.ffmpeg import FONT_PATH, FONT_FAMILY
    validate_caption_layout(layout)
    font = ImageFont.truetype(str(FONT_PATH), layout["font_size"])
    # ASS sizes its em box using ascent+descent; match the pixel size measured
    # by Pillow and the browser so UI width and wrapping agree with libass.
    ass_size = sum(font.getmetrics())
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_FAMILY},{ass_size},&H0000CCFF,&H0000CCFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,8,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    output = [header]
    for start, end, text in rows:
        if end <= start or not text:
            continue
        lines = wrap_caption(text, font, layout["width"]-16)
        limit = layout["max_lines"]
        pages = [lines[i:i+limit] for i in range(0, len(lines), limit)]
        weights = [max(1, sum(len(line) for line in page)) for page in pages]
        total, consumed = sum(weights), 0
        for page, weight in zip(pages, weights):
            page_start = start+round((end-start)*consumed/total)
            consumed += weight
            page_end = start+round((end-start)*consumed/total)
            for index, line in enumerate(page):
                escaped = line.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
                cx = layout["x"]+layout["width"]/2
                y = layout["y"]+8+index*math.ceil(layout["font_size"]*1.3)
                output.append(f"Dialogue: 0,{_ass_time(page_start)},{_ass_time(page_end)},Default,,0,0,0,,"
                              + r"{\an8\pos("+f"{cx:g},{y}"+r")}"
                              + escaped+"\n")
    Path(destination).write_text("".join(output), encoding="utf-8")
    return Path(destination)


def burn_box_captions(input_video, output_video, ass_file):
    """Use local temporary names to avoid Windows drive/quote filter escaping."""
    import shutil
    import subprocess
    import tempfile
    from core.ffmpeg import FONT_PATH
    with tempfile.TemporaryDirectory(prefix="main_captions_") as temporary:
        folder = Path(temporary)
        shutil.copy2(ass_file, folder/"captions.ass")
        (folder/"fonts").mkdir()
        shutil.copy2(FONT_PATH, folder/"fonts"/FONT_PATH.name)
        subprocess.run(["ffmpeg", "-y", "-i", str(Path(input_video).resolve()),
            "-vf", "ass=filename=captions.ass:fontsdir=fonts", "-c:v", "libx264",
            "-crf", "23", "-preset", "fast", "-c:a", "copy", str(Path(output_video).resolve())],
            cwd=folder, check=True)
