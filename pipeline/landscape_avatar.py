"""Landscape presenter/news layouts; audio stays on the uninterrupted news timeline.

Modes: none = presenter only; small = news inset; large = presenter inset.
Subtitles and covers belong to later passes, never to either inset.
"""
import argparse
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AVATAR = ROOT / 'assets/Man_generating_video_from_image_20261025235716_silent.mp4'


def render_landscape_layout(news_path, output_path, events, avatar_path=DEFAULT_AVATAR,
                            *, width=1920, height=1080, fps=30,
                            inset_ratio=.2, margin=40, transition_seconds=.5):
    """Render three layouts with smooth dissolves and original-aspect letterboxing."""
    news_path, output_path = Path(news_path), Path(output_path)
    if news_path.resolve() == output_path.resolve():
        raise ValueError('输出不能覆盖输入视频')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams',
        'v:0', '-show_entries', 'stream=duration_ts,time_base,duration', '-of', 'json', str(news_path)]))['streams'][0]
    # Rational stream timing avoids rounded decimal durations adding a phantom frame.
    duration = (int(probe['duration_ts']) * Fraction(probe['time_base'])
                if 'duration_ts' in probe else Fraction(probe['duration']))
    frames = math.ceil(duration * fps)
    events = sorted(events, key=lambda event: event['start'])
    if any(event['mode'] not in ('none', 'small', 'large') for event in events):
        raise ValueError('横屏布局模式应为 none / small / large')
    inset = (round(width * inset_ratio), round(height * inset_ratio))
    position = (width-inset[0]-margin, height-inset[1]-margin)
    processes = []
    log_path = output_path.with_suffix('.log')
    with log_path.open('w', encoding='utf-8') as log:
        def decoder(path, loop=False):
            args = ['ffmpeg', '-v', 'error']
            if loop:
                args += ['-stream_loop', '-1']
            args += ['-i', str(path), '-an', '-vf',
                f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}:eof_action=pass',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log)
            processes.append(process)
            return process

        def read_frame(process):
            data = process.stdout.read(width*height*3)
            return Image.frombytes('RGB', (width, height), data) if len(data) == width*height*3 else None

        def compose(mode, avatar, news):
            if mode == 'none':
                return avatar
            base, foreground = (news, avatar) if mode == 'large' else (avatar, news)
            image = base.copy()
            image.paste(foreground.resize(inset, Image.Resampling.LANCZOS), position)
            return image

        try:
            avatar_decoder, news_decoder = decoder(avatar_path, True), decoder(news_path)
            encoder = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo',
                '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0',
                '-i', str(news_path), '-map', '0:v', '-map', '1:a:0?', '-t', str(float(duration)),
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
                '-c:a', 'copy', '-movflags', '+faststart', str(output_path)], stdin=subprocess.PIPE, stderr=log)
            processes.append(encoder)
            previous_mode, mode, changed_at, event_index = 'none', 'none', 0., 0
            for frame in range(frames):
                t = frame/fps
                while event_index < len(events) and t >= events[event_index]['end']:
                    event_index += 1
                event = events[event_index] if event_index < len(events) and t >= events[event_index]['start'] else None
                target = event['mode'] if event else 'none'
                if target != mode:
                    previous_mode, mode, changed_at = mode, target, t
                avatar, news = read_frame(avatar_decoder), read_frame(news_decoder)
                if avatar is None or news is None:
                    raise RuntimeError(f'横屏解码提前结束：{frame}/{frames}，详见 {log_path}')
                image = compose(mode, avatar, news)
                u = 1 if transition_seconds <= 0 else min(1, (t-changed_at)/transition_seconds)
                if u < 1 and previous_mode != mode:
                    image = Image.blend(compose(previous_mode, avatar, news), image, u*u*(3-2*u))
                encoder.stdin.write(image.tobytes())
                if frame % (fps*10) == 0:
                    print(f'横屏画中画: {t:.0f}/{float(duration):.1f} 秒', flush=True)
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise RuntimeError(f'横屏编码失败：{log_path}')
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if process.stdout:
                    process.stdout.close()
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--news', type=Path, required=True)
    parser.add_argument('--timeline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--avatar', type=Path, default=DEFAULT_AVATAR)
    args = parser.parse_args()
    timeline = json.loads(args.timeline.read_text(encoding='utf-8'))
    render_landscape_layout(args.news, args.output, timeline['events'], args.avatar,
        transition_seconds=timeline.get('config', {}).get('transition_seconds', .5))


def burn_landscape_subtitles(layout_path, ass_path, output_path):
    """Blur a band behind captions, then burn text; keep the right inset clear."""
    import shutil
    import tempfile
    from pipeline.avatar_video import FONT
    with tempfile.TemporaryDirectory(prefix='landscape_subtitles_') as temporary:
        folder = Path(temporary)
        shutil.copy2(ass_path, folder/'captions.ass')
        (folder/'fonts').mkdir()
        shutil.copy2(FONT, folder/'fonts'/FONT.name)
        # Group cue intervals by line count and follow the ASS vertical alignment.
        cues = {}
        font_size, margin_v, alignment = 72, 824, 8
        def seconds(value):
            h, m, sec = value.split(':')
            return int(h)*3600 + int(m)*60 + float(sec)
        for line in Path(ass_path).read_text(encoding='utf-8').splitlines():
            if line.startswith('Style: Default,'):
                fields = line.split(':', 1)[1].strip().split(',')
                font_size, margin_v = float(fields[2]), int(fields[21])
                alignment = int(fields[18])
            elif line.startswith('Dialogue:'):
                fields = line.split(':', 1)[1].strip().split(',', 9)
                count = fields[9].count(r'\N') + 1
                cues.setdefault(count, []).append((seconds(fields[1]), seconds(fields[2])))
        if cues:
            commands = []
            parts = ['[0:v]sendcmd=f=commands.txt,split=' + str(len(cues)+1) + '[base]' +
                     ''.join(f'[crop{i}]' for i in range(len(cues))) + ';']
            previous = 'base'
            for i, (count, intervals) in enumerate(sorted(cues.items())):
                band_height = round(font_size * count + 24)
                top = (margin_v - 12 if alignment in (7, 8, 9) else
                       1080 - margin_v - round(font_size * count) - 12)
                # Merge touching/overlapping cues so boundaries cannot toggle twice.
                merged = []
                for start, end in sorted(intervals):
                    if end <= start:
                        continue
                    if merged and start <= merged[-1][1]:
                        merged[-1][1] = max(merged[-1][1], end)
                    else:
                        merged.append([start, end])
                for start, end in merged:
                    commands.append((start, f'overlay@caption{i} enable 1'))
                    commands.append((end, f'overlay@caption{i} enable 0'))
                parts.append(f'[crop{i}]crop=1400:{band_height}:60:{top},boxblur=18:2,'
                    f'drawbox=x=0:y=0:w=iw:h=ih:color=black@0.15:t=fill[band{i}];')
                parts.append(f"[{previous}][band{i}]overlay@caption{i}=60:{top}:enable=0[layer{i}];")
                previous = f'layer{i}'
            parts.append(f'[{previous}]ass=filename=captions.ass:fontsdir=fonts[v]')
            filters = ''.join(parts)
            (folder/'commands.txt').write_text(''.join(
                f'{time:.3f} {command};\n' for time, command in sorted(commands)
            ), encoding='utf-8')
        else:
            filters = '[0:v]ass=filename=captions.ass:fontsdir=fonts[v]'
        (folder/'filters.txt').write_text(filters, encoding='utf-8')
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(Path(layout_path).resolve()),
            '-filter_complex_script','filters.txt','-map','[v]','-map','0:a:0?',
            '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',
            '-c:a','copy','-movflags','+faststart',str(Path(output_path).resolve())],
            cwd=folder,check=True)
    return Path(output_path)
