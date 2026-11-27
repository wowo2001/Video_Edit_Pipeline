"""Editable main editing plan; media.json remains the execution asset registry."""
from copy import deepcopy
from pathlib import Path

from core.captions import DEFAULT_CAPTION_LAYOUT, overlay_layout, DEFAULT_BACKGROUND_OPACITY
from core.utils import read_json, write_json


def load_metadata(paths):
    if paths.metadata.is_file():
        return read_json(paths.metadata)
    media = read_json(paths.media).get('main', {}) if paths.media.is_file() else {}
    cache_path = paths.root/'main_postprocess.json'
    cache = read_json(cache_path) if cache_path.is_file() else {}
    return {
        'version': 1,
        'drama_title': media.get('drama_title') or media.get('source_master', {}).get('profile', {}).get('drama_title') or media.get('task_title'),
        'episode': media.get('episode'),
        'source': {k: media[k] for k in ('source_video_path', 'source_master') if k in media},
        'script': read_json(paths.script) if paths.script.is_file() else {},
        'render': {
            'title': media.get('task_title', ''),
            'subtitle': media.get('task_subtitle', ''),
            'generated_subtitle': cache.get('generated_subtitle', ''),
            'subtitle_source': 'legacy_task' if media.get('task_subtitle') else 'ai',
            'popup_comments': deepcopy(media.get('popup_comments', cache.get('popup_comments', []))),
            'caption_layout': deepcopy(media.get('caption_layout', DEFAULT_CAPTION_LAYOUT)),
            'overlay_layout': overlay_layout(media.get('overlay_layout')),
            'speed': media.get('final_render', {}).get('speed', 1.2),
            'background_opacity': DEFAULT_BACKGROUND_OPACITY,
            'background_music': deepcopy(media.get('background_music')),
            'gif_path': str(Path(__file__).resolve().parents[1]/'assets/like.gif'),
        },
        'assets': {k: deepcopy(media[k]) for k in ('hook', 'clips', 'concatenated_video_path', 'final_subtitles', 'final_video_path') if k in media},
    }


def save_metadata(paths, metadata):
    write_json(metadata, paths.metadata)


def sync_assets(paths, main):
    metadata = load_metadata(paths)
    for key in ('drama_title', 'episode'):
        if key in main:
            metadata[key] = main[key]
    metadata['source'].update({k: main[k] for k in ('source_video_path', 'source_master') if k in main})
    metadata['assets'].update({k: main[k] for k in ('hook', 'clips', 'concatenated_video_path', 'final_subtitles', 'final_video_path') if k in main})
    save_metadata(paths, metadata)


def read_script(paths):
    metadata = load_metadata(paths)
    return metadata['script'] or read_json(paths.script)


def save_script(paths, script):
    metadata = load_metadata(paths)
    metadata['script'] = script
    save_metadata(paths, metadata)
    write_json(script, paths.script)
