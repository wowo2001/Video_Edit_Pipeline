"""Experimental multi-source commentary. Run from the repository root with -m."""
import argparse
import atexit
import copy
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

from core.path import ProjectPaths
from core.utils import read_json, write_json, safe_json_parse
from services.chatgpt import ChatGPT
from experiments.news_commentary.prompt import build_prompt


def save(value, path):
    write_json(value, path, ensure_ascii=False, indent=2)


class Planner(ChatGPT):
    # Keep commentary planning independent of the shared conference routing.
    def __init__(self, usage_report_path=None):
        super().__init__(usage_report_path=usage_report_path)
        self.config = {**self.config, 'models': {
            **self.config['models'], 'plan_parliament_commentary': 'gpt-6.1-sol'}}

    def plan_parliament_commentary(self, catalog, angle='', advertisement=''):
        return safe_json_parse(self._complete(build_prompt(catalog, angle, advertisement)))


def expand_indices(indices, count):
    """Expand inclusive LLM endpoints; also accept previously saved index lists."""
    if (not isinstance(indices, list) or not indices
            or any(type(i) is not int or i < 0 or i >= count for i in indices)):
        raise ValueError('引用索引无效或越界')
    if len(indices) == 2:
        if indices[0] > indices[1]:
            raise ValueError('引用起点不能大于终点')
        return list(range(indices[0], indices[1] + 1))
    return indices


def validate_plan(plan, catalog, advertisement=''):
    sources = {s['source_id']: s for s in catalog}
    if not isinstance(plan, dict) or not str(plan.get('title', '')).strip() or not plan.get('segments'):
        raise ValueError('规划缺少标题或段落')
    used = set()
    clean = copy.deepcopy(plan)
    for number, segment in enumerate(clean['segments'], 1):
        source = sources.get(segment.get('source_id'))
        kind = segment.get('type')
        if source is None or kind not in ('narration_only', 'with_dialogue'):
            raise ValueError(f'段落 {number} 来源或类型无效')
        article = source.get('source_type') == 'article'
        rows = source['article_paragraphs'] if article else source['utterances']
        indices = segment.pop('paragraph_indices' if article else 'subtitle_indices', None)
        if article and indices is None:
            indices = segment.pop('subtitle_indices', None)
        indices = expand_indices(indices, len(rows))
        if (not isinstance(indices, list) or not indices or
            any(type(i) is not int or i < 0 or i >= len(rows) for i in indices) or
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
                        if origin is None:
                            raise ValueError(f'段落 {number} 转述来源无效')
                        field = 'paragraph_indices' if origin.get('source_type') == 'article' else 'subtitle_indices'
                        rows_count = len(origin.get('article_paragraphs', origin.get('utterances', [])))
                        reference[field] = expand_indices(reference.get(field), rows_count)
            segment['narration'] = ''.join(part['text'] for part in parts)
        if not isinstance(segment.get('narration'), str) or not segment['narration'].strip():
            raise ValueError(f'段落 {number} 缺少解说')
        if segment.get('audience_question') and number != len(clean['segments']):
            raise ValueError('互动问题只能放在最后一段')
        segment['segment_id'] = number
        segment['source_type'] = source.get('source_type', 'video')
        segment['publisher'] = source.get('publisher', '')
        if article:
            segment['paragraph_indices'] = indices
            segment['visual_mode'] = 'article_typewriter' if kind == 'with_dialogue' else 'publisher_logo'
            if kind == 'with_dialogue':
                segment['original_text'] = '\n\n'.join(rows[i]['text'] for i in indices)
        else:
            segment['dialogue_subtitle_indices' if kind == 'with_dialogue' else 'visual_subtitle_indices'] = indices
    if advertisement and not any(s.get('advertisement') is True for s in clean['segments']):
        matches = [s for s in clean['segments'] if advertisement.strip() in s['narration']]
        if len(matches) == 1:
            matches[0]['advertisement'] = True
    if advertisement and sum(s.get('advertisement') is True for s in clean['segments']) != 1:
        raise ValueError('广告必须恰好植入一次')
    return clean


def source_type(item):
    return item.get('source_type') or ('article' if urlparse(item['url']).hostname in
                                     ('afr.com', 'www.afr.com', 'www.nsw.gov.au', 'www.fairwork.gov.au',
                                      'minister.homeaffairs.gov.au') else 'video')


def download_sources(config, root):
    """Download each source without transcription, planning or rendering."""
    downloads = []
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        paths = ProjectPaths(root / 'sources' / sid)
        kind = source_type(item)
        marker = paths.root / '.download.done'
        if not marker.exists():
            print(f'[{sid}] download ({kind})', flush=True)
            if kind == 'article':
                host = urlparse(item['url']).hostname
                if host in ('afr.com', 'www.afr.com'):
                    from services.afr_article import fetch_afr_article
                    content = fetch_afr_article(item['url'])
                elif host == 'www.fairwork.gov.au':
                    from services.fair_work import fetch_fair_work_article
                    content = fetch_fair_work_article(item['url'])
                elif host == 'www.nsw.gov.au':
                    from services.nsw_gov import fetch_nsw_article
                    content = fetch_nsw_article(item['url'])
                elif host == 'minister.homeaffairs.gov.au':
                    from services.home_affairs_minister import fetch_home_affairs_article
                    content = fetch_home_affairs_article(item['url'])
                else:
                    raise ValueError('该文章来源尚未接入下载模块')
                (paths.root / 'article.txt').write_text(content, encoding='utf-8')
                save({**item, 'source_id': sid, 'source_type': kind,
                      'content': content}, paths.root / 'article.json')
            elif kind == 'video':
                from conference import ParliamentVideoPipeline
                ParliamentVideoPipeline(paths).download_sources_and_captions(
                    item['url'], config.get('title', '新闻评论'), item.get('title'))
            else:
                raise ValueError(f'不支持的素材类型：{kind}')
            marker.touch()
        else:
            print(f'[{sid}] download 已完成，复用本地素材', flush=True)
        downloads.append({**item, 'source_id': sid, 'source_type': kind,
                          'workspace': str(paths.root),
                          'content_path': str(paths.root / 'article.txt' if kind == 'article' else paths.video)})
        save(downloads, root / 'downloaded_sources.json')


def transcribe_sources(config, root):
    from conference import transcribe_parliament_english_subtitles
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        if source_type(item) == 'article':
            print(f'[{sid}] 文章保留原文，跳过语音识别', flush=True)
            continue
        paths = ProjectPaths(root / 'sources' / sid)
        marker = paths.root / '.transcribe.done'
        if marker.exists():
            print(f'[{sid}] transcribe 已完成，复用识别结果', flush=True)
            continue
        print(f'[{sid}] transcribe (火山 en-US)', flush=True)
        transcribe_parliament_english_subtitles(paths)
        marker.touch()


def merge_sources(config, root):
    from conference import merge_english_subtitles_before_diarization
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        if source_type(item) == 'article':
            print(f'[{sid}] 文章保留原文，跳过短句整合', flush=True)
            continue
        paths = ProjectPaths(root / 'sources' / sid)
        marker = paths.root / '.merge.done'
        if marker.exists():
            print(f'[{sid}] merge 已完成，复用整合结果', flush=True)
            continue
        print(f'[{sid}] merge (按语法整合英文短句)', flush=True)
        merge_english_subtitles_before_diarization(paths)
        marker.touch()


def ensure_video_source_context(paths, item):
    """Recover missing YouTube context from the selected source's known metadata."""
    media = read_json(paths.media)
    main = media['main']
    if main.get('source_context'):
        return
    title = item.get('title') or main.get('task_subtitle')
    if not title:
        from conference import record_source_metadata
        record_source_metadata(paths)
        return
    main['source_context'] = {
        'title': title,
        'channel': item.get('publisher') or '',
        'published_at': item.get('published_at'),
        'webpage_url': item['url'],
        'metadata_source': 'selected_source',
    }
    save(media, paths.media)
    print('YouTube 元数据缺失，使用选材时已有的标题和来源', flush=True)


def process_source_speakers(config, root):
    from conference import (classify_speakers, classify_speaker_genders,
                            recognise_parliament_speakers)
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        if source_type(item) == 'article':
            print(f'[{sid}] 文章保留原文，跳过说话人处理', flush=True)
            continue
        paths = ProjectPaths(root / 'sources' / sid)
        ensure_video_source_context(paths, item)
        for name, action in [('speakers', classify_speakers),
                             ('gender', classify_speaker_genders),
                             ('recognise', recognise_parliament_speakers)]:
            marker = paths.root / f'.{name}.done'
            if marker.exists():
                print(f'[{sid}] {name} 已完成，复用结果', flush=True)
                continue
            print(f'[{sid}] {name}', flush=True)
            action(paths)
            marker.touch()


def section_sources(config, root):
    from conference import segment_parliament_content
    from experiments.news_commentary.article_sections import segment_article_content
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        paths = ProjectPaths(root / 'sources' / sid)
        marker = paths.root / '.summary.done'
        if marker.exists():
            print(f'[{sid}] summary 已完成，复用分段结果', flush=True)
            continue
        print(f'[{sid}] section ({source_type(item)})', flush=True)
        if source_type(item) == 'article':
            segment_article_content(paths)
        else:
            segment_parliament_content(paths)
        marker.touch()


def prepare_sources(config, root):
    for action in (download_sources, transcribe_sources, merge_sources,
                   process_source_speakers, section_sources):
        action(config, root)
        from experiments.news_commentary.costs import summarize
        summarize(root)
    build_source_catalog(config, root)


def build_source_catalog(config, root):
    catalog = []
    for number, item in enumerate(config['sources'], 1):
        sid = f'source_{number:02d}'
        paths = ProjectPaths(root / 'sources' / sid)
        sections = read_json(paths.root / 'content_segments.json')
        kind = source_type(item)
        source = {'source_id': sid, 'source_type': kind, 'url': item['url'],
                  'workspace': str(paths.root), 'paragraphs': sections['segments']}
        if kind == 'article':
            article = read_json(paths.root / 'article.json')
            source['context'] = {k: v for k, v in article.items() if k != 'content'}
            source['publisher'] = article.get('publisher', '')
            source['article_paragraphs'] = sections['paragraphs']
        else:
            source['context'] = read_json(paths.media)['main'].get('source_context', {})
            source['publisher'] = item.get('publisher') or source['context'].get('channel', '')
            source['utterances'] = read_json(paths.subtitles['json'])['utterances']
        catalog.append(source)
    save(catalog, root / 'source_catalog.json')
    return catalog


def prepare_article_quote(segment, source, paths):
    """Represent an article quote as a translated, evidence-backed narration part."""
    if source.get('source_type') != 'article' or segment['type'] != 'with_dialogue':
        return
    indices = segment['paragraph_indices']
    original = '\n\n'.join(source['article_paragraphs'][i]['text'] for i in indices)
    result = ChatGPT(usage_report_path=paths.llm_cost_report).translate_subtitles(
        [{'index': 0, 'text': original}])
    translations = result.get('translations', [])
    if (len(translations) != 1 or translations[0].get('index') != 0
            or not isinstance(translations[0].get('text'), str)
            or not translations[0]['text'].strip()):
        raise ValueError('文章引用翻译缺少有效中文文本')
    parts = segment.setdefault('narration_parts', [{'kind': 'bridge', 'text': segment['narration']}])
    parts.append({'kind': 'paraphrase', 'role': 'article_quote',
                  'text': translations[0]['text'].strip(), 'original_text': original,
                  'evidence': [{'source_id': source['source_id'], 'paragraph_indices': indices}]})
    segment.update(type='narration_only', original_type='with_dialogue', original_text=original,
                   narration=''.join(part['text'] for part in parts))


def generate_audio(root):
    from conference import translate_commentary_dialogue
    from experiments.news_commentary.part_tts import generate_part_tts
    catalog = {s['source_id']: s for s in read_json(root / 'source_catalog.json')}
    plan = read_json(root / 'commentary_plan.json')
    for segment in plan['segments']:
        source = catalog[segment['source_id']]
        paths = ProjectPaths(root / 'render_segments' / f"{segment['segment_id']:02d}")
        prepare_article_quote(segment, source, paths)
        save(plan, root / 'commentary_plan.json')
        inputs = {k: segment.get(k) for k in ('source_id', 'type', 'narration',
            'audience_question', 'dialogue_subtitle_indices', 'paragraph_indices', 'original_text')}
        inputs['narration_parts'] = [{k: p.get(k) for k in ('kind', 'role', 'text', 'evidence')}
                                     for p in segment.get('narration_parts', [])]
        inputs['tts_mode'] = 'parts_v2_article_quote_female'
        completed = paths.root / 'audio_completed_input.json'
        if completed.exists() and read_json(completed) == inputs:
            segment.update(read_json(paths.root / 'commentary_plan.json')['segments'][0])
            print(f"段落 {segment['segment_id']} 复用已完成配音", flush=True)
            continue
        print(f"段落 {segment['segment_id']} 翻译与配音 ({source.get('source_type', 'video')})", flush=True)
        save({'title': plan['title'], 'segments': [segment]}, paths.root / 'commentary_plan.json')
        if source.get('source_type') == 'article':
            save({'main': {'source_context': source['context']}}, paths.media)
            save([], paths.root / 'dialogue_dubbing.json')
        else:
            src = ProjectPaths(source['workspace'])
            shutil.copy2(src.subtitles['json'], paths.subtitles['json'])
            shutil.copy2(src.media, paths.media)
            old = read_json(completed) if completed.exists() else {}
            reuse_dialogue = (old.get('source_id') == inputs['source_id'] and
                              old.get('dialogue_subtitle_indices') == inputs['dialogue_subtitle_indices'] and
                              (paths.root / 'dialogue_dubbing.json').exists())
            if not reuse_dialogue:
                translate_commentary_dialogue(paths)
        generate_part_tts(paths)
        segment.update(read_json(paths.root / 'commentary_plan.json')['segments'][0])
        save(inputs, completed)
        save(plan, root / 'commentary_plan.json')
    save(plan, root / 'commentary_plan.json')


def produce(root, config):
    from conference import crossfade_preview_clips
    from experiments.news_commentary.render import render_segment
    catalog = {s['source_id']: s for s in read_json(root / 'source_catalog.json')}
    plan = read_json(root / 'commentary_plan.json')
    if any(catalog[s['source_id']].get('source_type') == 'article' for s in plan['segments']):
        raise ValueError('文章画面渲染尚未接入；可先运行 --step audio')
    generate_audio(root)
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
    parser.add_argument('--step', choices=['all', 'download', 'transcribe', 'merge', 'speakers', 'section', 'prepare', 'plan', 'audio', 'paraphrase', 'produce', 'final', 'final-landscape', 'landscape-layout', 'upload'], default='all')
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
    if args.step == 'download':
        download_sources(config, root)
    if args.step == 'transcribe':
        transcribe_sources(config, root)
    if args.step == 'merge':
        merge_sources(config, root)
    if args.step == 'speakers':
        process_source_speakers(config, root)
    if args.step == 'section':
        section_sources(config, root)
    if args.step in ('all', 'prepare'):
        prepare_sources(config, root)
    if args.step in ('all', 'plan'):
        catalog = build_source_catalog(config, root)
        result = Planner(usage_report_path=paths.llm_cost_report).plan_parliament_commentary(
            catalog, config.get('angle', ''), config.get('广告', ''))
        save(result, root / 'commentary_plan_raw.json')
        save(validate_plan(result, catalog, config.get('广告', '')), root / 'commentary_plan.json')
    if args.step in ('all', 'audio'):
        generate_audio(root)
    if args.step in ('all', 'paraphrase'):
        from experiments.news_commentary.paraphrase_video import prepare_paraphrase_videos
        prepare_paraphrase_videos(root)
        from experiments.news_commentary.layout import build_layout_timeline
        build_layout_timeline(root)
    if args.step in ('all', 'produce'):
        from experiments.news_commentary.mixed_render import produce_mixed
        produce_mixed(root)
    if args.step == 'landscape-layout':
        from experiments.news_commentary.layout import build_layout_timeline
        from pipeline.landscape_avatar import render_landscape_layout
        timeline = build_layout_timeline(root)
        output = render_landscape_layout(root / 'commentary_preview_horizontal.mp4',
            root / 'commentary_avatar_landscape.mp4', timeline['events'],
            transition_seconds=timeline['config']['transition_seconds'])
        media = read_json(paths.media)
        media['main']['commentary_landscape_layout_path'] = str(output)
        save(media, paths.media)
    if args.step in ('all', 'final'):
        from experiments.news_commentary.mixed_render import final_mixed
        final_mixed(root)
    if args.step in ('all', 'final', 'final-landscape'):
        from experiments.news_commentary.mixed_render import final_landscape
        final_landscape(root)
    if args.step == 'upload' or (args.step == 'all' and args.upload):
        from conference import upload_commentary_short_video
        upload_commentary_short_video(paths)
        from experiments.news_commentary.mixed_render import upload_landscape
        upload_landscape(root)
    print(f'实验阶段完成: {args.step}，工作区: {root}', flush=True)


if __name__ == '__main__':
    main()
