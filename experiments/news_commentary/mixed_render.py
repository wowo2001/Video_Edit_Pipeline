"""Render part-level commentary using the existing audio and evidence assets."""
import math
from pathlib import Path
from pydub import AudioSegment
from core.utils import read_json, write_json
from core.path import ProjectPaths
from experiments.news_commentary.paraphrase_video import run
from experiments.news_commentary.layout import build_layout_timeline


def produce_mixed(root):
    root=Path(root)
    plan=read_json(root/'commentary_plan.json')
    catalog={s['source_id']:s for s in read_json(root/'source_catalog.json')}
    timeline=build_layout_timeline(root)
    directory=root/'timeline_clips';directory.mkdir(exist_ok=True)
    clips=[];audio_parts=[];subtitles=[];cursor=0
    for segment in plan['segments']:
        source=catalog[segment['source_id']]
        components=[]
        for part in segment['narration_parts']:
            components.append((part['audio_path'],part['text'],part.get('paraphrase_video',{}).get('path'),None))
        if segment['type']=='with_dialogue':
            dub=segment['dubbed_dialogue'];indices=segment['dialogue_subtitle_indices']
            rows=source['utterances'];bounds=(rows[indices[0]]['start_time']/1000,rows[indices[-1]]['end_time']/1000)
            components.append((dub['audio_path'],dub['chinese_text'],None,bounds))
        if segment.get('audience_question_audio_path'):
            components.append((segment['audience_question_audio_path'],segment['audience_question'],None,None))
        for audio,text,visual,bounds in components:
            decoded=AudioSegment.from_file(audio).set_frame_rate(24000).set_channels(1).set_sample_width(2)
            duration=len(decoded.raw_data)/48000
            end=cursor+duration
            frames=max(1,round(end*30)-round(cursor*30))
            clip=directory/f'{len(clips):03d}.mp4'
            print(f'合成素材 {len(clips)+1}: {duration:.2f}s',flush=True)
            if visual:
                inputs=['-i',visual];vf='setpts=PTS-STARTPTS'
            elif bounds:
                start,stop=bounds
                inputs=['-ss',start,'-t',stop-start,'-i',Path(source['workspace'])/'video.mp4']
                vf=f'setpts=(PTS-STARTPTS)*{duration/(stop-start)}'
            elif source['source_type']=='article':
                logo=source['context'].get('logo_path')
                if not logo and source['publisher']=='AFR':
                    logo=Path(__file__).resolve().parents[2]/'assets/afr_logo_1280x720.png'
                if logo:
                    inputs=['-loop',1,'-i',logo];vf='setpts=PTS-STARTPTS'
                else:
                    inputs=['-f','lavfi','-i','color=c=black:s=1280x720:r=30'];vf='null'
            else:
                # Only visible if bridge/commentary is configured as small/large.
                ids=segment.get('visual_subtitle_indices') or segment.get('dialogue_subtitle_indices')
                anchor=source['utterances'][ids[0]]['start_time']/1000
                inputs=['-stream_loop',-1,'-ss',anchor,'-i',Path(source['workspace'])/'video.mp4'];vf='setpts=PTS-STARTPTS'
            vf+=',scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=1'
            run([*inputs,'-an','-vf',vf,'-frames:v',frames,'-c:v','libx264','-preset','fast','-crf',20,'-pix_fmt','yuv420p',clip])
            subtitles.append({'start':cursor,'end':end,'kind':'narration','text':text})
            clips.append(clip);audio_parts.append(decoded);cursor=end
    combined=audio_parts[0]
    for item in audio_parts[1:]:combined+=item
    combined.export(directory/'body.wav',format='wav')
    (directory/'concat.txt').write_text(''.join(f"file '{p.name}'\n" for p in clips))
    run(['-f','concat','-safe',0,'-i',directory/'concat.txt','-i',directory/'body.wav',
         '-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-t',cursor,'-movflags','+faststart',root/'commentary_preview_horizontal.mp4'])
    write_json(subtitles,root/'part_subtitle_events.json',ensure_ascii=False,indent=2)


def final_mixed(root):
    from pipeline.avatar_video import write_script_subtitles, burn_avatar_subtitles, prepend_cover
    from pipeline.cover import create_portrait_cover, create_landscape_cover
    from experiments.news_commentary.layout import render_layout
    paths=ProjectPaths(root);plan=read_json(paths.root/'commentary_plan.json')
    preview=paths.root/'commentary_preview_horizontal.mp4'
    layout=paths.root/'commentary_avatar_layout.mp4'
    body=paths.root/'commentary_body.mp4';final=paths.root/'commentary_news.mp4'
    cover=create_portrait_cover(plan['title'],paths.root/'commentary_cover.png')
    landscape_cover=create_landscape_cover(plan['title'],paths.root/'commentary_cover_landscape.png')
    render_layout(preview,layout,paths.root)
    write_script_subtitles(read_json(paths.root/'part_subtitle_events.json'),paths.final_subtitles['srt'],
                           paths.root/'final_subtitles.ass',paths.final_subtitles['json'])
    burn_avatar_subtitles(layout,paths.root/'final_subtitles.ass',body)
    prepend_cover(body,cover,final)
    media=read_json(paths.media);media['main'].update(commentary_news_video_path=str(final),
        commentary_body_video_path=str(body),commentary_vertical_video_path=str(layout),
        commentary_chinese_subtitles_path=str(paths.final_subtitles['srt']),
        news_title=plan['title'],news_subtitle=plan['title'],
        commentary_cover_path=str(cover),commentary_cover_landscape_path=str(landscape_cover))
    write_json(media,paths.media,ensure_ascii=False,indent=2)
    return final


def final_landscape(root):
    """Reuse evidence, audio and cue timing; render a separate landscape deliverable."""
    from pipeline.landscape_avatar import render_landscape_layout
    from pipeline.avatar_video import FONT, wrap_text
    from pipeline.landscape_avatar import burn_landscape_subtitles
    from pipeline.cover import create_landscape_cover
    from PIL import ImageFont
    root = Path(root)
    timeline = build_layout_timeline(root)
    layout = root/'commentary_avatar_landscape.mp4'
    render_landscape_layout(root/'commentary_preview_horizontal.mp4', layout,
        timeline['events'], transition_seconds=timeline['config']['transition_seconds'])
    # Keep portrait cue timing while reflowing text in the area left of the inset.
    rows = read_json(root/'final_subtitles.json')['utterances']
    font = ImageFont.truetype(str(FONT), 72)
    def stamp(ms):
        cs = round(ms/10)
        return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Smiley Sans Oblique,72,&H005AD3FF,&H005AD3FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,80,480,184,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines = [header]
    for row in rows:
        text = row['text'].replace('\n', '').replace('\\', '＼').replace('{', '｛').replace('}', '｝')
        text = r'\N'.join(wrap_text(text, font, width=1340))
        lines.append(f"Dialogue: 0,{stamp(row['start_time'])},{stamp(row['end_time'])},Default,,0,0,0,,{text}\n")
    ass = root/'final_subtitles_landscape.ass'
    ass.write_text(''.join(lines), encoding='utf-8')
    body = root/'commentary_body_landscape.mp4'
    burn_landscape_subtitles(layout, ass, body)
    plan = read_json(root/'commentary_plan.json')
    cover = create_landscape_cover(plan['title'], root/'commentary_cover_landscape.png')
    final = root/'commentary_news_landscape.mp4'
    run(['-loop',1,'-framerate',30,'-i',cover,'-i',body,'-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
        '-filter_complex',
        '[0:v]scale=1920:1080,setsar=1,trim=duration=1,setpts=PTS-STARTPTS,format=yuv420p[c];'
        '[2:a]atrim=duration=1,asetpts=PTS-STARTPTS[s];'
        '[1:v]fps=30,setsar=1,setpts=PTS-STARTPTS,format=yuv420p[v];'
        '[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.2,'
        'alimiter=limit=0.95:level=false:latency=true,asetpts=PTS-STARTPTS[a];'
        '[c][s][v][a]concat=n=2:v=1:a=1[outv][outa]',
        '-map','[outv]','-map','[outa]','-c:v','libx264','-preset','fast','-crf',20,
        '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',final])
    paths = ProjectPaths(root)
    media = read_json(paths.media)
    media['main'].update(commentary_landscape_video_path=str(final),
        commentary_landscape_layout_path=str(layout),commentary_landscape_subtitles_path=str(ass),
        commentary_cover_landscape_path=str(cover))
    write_json(media,paths.media,ensure_ascii=False,indent=2)
    return final


def upload_landscape(root):
    from services.google_drive import upload_to_drive
    from conference import safe_filename
    paths = ProjectPaths(root)
    media = read_json(paths.media)
    main = media['main']
    video = main.get('commentary_landscape_video_path')
    if not video or not Path(video).is_file():
        print('没有横屏成片，跳过横屏上传', flush=True)
        return
    folder = str(main.get('task_title') or '新闻评论')
    filename = safe_filename(main.get('news_subtitle') or folder) + '_横屏.mp4'
    file_id = upload_to_drive(video, folder_name=folder, filename=filename)
    main['google_drive_landscape'] = dict(file_id=file_id, filename=filename, folder_name=folder, video_path=video)
    write_json(media,paths.media,ensure_ascii=False,indent=2)
    return file_id
