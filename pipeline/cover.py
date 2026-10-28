"""Generate a standalone portrait cover without re-encoding video."""
import re
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AVATAR = ROOT / "assets/uncle_computer_portrait.png"
DEFAULT_FONT = ROOT / "assets/fonts/SmileySans-Oblique.otf"
PORTRAIT_TITLE_START_Y = 800


def _title_layout(title, font_path):
    text = str(title).strip()
    if not text:
        raise ValueError("封面标题不能为空")
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    def width(value, font):
        box = measure.textbbox((0, 0), value, font=font, stroke_width=1)
        return box[2] - box[0]
    # Portrait covers prioritise large type. Long titles wrap into as many
    # semantic lines as needed instead of shrinking back to the former size.
    for size in range(140, 59, -1):
        font = ImageFont.truetype(str(font_path), size)
        lines, remaining = [], text
        while remaining:
            end = 1
            while end < len(remaining) and width(remaining[:end + 1], font) <= 920:
                end += 1
            if end < len(remaining):
                # When practical, end at punctuation rather than slicing it
                # onto the next title line.
                breaks = [i + 1 for i in range(end) if remaining[i] in "，：；。！？、,;:!? "]
                if breaks and breaks[-1] >= end * .55:
                    end = breaks[-1]
            while end < len(remaining) and remaining[end] in "，：；。！？、,;:!?）》】」』”’…":
                end += 1
            lines.append(remaining[:end])
            remaining = remaining[end:]
        line_height = round(size * 1.14)
        if len(lines) <= 4 and PORTRAIT_TITLE_START_Y + len(lines) * line_height <= 1840:
            return lines, font
    raise ValueError("封面标题过长")


def create_portrait_cover(title, output_path, avatar_path=DEFAULT_AVATAR, font_path=DEFAULT_FONT):
    """Render a 1080x1920 cover with a portrait and centered Smiley Sans title."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    W, H = 1080, 1920
    canvas = Image.new('RGB', (W, H), '#171411')
    portrait = Image.open(avatar_path).convert('RGB')
    # Keep the entire original portrait in a centered upper panel.
    portrait = ImageOps.contain(portrait, (W, 1536), Image.Resampling.LANCZOS)
    # Fill side margins using the same picture, softly darkened for a cohesive panel.
    back = ImageOps.fit(Image.open(avatar_path).convert('RGB'), (W, 1536))
    from PIL import ImageFilter, ImageEnhance
    back = ImageEnhance.Brightness(back.filter(ImageFilter.GaussianBlur(28))).enhance(.55)
    canvas.paste(back, (0, 0))
    canvas.paste(portrait, ((W-portrait.width)//2, 0))
    # A dark fade connects the portrait and the title panel.
    shade = Image.new('RGBA', (W, H), (0,0,0,0))
    sd = ImageDraw.Draw(shade)
    for y in range(1376, 1536):
        sd.line((0,y,W,y), fill=(23,20,17,min(255, round(255*(y-1376)/120))))
    canvas = Image.alpha_composite(canvas.convert('RGBA'), shade)
    draw = ImageDraw.Draw(canvas)
    lines, font = _title_layout(title, font_path)
    line_height = round(font.size * 1.14)
    # Begin at the presenter's collar, leaving the lower half to the headline.
    start_y = PORTRAIT_TITLE_START_Y
    for index, line in enumerate(lines):
        top = start_y + index * line_height
        color = '#FFD35A' if index == len(lines) - 1 else '#D7EEF2'
        box = draw.textbbox((0,0), line, font=font, stroke_width=1)
        x = (W - (box[2]-box[0])) / 2 - box[0]
        y = top - box[1]
        draw.text((x+3,y+5), line, font=font, fill='#000000', stroke_width=2)
        draw.text((x,y), line, font=font, fill=color, stroke_width=1)
    canvas.convert("RGB").save(output_path)
    return output_path


def create_landscape_cover(title, output_path,
                           avatar_path=ROOT / 'assets/uncle_computer_landscape.png',
                           font_path=DEFAULT_FONT):
    """1920x1080 cover with large, punctuation-aware type across the lower half."""
    text = str(title).strip()
    if not text:
        raise ValueError('封面标题不能为空')
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1920, 1080
    canvas = ImageOps.fit(Image.open(avatar_path).convert('RGB'), (width, height),
                          method=Image.Resampling.LANCZOS).convert('RGBA')
    shade = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    for y in range(480, height):
        alpha = round(205 * (y - 480) / (height - 480))
        shade_draw.line((0, y, width, y), fill=(9, 12, 16, alpha))
    canvas = Image.alpha_composite(canvas, shade)
    draw = ImageDraw.Draw(canvas)

    # Closing punctuation belongs to the preceding word/character. Explicit
    # newlines remain hard breaks; within each line, balance visual widths.
    def paragraph_options(paragraph, font):
        tokens = re.findall(r'[A-Za-z0-9]+(?:[.&%/-][A-Za-z0-9]+)*|.', paragraph)
        groups = []
        for token in tokens:
            if token in '，：；。！？、,;:!?）》】」』”’…' and groups:
                groups[-1] += token
            else:
                groups.append(token)
        count = len(groups)

        @lru_cache(None)
        def line_width(start, stop):
            return draw.textbbox((0, 0), ''.join(groups[start:stop]).strip(), font=font)[2]

        @lru_cache(None)
        def choose(start, remaining):
            if start == count:
                return (0, ()) if remaining == 0 else None
            if remaining == 0:
                return None
            best = None
            for stop in range(start + 1, count + 1):
                measured = line_width(start, stop)
                if measured > 1740:
                    break
                rest = choose(stop, remaining - 1)
                if rest is None:
                    continue
                line = ''.join(groups[start:stop]).strip()
                if not line:
                    continue
                # Equal line lengths read well at thumbnail size. A natural
                # punctuation boundary is preferred when scores are close.
                score = ((1740 - measured) / 1740) ** 2 + rest[0]
                if stop < count and line[-1] in '，：；。！？、,;:!?':
                    score -= .12
                candidate = (score, (line,) + rest[1])
                if best is None or candidate[0] < best[0]:
                    best = candidate
            return best

        return {n: choose(0, n) for n in range(1, min(4, count) + 1)}

    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chosen = None
    best_quality = float('-inf')
    for size in range(230, 79, -1):
        if size < best_quality - 5:
            break
        line_height = round(size * 1.04)
        if line_height > 520:
            continue
        font = ImageFont.truetype(str(font_path), size)
        options = [(0, 0.0, ())]
        for paragraph in paragraphs:
            next_options = []
            for count, result in paragraph_options(paragraph, font).items():
                if result is None:
                    continue
                for previous_count, previous_score, previous in options:
                    if previous_count + count <= 4:
                        next_options.append((previous_count + count,
                                             previous_score + result[0],
                                             previous + result[1]))
            options = next_options
        options = [(score, lines) for count, score, lines in options
                   if count * line_height <= 520]
        if options:
            for score, lines in options:
                # A little less type size is preferable to an abrupt cut
                # through a sentence, especially beside existing punctuation.
                awkward_breaks = sum(line[-1] not in '，：；。！？、,;:!?' for line in lines[:-1])
                quality = size - 105 * awkward_breaks - 10 * score
                if quality > best_quality:
                    best_quality = quality
                    chosen = (font, line_height, lines)
    if chosen is None:
        raise ValueError('横版封面标题过长，无法放入四行')

    font, line_height, lines = chosen
    start_y = height - 35 - len(lines) * line_height
    for index, line in enumerate(lines):
        box = draw.textbbox((0, 0), line, font=font, stroke_width=4)
        x = (width - (box[2] - box[0])) / 2 - box[0]
        y = start_y + index * line_height - box[1]
        draw.text((x + 7, y + 10), line, font=font, fill='#090A0B',
                  stroke_width=8, stroke_fill='#090A0B')
        draw.text((x, y), line, font=font,
                  fill='#FFD35A' if index == len(lines) - 1 else '#D7EEF2',
                  stroke_width=4, stroke_fill='#111111')
    canvas.convert('RGB').save(output_path)
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(create_portrait_cover(args.title, args.output))
