"""Prepare evidence videos for each paraphrase before the final layout render."""
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from core.utils import read_json, write_json
from experiments.news_commentary.typewriter import render_typewriter, ROOT


def run(args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *map(str,args)], check=True)


def prepare_paraphrase_videos(root):
    root = Path(root)
    catalog = {s['source_id']:s for s in read_json(root/'source_catalog.json')}
    plan_path = root/'commentary_plan.json'
    plan = read_json(plan_path)
    directory = root/'paraphrase_videos'
    directory.mkdir(exist_ok=True)
    manifest = []
    for segment in plan['segments']:
        for number, part in enumerate(segment['narration_parts'],1):
            if part['kind'] != 'paraphrase':
                continue
            name = f"segment_{segment['segment_id']:02d}_part_{number:02d}"
            folder = directory/name
            folder.mkdir(exist_ok=True)
            audio = Path(part['audio_path'])
            seconds = part['duration_ms']/1000
            references = []
            for evidence in part['evidence']:
                source = catalog[evidence['source_id']]
                article = source.get('source_type')=='article'
                rows = source['article_paragraphs'] if article else source['utterances']
                indices = evidence['paragraph_indices' if article else 'subtitle_indices']
                text = '\n\n'.join(rows[i]['text'] for i in indices)
                ref = {'source_id':source['source_id'], 'source_type':source.get('source_type','video'),
                       'publisher':source.get('publisher',''), 'url':source['url'],
                       'indices':indices,'text':text}
                if article:
                    federal_background = (ROOT/'assets/australian_government_typewriter_background_blurred.png'
                        if urlparse(ref['url']).hostname == 'minister.homeaffairs.gov.au' else '')
                    background = Path(source['context'].get('typewriter_background') or federal_background or
                        ({'AFR': ROOT/'assets/afr_typewriter_background_blurred.png',
                          'NSW Government': ROOT/'assets/nsw_typewriter_background_blurred.png',
                          'Fair Work Ombudsman': ROOT/'assets/australian_government_typewriter_background_blurred.png'
                          }.get(ref['publisher'], '')))
                    if not background.is_file():
                        raise ValueError(f"请配置 {ref['publisher']} 的 typewriter_background")
                    ref.update(background=str(background),background_hash=hashlib.sha256(background.read_bytes()).hexdigest())
                else:
                    ref['video'] = str(Path(source['workspace'])/'video.mp4')
                    ref['ranges'] = [[rows[i]['start_time'],rows[i]['end_time']] for i in indices]
                references.append(ref)
            fingerprint = hashlib.sha256(json.dumps({'references':references,'duration_ms':part['duration_ms'],
                'audio':hashlib.sha256(audio.read_bytes()).hexdigest(),
                'renderer':hashlib.sha256(Path(__file__).read_bytes()+ (ROOT/'experiments/news_commentary/typewriter.py').read_bytes()).hexdigest()},
                sort_keys=True).encode()).hexdigest()
            output = folder/'paraphrase.mp4'
            marker = folder/'completed.json'
            if not (output.exists() and marker.exists() and read_json(marker).get('fingerprint')==fingerprint):
                print(f'{name}: 生成转述画面',flush=True)
                total = sum(len(ref['text']) for ref in references)
                cursor, clips = 0., []
                for index,ref in enumerate(references):
                    duration = seconds*len(ref['text'])/total if index<len(references)-1 else seconds-cursor
                    piece_audio = folder/f'{index:02d}.wav'
                    run(['-ss',cursor,'-i',audio,'-t',duration,'-ar',24000,'-ac',1,piece_audio])
                    clip = folder/f'{index:02d}.mp4'
                    if ref['source_type']=='article':
                        (folder/f'{index:02d}_original.txt').write_text(ref['text'],encoding='utf-8')
                        render_typewriter(ref['text'],piece_audio,clip,background=ref['background'],publisher=ref['publisher'])
                    else:
                        # Only use the referenced intervals; do not play unrelated intervening footage.
                        groups=[]
                        for start,end in ref['ranges']:
                            if groups and start<=groups[-1][1]+500:
                                groups[-1][1]=end
                            else:
                                groups.append([start,end])
                        filters=[]
                        for j,(start,end) in enumerate(groups):
                            filters.append(f'[0:v]trim=start={start/1000}:end={end/1000},setpts=PTS-STARTPTS[v{j}]')
                        length=sum(b-a for a,b in groups)/1000
                        labels=''.join(f'[v{j}]' for j in range(len(groups)))
                        filters.append(f'{labels}concat=n={len(groups)}:v=1:a=0,setpts=PTS*{duration/length},fps=30,tpad=stop_mode=clone:stop_duration=1,trim=duration={duration},scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1[v]')
                        run(['-i',ref['video'],'-i',piece_audio,'-filter_complex',';'.join(filters),'-map','[v]','-map','1:a',
                             '-c:v','libx264','-preset','fast','-crf',18,'-pix_fmt','yuv420p','-c:a','aac','-t',duration,clip])
                    clips.append(clip)
                    cursor+=duration
                listing=folder/'concat.txt'
                listing.write_text(''.join(f"file '{p.name}'\n" for p in clips), encoding='utf-8')
                # Keep the original part audio once, avoiding accumulated AAC joins.
                run(['-f','concat','-safe',0,'-i',listing,'-i',audio,'-map','0:v','-map','1:a',
                     '-c:v','copy','-c:a','aac','-t',seconds,'-movflags','+faststart',output])
                write_json({'fingerprint':fingerprint},marker)
            else:
                print(f'{name}: 复用已完成素材',flush=True)
            part['paraphrase_video']={'path':str(output),'duration_ms':part['duration_ms'],'references':references}
            manifest.append({'segment_id':segment['segment_id'],'part_index':number-1,**part['paraphrase_video']})
            write_json(plan,plan_path,ensure_ascii=False,indent=2)
            # Keep per-segment cached audio plans consistent with the root plan.
            local=root/'render_segments'/f"{segment['segment_id']:02d}"/'commentary_plan.json'
            if local.exists():
                saved=read_json(local);saved['segments']=[segment]
                write_json(saved,local,ensure_ascii=False,indent=2)
            write_json(manifest,directory/'manifest.json',ensure_ascii=False,indent=2)
    return manifest
