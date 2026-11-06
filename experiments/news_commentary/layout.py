"""Configurable news-window modes for the commentary experiment."""
from pathlib import Path
from core.utils import read_json, write_json

CONFIG_PATH = Path(__file__).with_name('layout_config.json')


def build_layout_timeline(root, config_path=CONFIG_PATH):
    config = read_json(config_path)
    kinds = ('bridge','commentary','video_paraphrase','article_paraphrase','dialogue','audience_question')
    if any(config[k] not in ('none','small','large') for k in kinds):
        raise ValueError('布局只能是 none、small 或 large')
    if config['transition_seconds'] < 0:
        raise ValueError('动画时长不能为负数')
    plan = read_json(Path(root)/'commentary_plan.json')
    catalog = {s['source_id']: s for s in read_json(Path(root)/'source_catalog.json')}
    cursor, events = 0, []
    def add(kind, duration, **metadata):
        nonlocal cursor
        events.append({'kind':kind,'mode':config[kind], 'start':cursor/1000,
                       'end':(cursor+duration)/1000, **metadata})
        cursor += duration
    for segment in plan['segments']:
        for index, part in enumerate(segment['narration_parts']):
            # Use endpoint differences to avoid accumulated rounding drift.
            duration = part['end_ms']-part['start_ms']
            metadata = dict(segment_id=segment['segment_id'],part_index=index,
                            source_id=segment['source_id'],audio_path=part['audio_path'],
                            video_path=part.get('paraphrase_video',{}).get('path'))
            if part['kind'] == 'paraphrase':
                references=part['evidence']
                weights=[]
                for ref in references:
                    src=catalog[ref['source_id']]
                    article=src.get('source_type')=='article'
                    rows=src['article_sentences'] if article else src['utterances']
                    ids=ref['sentence_indices' if article else 'subtitle_indices']
                    weights.append(len('\n\n'.join(rows[i]['text'] for i in ids)))
                used=0
                for n,(ref,weight) in enumerate(zip(references,weights)):
                    end=round(duration*sum(weights[:n+1])/sum(weights))
                    kind='article_paraphrase' if catalog[ref['source_id']].get('source_type')=='article' else 'video_paraphrase'
                    add(kind,end-used,**{**metadata,'source_id':ref['source_id'],'evidence_index':n})
                    used=end
            else:
                add(part['kind'],duration,**metadata)
        if segment['type']=='with_dialogue':
            add('dialogue',segment['dubbed_dialogue']['duration_ms'],segment_id=segment['segment_id'])
        if segment.get('audience_question_audio_path'):
            add('audience_question',segment['audience_question_duration_ms'],segment_id=segment['segment_id'])
    result={'config':config,'duration':cursor/1000,'events':events,
            'time_origin':'body start, before cover; sequential audio without crossfades'}
    write_json(result,Path(root)/'layout_timeline.json',ensure_ascii=False,indent=2)
    return result


def render_layout(news_path, output_path, root, config_path=CONFIG_PATH):
    from pipeline.avatar_video import render_avatar_layout
    timeline=build_layout_timeline(root,config_path)
    return render_avatar_layout(news_path,output_path,[],layout_events=timeline['events'],
                                transition_seconds=timeline['config']['transition_seconds'])
