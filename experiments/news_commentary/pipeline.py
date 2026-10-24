"""Experimental multi-source commentary. Run from the repository root with -m."""
import argparse
import atexit
import copy
import json
import shutil
from pathlib import Path

from core.path import ProjectPaths
from core.utils import read_json, write_json, safe_json_parse
from services.chatgpt import ChatGPT
from experiments.news_commentary.prompt import build_prompt


def save(value, path):
    write_json(value, path, ensure_ascii=False, indent=2)


class Planner(ChatGPT):
    # Reuse the conference model routing/cost accounting, with an independent prompt.
    def plan_parliament_commentary(self, catalog, angle='', advertisement=''):
        return safe_json_parse(self._complete(build_prompt(catalog, angle, advertisement)))


def validate_plan(plan, catalog, advertisement=''):
    sources = {s['source_id']: s for s in catalog}
    if not isinstance(plan, dict) or not str(plan.get('title', '')).strip() or not plan.get('segments'):
        raise ValueError('规划缺少标题或段落')
    used = set()
    clean = copy.deepcopy(plan)
    for number, segment in enumerate(clean['segments'], 1):
        source = sources.get(segment.get('source_id'))
        indices = segment.pop('subtitle_indices', None)
        kind = segment.get('type')
        if source is None or kind not in ('narration_only', 'with_dialogue'):
            raise ValueError(f'段落 {number} 来源或类型无效')
        if (not isinstance(indices, list) or not indices or
            any(type(i) is not int or i < 0 or i >= len(source['utterances']) for i in indices) or
            indices != list(range(indices[0], indices[-1] + 1))):
            raise ValueError(f'段落 {number} 字幕索引无效或不连续')
        keys = {(segment['source_id'], i) for i in indices}
        if used & keys:
            raise ValueError(f'段落 {number} 重复使用证据')
        used.update(keys)
        if 'narration_parts' in segment:
            parts = segment['narration_parts']
            if not isinstance(parts, list) or not parts:
                raise ValueError(f'段落 {number} 缺少细分旁白')
            for part in parts:
                if (not isinstance(part, dict) or part.get('kind') not in ('paraphrase', 'bridge', 'commentary')
                    or not isinstance(part.get('text'), str) or not part['text'].strip()):
                    raise ValueError(f'段落 {number} 旁白分类或文本无效')
                if part['kind'] == 'paraphrase':
                    evidence = part.get('evidence')
                    if not isinstance(evidence, list) or not evidence:
                        raise ValueError(f'段落 {number} 转述缺少证据')
                    for reference in evidence:
                        origin = sources.get(reference.get('source_id'))
                        refs = reference.get('subtitle_indices')
                        if (origin is None or not isinstance(refs, list) or not refs or
                            any(type(i) is not int or i < 0 or i >= len(origin['utterances']) for i in refs)):
                            raise ValueError(f'段落 {number} 转述证据编号无效')
            segment['narration'] = ''.join(part['text'] for part in parts)
        if not isinstance(segment.get('narration'), str) or not segment['narration'].strip():
            raise ValueError(f'段落 {number} 缺少解说')
        if kind == 'with_dialogue':
            speakers = {source['utterances'][i].get('attribute', {}).get('speaker') for i in indices}
            if len(indices) > 5 or len(speakers) != 1 or speakers & {None, 'UNKNOWN', ''}:
                raise ValueError(f'段落 {number} 原声必须来自同一个明确说话人')
        if segment.get('audience_question') and number != len(clean['segments']):
            raise ValueError('互动问题只能放在最后一段')
        segment['segment_id'] = number
        segment['dialogue_subtitle_indices' if kind == 'with_dialogue' else 'visual_subtitle_indices'] = indices
    if advertisement and sum(s.get('advertisement') is True for s in clean['segments']) != 1:
        raise ValueError('广告必须恰好植入一次')
    return clean


def prepare_sources(config, root):
    from conference import (ParliamentVideoPipeline, merge_english_subtitles_before_diarization,
        classify_speakers, classify_speaker_genders, recognise_parliament_speakers,
        segment_parliament_content, transcribe_parliament_english_subtitles)
    catalog = []
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        paths = ProjectPaths(root / 'sources' / sid)
        # Stage markers are written only after successful completion; failed stages retry.
        def stage(name, action):
            marker = paths.root / f'.{name}.done'
            if not marker.exists():
                print(f'[{sid}] {name}', flush=True)
                action()
                marker.touch()
                from experiments.news_commentary.costs import summarize
                summarize(root)
        stage('download', lambda: ParliamentVideoPipeline(paths).download_sources_and_captions(
            item['url'], config.get('title', '新闻评论'), item.get('title')))
        stage('transcribe', lambda: transcribe_parliament_english_subtitles(paths))
        stage('merge', lambda: merge_english_subtitles_before_diarization(paths))
        stage('speakers', lambda: classify_speakers(paths))
        stage('gender', lambda: classify_speaker_genders(paths))
        stage('recognise', lambda: recognise_parliament_speakers(paths))
        stage('summary', lambda: segment_parliament_content(paths))
        catalog.append({'source_id': sid, 'url': item['url'], 'workspace': str(paths.root),
                        'context': read_json(paths.media)['main'].get('source_context', {}),
                        'paragraphs': read_json(paths.root / 'content_segments.json')['segments'],
                        'utterances': read_json(paths.subtitles['json'])['utterances']})
    save(catalog, root / 'source_catalog.json')


def produce(root, config):
    from conference import translate_commentary_dialogue, generate_commentary_tts
    from conference import crossfade_preview_clips
    from experiments.news_commentary.render import render_segment
    catalog = {s['source_id']: s for s in read_json(root / 'source_catalog.json')}
    plan = read_json(root / 'commentary_plan.json')
    output_dir = root / 'commentary_preview_segments'
    output_dir.mkdir(exist_ok=True)
    clips = []
    for segment in plan['segments']:
        sid = segment['source_id']
        src = ProjectPaths(catalog[sid]['workspace'])
        paths = ProjectPaths(root / 'render_segments' / f"{segment['segment_id']:02d}")
        # Every segment gets an isolated source video: preludes and questions cannot
        # accidentally spill into a different news source at a concatenation boundary.
        if not paths.video.exists():
            paths.video.symlink_to(src.video.resolve())
        shutil.copy2(src.subtitles['json'], paths.subtitles['json'])
        shutil.copy2(src.media, paths.media)
        save({'title': plan['title'], 'segments': [segment]}, paths.root / 'commentary_plan.json')
        translate_commentary_dialogue(paths)
        generate_commentary_tts(paths)
        render_segment(paths)
        rendered = read_json(paths.root / 'commentary_plan.json')['segments'][0]
        segment.update(rendered)
        # Final timeline/subtitles reuse conference's component-duration accounting.
        for component in (paths.root / 'commentary_preview_segments').glob('*.mp4'):
            shutil.copy2(component, output_dir / component.name)
        clips.append(rendered['render_preview']['final_video_path'])
        save(plan, root / 'commentary_plan.json')
    crossfade_preview_clips(clips, root / 'commentary_preview_horizontal.mp4')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--step', choices=['all', 'prepare', 'plan', 'produce', 'final', 'upload'], default='all')
    parser.add_argument('--upload', action='store_true', help='Upload after an all run')
    args = parser.parse_args()
    config = read_json(args.tasks)
    if not isinstance(config.get('sources'), list) or not config['sources'] or any(
        not isinstance(s, dict) or not isinstance(s.get('url'), str) or not s['url'].strip()
        for s in config['sources']):
        raise ValueError('sources 必须包含新闻 URL')
    root = args.workspace.resolve()
    paths = ProjectPaths(root)
    from experiments.news_commentary.costs import summarize
    atexit.register(summarize, root)
    saved_config = root / 'experiment_input.json'
    if saved_config.exists() and read_json(saved_config) != config:
        raise ValueError('工作区已绑定另一组输入，请使用新工作区')
    save(config, saved_config)
    if not paths.media.exists():
        save({'sources': config['sources'], 'main': {'task_title': config.get('title', '新闻评论')}}, paths.media)
    if args.step in ('all', 'prepare'):
        prepare_sources(config, root)
    if args.step in ('all', 'plan'):
        catalog = read_json(root / 'source_catalog.json')
        result = Planner(usage_report_path=paths.llm_cost_report).plan_parliament_commentary(
            catalog, config.get('angle', ''), config.get('广告', ''))
        save(result, root / 'commentary_plan_raw.json')
        save(validate_plan(result, catalog, config.get('广告', '')), root / 'commentary_plan.json')
    if args.step in ('all', 'produce'):
        produce(root, config)
    if args.step in ('all', 'final'):
        from conference import create_commentary_short_video
        create_commentary_short_video(paths)
    if args.step == 'upload' or (args.step == 'all' and args.upload):
        from conference import upload_commentary_short_video
        upload_commentary_short_video(paths)
    print(f'实验阶段完成: {args.step}，工作区: {root}', flush=True)


if __name__ == '__main__':
    main()
