"""Cache clean final-clock ASR, then render main's finished video once."""
import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

from core.captions import (DEFAULT_CAPTION_LAYOUT, read_srt, validate_caption_layout, overlay_layout,
                           DEFAULT_BACKGROUND_OPACITY, validate_background_opacity)
from pipeline.final_render import MAIN_SPEED, export_recognition_audio, render_final_video, validate_speed
from pipeline.source_preprocess import load_json, save_json
from pipeline.main_metadata import load_metadata, save_metadata, sync_assets


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def valid_srt(path):
    try:
        read_srt(path)
        return True
    except (OSError, ValueError):
        return False


class MainPostProcessor:
    def __init__(self, paths, transcribe=None, fix_subtitles=None):
        self.paths = paths
        self.transcribe = transcribe
        self.fix_subtitles = fix_subtitles

    def run(self, title=None, subtitle=None, *, caption_layout=None, background_music=None,
            speed=None, refresh_subtitles=False, use_existing_subtitles=False, text_layout=None,
            background_opacity=None):
        metadata = load_metadata(self.paths)
        settings = metadata['render']
        background_opacity = validate_background_opacity(background_opacity if background_opacity is not None
            else settings.get('background_opacity', DEFAULT_BACKGROUND_OPACITY))
        title = title if title is not None else settings.get('title') or metadata.get('drama_title')
        if not title:
            raise ValueError('metadata 缺少标题或剧名')
        layout = dict(caption_layout or settings.get('caption_layout') or DEFAULT_CAPTION_LAYOUT)
        validate_caption_layout(layout)
        text_layout = overlay_layout(text_layout if text_layout is not None else settings.get('overlay_layout'))
        speed = validate_speed(speed if speed is not None else settings.get('speed', MAIN_SPEED))
        if background_music is None:
            background_music = settings.get('background_music')
            if background_music and 'path' not in background_music:
                background_music = {**background_music, 'path': background_music['source_audio_path']}
        elif background_music is False:
            background_music = None
        if background_music:
            volume = float(background_music.get("volume", .08))
            if not math.isfinite(volume) or not 0 <= volume <= 1:
                raise ValueError("背景音乐音量必须在 0 到 1 之间")
            if not Path(background_music["path"]).is_file():
                raise FileNotFoundError(f"背景音乐不存在: {background_music['path']}")
        media = load_json(self.paths.media)
        main = media["main"]
        source = Path(main["concatenated_video_path"])
        if not source.is_file() and not source.is_absolute():
            source = self.paths.root/source.name
        key = signature({"version": 1, "source": file_digest(source), "speed": speed})
        state_path = self.paths.root/"main_postprocess.json"
        state = load_json(state_path) if state_path.exists() else {}
        if state.get("input_key") != key:
            state = {"version": 1, "input_key": key}
        raw = {"srt": self.paths.root/"final_subtitles_raw.srt",
               "json": self.paths.root/"final_subtitles_raw.json"}

        if use_existing_subtitles:
            if not valid_srt(self.paths.final_subtitles["srt"]):
                raise ValueError("没有可用的 final_subtitles.srt")
            # Explicit opt-in for old projects: the user confirms final-clock cues.
            popups = settings.get('popup_comments', [])
            state["subtitle_source"] = "existing_final_clock_srt"
        else:
            print(f"========== 9. 准备 {speed:g} 倍速识别音频（无背景音乐，不渲染视频） ==========", flush=True)
            audio = self.paths.subtitle_audio
            if not (audio.is_file() and state.get("audio_hash") == file_digest(audio)):
                export_recognition_audio(source, audio, speed)
                state["audio_hash"] = file_digest(audio)
                save_json(state_path, state)
            else:
                print("复用识别音频缓存", flush=True)

            print("========== 10. 成片语音识别（复用有效缓存） ==========", flush=True)
            asr_key = signature({"input": key, "audio": state["audio_hash"], "provider": "volcengine-vc-zh-v1"})
            asr_cached = (not refresh_subtitles and state.get("asr_key") == asr_key
                          and valid_srt(raw["srt"]) and raw["json"].is_file()
                          and state.get("raw_hash") == file_digest(raw["srt"]))
            if not asr_cached:
                with tempfile.TemporaryDirectory(prefix="main_asr_", dir=self.paths.root) as directory:
                    temporary = {k: Path(directory)/p.name for k, p in raw.items()}
                    if self.transcribe is None:
                        from services.volcengine import Volcengine
                        transcribe = Volcengine().transcribe_audio
                    else:
                        transcribe = self.transcribe
                    transcribe(audio, temporary)
                    if not valid_srt(temporary["srt"]) or not temporary["json"].is_file():
                        raise ValueError("语音识别未生成有效字幕")
                    for kind in raw:
                        shutil.copy2(temporary[kind], raw[kind])
                state.update(asr_key=asr_key, raw_hash=file_digest(raw["srt"]))
                state.pop("fix_key", None)
                save_json(state_path, state)
            else:
                print("复用成片识别字幕", flush=True)

            print("========== 11. AI 修正字幕与弹幕（复用有效缓存） ==========", flush=True)
            from prompts.fix_subtitles import FIX_SUBTITLE_PROMPT
            from prompts.fix_subtitles_input import FIX_SUBTITLES_INPUT_PROMPT
            from services.chatgpt import ChatGPT, PROVIDERS
            fix_model = PROVIDERS["openai"]["models"]["fix_subtitles"]
            fix_key = signature({"asr": asr_key, "raw": state["raw_hash"], "version": 1,
                                 "provider": "openai", "model": fix_model,
                                 "prompt": FIX_SUBTITLE_PROMPT+FIX_SUBTITLES_INPUT_PROMPT})
            if refresh_subtitles or state.get("fix_key") != fix_key or not valid_srt(self.paths.final_subtitles["srt"]):
                with tempfile.TemporaryDirectory(prefix="main_fix_", dir=self.paths.root) as directory:
                    fixed = Path(directory)/"corrected.srt"
                    if self.fix_subtitles is None:
                        fixer = ChatGPT(usage_report_path=self.paths.llm_cost_report).fix_subtitles
                    else:
                        fixer = self.fix_subtitles
                    popups, generated_subtitle = fixer(raw["srt"], fixed)
                    if not valid_srt(fixed) or not isinstance(popups, list):
                        raise ValueError("AI 修正未生成有效字幕或弹幕")
                    shutil.copy2(fixed, self.paths.final_subtitles["srt"])
                if isinstance(generated_subtitle, str) and generated_subtitle.strip():
                    if not settings.get('subtitle') or settings.get('subtitle') == settings.get('generated_subtitle'):
                        settings['subtitle'] = generated_subtitle.strip()
                        settings['subtitle_source'] = 'ai'
                        settings['subtitle_source'] = 'ai'
                    settings['generated_subtitle'] = generated_subtitle.strip()
                settings['popup_comments'] = popups
                save_metadata(self.paths, metadata)
                state.update(fix_key=fix_key, fix_provider="openai", fix_model=fix_model, popup_comments=popups,
                             generated_subtitle=settings.get('generated_subtitle', ''))
                save_json(state_path, state)
            else:
                popups = settings.get('popup_comments', state.get("popup_comments", []))
                print("复用修正字幕与弹幕；手动修改的 SRT 也会保留", flush=True)
            shutil.copy2(raw["json"], self.paths.final_subtitles["json"])
            state["subtitle_source"] = "cached_or_fresh_asr"

        print("========== 12. 一次渲染竖屏、加速、字幕、标题、弹幕、GIF 与背景音乐 ==========", flush=True)
        if subtitle is not None:
            settings['subtitle_source'] = 'manual'
        if subtitle is not None:
            settings['subtitle_source'] = 'manual'
        subtitle = subtitle if subtitle is not None else settings.get('subtitle') or settings.get('generated_subtitle', '')
        settings.update(title=title, subtitle=subtitle, caption_layout=layout, background_opacity=background_opacity,
                        overlay_layout=text_layout, popup_comments=popups, speed=speed,
                        background_music={**background_music, 'path': str(background_music['path'])} if background_music else None)
        save_metadata(self.paths, metadata)
        result = render_final_video(source, self.paths.final_video, self.paths.final_subtitles["srt"],
            title, subtitle, layout, popups, speed=speed,
            music_path=background_music["path"] if background_music else None,
            music_volume=background_music.get("volume", .08) if background_music else .08,
            gif_path=settings.get('gif_path'),
            ass_path=self.paths.root/"final_render.ass", text_layout=text_layout,
            background_opacity=background_opacity)
        # Old full-video intermediates are no longer part of the execution path.
        for name in ("changed_resolution_video_path", "speed_up_video_path", "post_speed_video_path",
                     "masked_video_path", "subtitle_video_path", "text_overlay_video_path"):
            main.pop(name, None)
        main.update(final_video_path=result["path"], final_render=result,
                    final_subtitles={"srt_path": str(self.paths.final_subtitles["srt"]),
                                     "json_path": str(self.paths.final_subtitles["json"])})
        if self.paths.subtitle_audio.is_file():
            main["subtitle_audio_path"] = str(self.paths.subtitle_audio)
        for name in ('task_title', 'task_subtitle', 'caption_layout', 'overlay_layout',
                     'popup_comments', 'background_music'):
            main.pop(name, None)
        save_json(self.paths.media, media)
        metadata['assets'].update(final_video_path=result['path'], final_render=result,
                                  final_subtitles=main['final_subtitles'])
        save_metadata(self.paths, metadata)
        sync_assets(self.paths, main)
        save_json(state_path, state)
        return self.paths.final_video
