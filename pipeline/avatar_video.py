"""Conference avatar layout, script subtitles, and final subtitle burn-in."""
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from core.utils import ms_to_srt_time

ROOT = Path(__file__).resolve().parents[1]
AVATAR = ROOT / 'assets/Man_speaking_to_camera_20261025235017_silent.mp4'
FONT = ROOT / 'assets/fonts/SmileySans-Oblique.otf'
WIDTH, HEIGHT, FPS = 1080, 1920, 30
FONT_SIZE = 65


def video_duration(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=duration', '-of', 'default=nw=1:nk=1', str(path)],
        capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def build_timeline(plan, workspace, duration):
    """Match the rendered components and the 0.12s overlap between segments."""
    events = []
    cursor = 0.0
    for index, segment in enumerate(plan['segments']):
        if index:
            cursor -= .12
        number = int(segment['segment_id'])
        directory = workspace / 'commentary_preview_segments'
        narration = segment['narration_duration_ms'] / 1000
        if segment['type'] == 'with_dialogue':
            narration = video_duration(directory / f'{number:02d}_prelude_final.mp4')
        events.append(dict(start=cursor, end=cursor+narration,
                           kind='narration', text=segment['narration']))
        offset = narration
        if segment['type'] == 'with_dialogue':
            dub = segment['dubbed_dialogue']
            length = video_duration(directory / f'{number:02d}_dubbed.mp4')
            events.append(dict(start=cursor+offset, end=cursor+offset+length,
                               kind='dialogue', text=dub['chinese_text']))
            offset += length
        final = directory / f'{number:02d}_final.mp4'
        if segment.get('audience_question_audio_path'):
            offset = video_duration(final)
            length = segment['audience_question_duration_ms'] / 1000
            events.append(dict(start=cursor+offset, end=cursor+offset+length,
                               kind='narration', text=segment['audience_question']))
            final = directory / f'{number:02d}_with_question.mp4'
        cursor += video_duration(final)
    for index, event in enumerate(events):
        event['end'] = min(event['end'], duration,
                           events[index+1]['start'] if index+1<len(events) else duration)
    return events


def wrap_text(text, font, width=940):
    """Explicit line breaks measured in pixels, with punctuation/word preference."""
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines = []
    text = text.strip()
    while text:
        end = 0
        for i in range(1, len(text)+1):
            box = draw.textbbox((0, 0), text[:i], font=font, stroke_width=3)
            if box[2]-box[0] > width:
                break
            end = i
        if not end:
            raise ValueError('字幕单字超出可用宽度')
        if end < len(text):
            choices = [i+1 for i,c in enumerate(text[:end])
                       if c in '，。！？；：、,.;:!? ' and i >= end//2]
            if choices:
                end = choices[-1]
            # Keep closing punctuation with its phrase without exceeding width.
            elif text[end] in '，。！？；：、,.!?;:）】》”' and end > 1:
                end -= 1
        lines.append(text[:end])
        text = text[end:]
    return lines


def write_script_subtitles(events, srt_path, ass_path, json_path):
    font = ImageFont.truetype(str(FONT), FONT_SIZE)
    rows = []
    for event in events:
        # Keep grammatical pauses separate instead of filling two lines with
        # several unrelated sentences. Still preserve the exact script text.
        clauses = re.findall(r'[^，。！？；：,!?;:]+[，。！？；：,!?;:]*|[，。！？；：,!?;:]+', event['text'])
        cues = []
        for clause in clauses:
            lines = wrap_text(clause, font)
            cues.extend('\n'.join(lines[i:i+2]) for i in range(0, len(lines), 2))
        def spoken_weight(cue):
            # Latin letters take less time than the same count of Chinese characters.
            return max(1, sum(.35 if c.isascii() and c.isalpha() else
                              .2 if c.isspace() or c in '，。！？；：,!?;:' else 1
                              for c in cue))
        weights = [spoken_weight(cue) for cue in cues]
        total = sum(weights)
        start = event['start']
        for cue, weight in zip(cues, weights):
            end = start+(event['end']-event['start'])*weight/total
            if end > start:
                rows.append(dict(start_time=round(start*1000), end_time=round(end*1000), text=cue))
            start = end
    def ass_time(ms):
        cs = round(ms/10)
        return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''
    # libass/CoreText resolves the legacy family name, not Pillow's typographic name.
    family = 'Smiley Sans Oblique'
    header += f'Style: Default,{family},{FONT_SIZE},&H005AD3FF,&H005AD3FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,70,70,540,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    srt, ass = [], [header]
    for index,row in enumerate(rows,1):
        srt.append(f"{index}\n{ms_to_srt_time(row['start_time'])} --> {ms_to_srt_time(row['end_time'])}\n{row['text']}\n\n")
        escaped = row['text'].replace('\\','＼').replace('{','｛').replace('}','｝').replace('\n',r'\N')
        ass.append(f"Dialogue: 0,{ass_time(row['start_time'])},{ass_time(row['end_time'])},Default,,0,0,0,,{escaped}\n")
    srt_path.write_text(''.join(srt), encoding='utf-8')
    ass_path.write_text(''.join(ass), encoding='utf-8')
    json_path.write_text(json.dumps({'source':'script_duration_estimate','utterances':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    return rows


def layout_amount(t, intervals, transition=.5):
    def smooth(x):
        x = min(1,max(0,x))
        return x*x*(3-2*x)
    return max((smooth((t-a)/transition)*(1-smooth((t-b)/transition))
                for a,b in intervals), default=0)


def window_state(t, events, transition=.5):
    """Return (large amount, opacity). None anchors at the same small-window box."""
    for index,event in enumerate(events):
        if event['start'] <= t < event['end']:
            mode=event['mode']
            previous=events[index-1]['mode'] if index else 'none'
            target=(float(mode=='large'),float(mode!='none'))
            origin=(float(previous=='large'),float(previous!='none'))
            seconds=min(transition,event['end']-event['start'])
            u=1 if seconds<=0 else min(1,max(0,(t-event['start'])/seconds))
            u=u*u*(3-2*u)
            return tuple(a+(b-a)*u for a,b in zip(origin,target))
    return 0.,0.


def render_avatar_layout(news_path, output_path, events, avatar_path=AVATAR, *,
                         layout_events=None, transition_seconds=.5):
    """Composite clean news footage; subtitles are added in a separate final pass."""
    duration = video_duration(news_path)
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,sample_aspect_ratio', '-of', 'json', str(news_path)],
        capture_output=True, text=True, check=True)
    stream = json.loads(result.stdout)['streams'][0]
    sar = stream.get('sample_aspect_ratio', '1:1')
    numerator, denominator = map(int, sar.split(':')) if sar not in ('N/A', '0:1') else (1, 1)
    aspect = stream['width'] * numerator / (stream['height'] * denominator)
    news_size = (WIDTH, round(WIDTH / aspect))
    small_height = round(594 / aspect)
    small_y = HEIGHT - 52 - 4 - small_height
    large_y = (HEIGHT - news_size[1]) / 2
    intervals = [(e['start'],e['end']) for e in events if e['kind']=='dialogue']
    def decoder(path,size,loop=False):
        args=['ffmpeg','-v','error']
        if loop: args += ['-stream_loop','-1']
        args += ['-i',str(path),'-an','-vf',f'scale={size[0]}:{size[1]},fps={FPS}:eof_action=pass',
                 '-f','rawvideo','-pix_fmt','rgb24','pipe:1']
        return subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    def read_frame(process,size):
        expected=size[0]*size[1]*3
        data=process.stdout.read(expected)
        if len(data)!=expected:
            return None
        return Image.frombytes('RGB',size,data)
    avatar=decoder(avatar_path,(WIDTH,HEIGHT),True)
    news=decoder(news_path,news_size)
    log_path=output_path.with_suffix('.log')
    with log_path.open('w', encoding='utf-8') as log:
        encoder=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24',
            '-s',f'{WIDTH}x{HEIGHT}','-r',str(FPS),'-i','pipe:0','-i',str(news_path),
            '-map','0:v','-map','1:a:0','-t',str(duration),'-c:v','libx264','-preset','fast',
            '-crf','20','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(output_path)],
            stdin=subprocess.PIPE,stderr=log)
        try:
            last_visible_fg=None
            # ffprobe rounds seconds to 6 decimals; discard only that rounding error.
            frame_count = math.ceil(duration * FPS - FPS * 0.000001)
            for i in range(frame_count):
                bg=read_frame(avatar,(WIDTH,HEIGHT)); fg=read_frame(news,news_size)
                if bg is None or fg is None:
                    raise RuntimeError(f'布局解码提前结束：第 {i + 1}/{frame_count} 帧，'
                                       f'素材={"avatar" if bg is None else "news"}')
                if layout_events is None:
                    amount=layout_amount(i/FPS,intervals)
                    opacity=1.
                else:
                    amount,opacity=window_state(i/FPS,layout_events,transition_seconds)
                    current=next((e for e in layout_events if e['start']<=i/FPS<e['end']),None)
                    if current and current['mode']=='none' and last_visible_fg is not None:
                        fg=last_visible_fg
                    elif current and current['mode']!='none':
                        last_visible_fg=fg
                clean_bg=bg.copy() if opacity<1 else None
                if amount:
                    blur=bg.resize((270,480)).filter(ImageFilter.GaussianBlur(7)).resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR)
                    blur=ImageEnhance.Brightness(blur).enhance(.82)
                    bg=Image.blend(bg,blur,amount)
                # Preserve the source aspect ratio and anchor the small window at bottom right.
                width=round(594+486*amount); height=round(width/aspect)
                x=round(450*(1-amount)); y=round(small_y*(1-amount)+large_y*amount)
                box=(max(0,x-4),max(0,y-4),min(WIDTH,x+width+4),min(HEIGHT,y+height+4))
                if amount<1:
                    region=bg.crop(box)
                    bg.paste(Image.blend(region,Image.new('RGB',region.size,'white'),1-amount),box[:2])
                bg.paste(fg.resize((width,height),Image.Resampling.LANCZOS),(x,y))
                if opacity<1:
                    bg=Image.blend(clean_bg,bg,opacity)
                encoder.stdin.write(bg.tobytes())
                if i % (FPS*10)==0:
                    print(f'画中画布局合成: {i/FPS:.0f}/{duration:.1f} 秒',flush=True)
            encoder.stdin.close()
            if encoder.wait()!=0:
                raise RuntimeError(f'布局编码失败: {log_path}')
        finally:
            for process in (avatar,news,encoder):
                if process.poll() is None: process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    # An infinite decoder may block writing to its full stdout pipe.
                    process.kill()
                    process.wait()
            avatar.stdout.close(); news.stdout.close()
    return output_path


def burn_avatar_subtitles(layout_path, ass_path, final_path):
    # Safe temporary names also handle apostrophes in source-video titles.
    with tempfile.TemporaryDirectory(prefix='avatar_subtitles_') as tmp:
        folder=Path(tmp)
        shutil.copy2(ass_path,folder/'captions.ass')
        (folder/'fonts').mkdir()
        shutil.copy2(FONT,folder/'fonts'/FONT.name)
        subprocess.run(['ffmpeg','-v','warning','-y','-i',str(Path(layout_path).resolve()),
            '-vf','ass=filename=captions.ass:fontsdir=fonts', '-c:v','libx264','-preset','fast',
            '-crf','20','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',
            str(Path(final_path).resolve())],cwd=folder,check=True)
    return final_path


def prepend_cover(body_path, cover_path, output_path, duration=1.0):
    """Add a silent cover and boost body audio by 20%; retain sync."""
    if duration <= 0:
        raise ValueError('封面时长必须大于零')
    if Path(body_path).resolve() == Path(output_path).resolve():
        raise ValueError('封面输出不能覆盖输入正文')
    filters = (
        f'[0:v]scale={WIDTH}:{HEIGHT},setsar=1,fps={FPS},'
        f'trim=duration={duration},setpts=PTS-STARTPTS,format=yuv420p[cover];'
        f'[2:a]atrim=duration={duration},asetpts=PTS-STARTPTS[silence];'
        f'[1:v]setsar=1,fps={FPS},setpts=PTS-STARTPTS,format=yuv420p[body];'
        '[1:a]aresample=48000,aformat=channel_layouts=stereo,'
        'volume=1.2,alimiter=limit=0.95:level=false:latency=true,asetpts=PTS-STARTPTS[audio];'
        '[cover][silence][body][audio]concat=n=2:v=1:a=1[v][a]'
    )
    subprocess.run(['ffmpeg','-v','warning','-y','-loop','1','-framerate',str(FPS),
        '-i',str(cover_path),'-i',str(body_path),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
        '-filter_complex',filters,'-map','[v]','-map','[a]',
        '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',
        '-c:a','aac','-b:a','192k','-movflags','+faststart',str(output_path)],check=True)
    return output_path
