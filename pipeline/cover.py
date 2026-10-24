"""Generate a standalone portrait cover without re-encoding video."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AVATAR = ROOT / "assets/red_hair_uncle_avatar.png"
DEFAULT_FONT = ROOT / "assets/fonts/SmileySans-Oblique.otf"


def _title_layout(title, font_path):
    text = str(title).strip()
    if not text:
        raise ValueError("封面标题不能为空")
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    # Prefer a punctuation boundary near the middle, preserving all characters.
    candidates = list(range(1, len(text)))
    def width(value, font):
        box = measure.textbbox((0, 0), value, font=font, stroke_width=1)
        return box[2] - box[0]
    font = ImageFont.truetype(str(font_path), 100)
    if width(text, font) <= 920:
        return [text], font
    def score(i):
        a, b = width(text[:i], font), width(text[i:], font)
        punctuation = text[i-1] in "，：；。！？、,;:!? "
        return max(a, b) + abs(a-b)*.2 - (150 if punctuation else 0)
    split = min(candidates, key=score)
    lines = [text[:split], text[split:]]
    for size in range(100, 0, -1):
        font = ImageFont.truetype(str(font_path), size)
        if all(width(line, font) <= 920 for line in lines):
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
    for y in range(1396, 1536):
        sd.line((0,y,W,y), fill=(23,20,17,round(255*(y-1396)/139)))
    canvas = Image.alpha_composite(canvas.convert('RGBA'), shade)
    draw = ImageDraw.Draw(canvas)
    lines, font = _title_layout(title, font_path)
    line_height = 136 if len(lines) == 2 else 112
    start_y = 1584 if len(lines) <= 2 else 1556
    for index, line in enumerate(lines):
        top = start_y + index * line_height
        color = '#FFD35A' if index == len(lines) - 1 else '#FFFFFF'
        box = draw.textbbox((0,0), line, font=font, stroke_width=1)
        x = (W - (box[2]-box[0])) / 2 - box[0]
        y = top - box[1]
        draw.text((x+3,y+5), line, font=font, fill='#000000', stroke_width=2)
        draw.text((x,y), line, font=font, fill=color, stroke_width=1)
    canvas.convert("RGB").save(output_path)
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(create_portrait_cover(args.title, args.output))
