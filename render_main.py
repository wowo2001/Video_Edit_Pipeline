"""Re-render an existing main project without downloads, TTS or uploads."""
import argparse
import shutil
from pathlib import Path

from core.captions import DEFAULT_CAPTION_LAYOUT
from core.path import ProjectPaths
from core.llm_cost import finish_llm_cost_report
from core.utils import safe_filename
from main import batch_profile_path
from pipeline.audio import resolve_background_music
from pipeline.main_postprocess import MainPostProcessor
from pipeline.main_metadata import load_metadata, save_metadata
from pipeline.source_preprocess import load_json, save_json, validate_profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True, help="已有 main 项目目录")
    parser.add_argument("--profile", type=Path, help="使用指定选区工具配置中的字幕布局")
    parser.add_argument("--title", help="覆盖顶部剧名")
    parser.add_argument("--subtitle", help="覆盖底部标题")
    parser.add_argument("--speed", type=float, help="覆盖 metadata 中的成片速度")
    parser.add_argument("--refresh-subtitles", action="store_true", help="重新调用语音识别和 AI 修正")
    parser.add_argument("--use-existing-subtitles", action="store_true",
        help="直接使用本地 final_subtitles.srt（应已是成片加速后的时间轴），不调用识别/修正")
    music_group = parser.add_mutually_exclusive_group()
    music_group.add_argument("--background-music", help="背景音乐登记的 id 或名称")
    music_group.add_argument("--no-background-music", action="store_true")
    parser.add_argument("--music-volume", type=float)
    args = parser.parse_args(argv)
    if args.refresh_subtitles and args.use_existing_subtitles:
        parser.error("--refresh-subtitles 和 --use-existing-subtitles 不能同时使用")
    paths = ProjectPaths(args.work.resolve())
    media = load_json(paths.media)
    previous = media["main"]
    metadata_exists = paths.metadata.is_file()
    metadata = load_metadata(paths)
    settings = metadata['render']
    drama_title = (metadata.get('drama_title') or previous.get("drama_title")
                   or previous.get("source_master", {}).get("profile", {}).get("drama_title")
                   or previous.get("task_title") or args.title)
    title = args.title if args.title is not None else settings.get('title') or drama_title
    if not title:
        parser.error("旧项目没有保存剧名，请提供 --title")
    subtitle = args.subtitle
    layout = settings.get('caption_layout', DEFAULT_CAPTION_LAYOUT)
    text_layout = settings.get('overlay_layout')
    profile_path = args.profile or batch_profile_path(drama_title)
    if profile_path.exists() and (args.profile or not metadata_exists):
        profile = validate_profile(load_json(profile_path), drama_title)
        layout = profile.get("caption_layout", DEFAULT_CAPTION_LAYOUT)
        text_layout = profile.get("overlay_layout")
    elif args.profile:
        parser.error(f"配置文件不存在: {args.profile}")
    music = None
    if args.background_music:
        music = resolve_background_music(args.background_music)
    elif args.no_background_music:
        music = False
    elif args.music_volume is not None and settings.get('background_music'):
        stored = settings['background_music']
        music = {**stored, 'path': stored.get('path') or stored['source_audio_path']}
    if music:
        music["volume"] = args.music_volume if args.music_volume is not None else music.get("volume", music.get("default_volume", .08))
    previous["drama_title"] = drama_title
    save_json(paths.media, media)
    metadata['drama_title'] = drama_title
    save_metadata(paths, metadata)
    output = MainPostProcessor(paths).run(title, subtitle, caption_layout=layout, text_layout=text_layout,
        background_music=music, speed=args.speed, refresh_subtitles=args.refresh_subtitles,
        use_existing_subtitles=args.use_existing_subtitles)
    effective_subtitle = subtitle if subtitle is not None else load_metadata(paths)['render'].get('subtitle')
    exported = paths.root/(safe_filename(effective_subtitle or title)+".mp4")
    if exported.resolve() != output.resolve():
        shutil.copy2(output, exported)
    media = load_json(paths.media)
    media["main"]["exported_video_path"] = str(exported)
    save_json(paths.media, media)
    if paths.llm_cost_report.exists():
        finish_llm_cost_report(paths.llm_cost_report)
    print(f"重渲染完成（未上传）: {exported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
