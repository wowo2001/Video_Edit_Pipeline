"""English typewriter video with supplied Chinese audio; automatic wrapping/pages.
Reveal timing follows audio duration, not word-level cross-language alignment.
"""
import argparse
import math
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[2]


def render_typewriter(text, audio, output, background=None, fps=30, *, publisher):
    background = background or ROOT / 'assets/article_typewriter_background_1280x720.png'
    font_path = str(ROOT / 'assets/fonts/SmileySans-Oblique.otf')
    font = ImageFont.truetype(font_path, 40)
    source_font = ImageFont.truetype(font_path, 48)
    duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration', '-of', 'default=nw=1:nk=1', str(audio)], text=True))
    if not text.strip() or duration <= 0:
        raise ValueError('原文和配音不能为空')
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines = []
    for paragraph in text.splitlines():
        line = ''
        for word in paragraph.split():
            candidate = (line+' '+word).strip()
            if line and measure.textlength(candidate, font=font)>1080:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
    page_count = math.ceil(len(lines)/7)
    per_page = math.ceil(len(lines)/page_count)
    pages = [lines[i:i+per_page] for i in range(0, len(lines), per_page)]
    weights = [sum(map(len, page)) for page in pages]
    base = Image.open(background).convert('RGBA').resize((1280,720))
    box = (76, 142, 1204, 720)
    base.paste(base.crop(box).filter(ImageFilter.GaussianBlur(10)), box)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    codec = ['-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p']
    process = subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y',
        '-f','rawvideo','-pix_fmt','rgba','-s','1280x720','-r',str(fps),'-i','-',
        '-i',str(audio),'-map','0:v','-map','1:a',*codec,'-c:a','aac','-t',str(duration),
        '-movflags','+faststart',str(output)], stdin=subprocess.PIPE)
    try:
        for frame in range(math.ceil(duration*fps)):
            t, start = frame/fps, 0
            for index, weight in enumerate(weights):
                seconds = duration*weight/sum(weights)
                if t < start+seconds or index==len(pages)-1:
                    break
                start += seconds
            lead, hold = min(.25,seconds*.05), min(1.2,seconds*.15)
            remaining = int(weight*min(1,max(0,(t-start-lead)/(seconds-lead-hold))))
            image = base.copy()
            draw = ImageDraw.Draw(image)
            for line_number, line in enumerate(pages[index]):
                draw.text((100,146+57*line_number),line[:max(0,remaining)],font=font,fill='#30343B')
                remaining -= len(line)
                if remaining<0:
                    break
            if index == len(pages)-1 and remaining >= 0 and publisher:
                draw.text((100, 146+57*len(pages[index])+14), '--'+publisher,
                          font=source_font, fill='#FFD400', stroke_width=1, stroke_fill='#343434')
            process.stdin.write(image.tobytes())
    finally:
        process.stdin.close()
        code = process.wait()
    if code:
        raise RuntimeError(f'ffmpeg 渲染失败: {code}')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text-file',type=Path,required=True)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--background',type=Path)
    parser.add_argument('--publisher', required=True, help='素材的 publisher 媒体名称')
    args = parser.parse_args()
    render_typewriter(args.text_file.read_text(encoding='utf-8'),args.audio,args.output,args.background,publisher=args.publisher)
