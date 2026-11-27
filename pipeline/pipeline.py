
import shutil

from core.path import ProjectPaths
from core.captions import DEFAULT_CAPTION_LAYOUT
from core.llm_cost import finish_llm_cost_report, start_llm_cost_report
from core.utils import ms_to_seconds, read_json, safe_filename, write_json
from pipeline.subtitles import (
    apply_speaker_mapping,
    apply_timeline,
    strip_srt,
)
from pipeline.audio import (
    export_audio,
    mix_narration_audio,
    mix_background_narration_audio,
    resolve_background_music,
)
from pipeline.source_preprocess import prepare_episode, save_json, validate_profile, probe_source
from pipeline.video import concat_video_paths, cut_video, cut_video_range, fit_forward_video_range
from pipeline.scenes import NARRATION_ONLY, WITH_DIALOGUE, normalize_segment_type
from pipeline.main_postprocess import MainPostProcessor
from pipeline.main_metadata import load_metadata, save_metadata, sync_assets, read_script, save_script
from services.chatgpt import ChatGPT
from services.post_cut_service import PostCutService
from services.volcengine import Volcengine
from services.google_drive import upload_to_drive
from pathlib import Path
from core.demucs import extract_vocals_demucs
from services.s3 import S3


class AutoVideoPipeline:

    def __init__(self, project_paths=None):
        self.project_paths = project_paths or ProjectPaths()

    def _read_main_media(self):
        media = read_json(self.project_paths.media)
        return media, media["main"]

    def _write_media(self, media):
        write_json(media, self.project_paths.media)
        sync_assets(self.project_paths, media['main'])

    def _generate_script_tts(self):
        media, main_media = self._read_main_media()
        script = read_script(self.project_paths)
        tts = Volcengine()

        hook_audio_path = self.project_paths.narration_audios / "hook.mp3"
        script["hook"]["narrative"]["length"] = tts.generate_tts(
            script["hook"]["narrative"]["content"],
            hook_audio_path,
        )
        main_media["script_path"] = str(self.project_paths.script)
        main_media["hook"] = {
            "narration_audio_path": str(hook_audio_path)
        }
        main_media["clips"] = {}

        for item in script["clips"]:
            audio_path = self.project_paths.narration_audios / f"clip_{item['place']}.mp3"
            item["narrative"]["length"] = tts.generate_tts(
                item["narrative"]["content"],
                audio_path,
            )
            main_media["clips"][str(item["place"])] = {
                "narration_audio_path": str(audio_path)
            }

        save_script(self.project_paths, script)
        self._write_media(media)

    def _cut_script_videos(self):
        script = read_script(self.project_paths)
        media, main_media = self._read_main_media()
        hook_media = main_media["hook"]
        hook_media["video_path"] = str(
            cut_video(
                main_media["source_video_path"],
                script["hook"]["clip"],
                ms_to_seconds(script["hook"]["narrative"]["length"]),
                self.project_paths.clips / "hook.mp4",
                narration_position="after",
            )
        )

        source_duration = None
        for item in script["clips"]:
            clip_media = main_media["clips"][str(item["place"])]
            segment_type = normalize_segment_type(item.get("type", WITH_DIALOGUE))
            if segment_type == NARRATION_ONLY:
                if source_duration is None:
                    source_duration = probe_source(main_media["source_video_path"])["duration"]
                bounds = item.get("visual_bounds", {"start": 0, "end": source_duration*1000})
                lower = ms_to_seconds(bounds["start"])
                upper = min(source_duration, ms_to_seconds(bounds["end"]))
                start, end = fit_forward_video_range(
                    ms_to_seconds(item["clip"][0]["start"])-lower,
                    ms_to_seconds(item["narrative"]["length"]), upper-lower)
                start, end = start+lower, end+lower
                clip_media["video_path"] = str(cut_video_range(
                    main_media["source_video_path"],
                    self.project_paths.clips / f"clip_{item['place']}.mp4", start, end))
                clip_media["type"] = segment_type
                clip_media["source_range"] = {"start": start, "end": end}
                continue
            clip_media["video_path"] = str(
                cut_video(
                    main_media["source_video_path"],
                    item["clip"],
                    ms_to_seconds(item["narrative"]["length"]),
                    self.project_paths.clips / f"clip_{item['place']}.mp4",
                    keep_gaps=True,
                )
            )
        self._write_media(media)

    def _concat_script_videos(self):
        media, main_media = self._read_main_media()
        video_paths = [main_media["hook"]["final_video_path"]]
        video_paths.extend(
            main_media["clips"][str(item["place"])]["final_video_path"]
            for item in read_script(self.project_paths)["clips"]
        )
        concat_video_paths(
            video_paths,
            self.project_paths.concatenated_video,
            self.project_paths.root / "final_video_concat_list.txt",
        )
        main_media["concatenated_video_path"] = str(self.project_paths.concatenated_video)
        self._write_media(media)

    def _mix_script_audio(self):
        media, main_media = self._read_main_media()
        hook_media = main_media["hook"]
        hook_media["final_video_path"] = str(self.project_paths.final_clips / "hook_final.mp4")
        mix_narration_audio(
            hook_media["video_path"],
            hook_media["narration_audio_path"],
            hook_media["final_video_path"],
            alignment="end",
        )

        for item in read_script(self.project_paths)["clips"]:
            clip_media = main_media["clips"][str(item["place"])]
            clip_media["final_video_path"] = str(
                self.project_paths.final_clips / f"clip_{item['place']}_final.mp4"
            )
            mixer = (mix_background_narration_audio
                     if normalize_segment_type(item.get("type", WITH_DIALOGUE)) == NARRATION_ONLY
                     else mix_narration_audio)
            mixer(
                clip_media["video_path"],
                clip_media["narration_audio_path"],
                clip_media["final_video_path"],
            )
        self._write_media(media)

    def run(
        self,
        urls,
        title,
        episode,
        upload=False,
        background_music=None,
        background_music_volume=None,
        preprocess_profile=None,
    ):

        if type(episode) is not int or episode < 1:
            raise ValueError('episode 必须是正整数')
        if preprocess_profile is None:
            raise ValueError("请先用 main.py 或 configure_main.bat 配置整批素材预处理")
        validate_profile(preprocess_profile, title)
        start_llm_cost_report(self.project_paths.llm_cost_report)

        print("========== 1. 下载原片并生成整集母版（一次裁剪、模糊、压缩） ==========")
        media_data = prepare_episode(urls, self.project_paths, preprocess_profile)
        media_data['main'].update(drama_title=title, episode=episode)
        self._write_media(media_data)

        print("========== 2. 提取音频 ==========")

        media_data = read_json(self.project_paths.media)
        # Recognise the assembled master's own audio, so multi-source joins and
        # database timestamps use exactly the same timeline as the S3 video.
        master_id = media_data["main"]["source_master"]["fingerprint"][:16]
        audio_path = self.project_paths.audio_dir / f"master_{master_id}.mp3"
        export_audio(Path(media_data["main"]["source_video_path"]), audio_path)
        vocals_path = extract_vocals_demucs(audio_path)
        shutil.copy2(vocals_path, self.project_paths.audio)
        media_data["main"]["raw_audio_path"] = str(audio_path)
        media_data["main"]["vocals_audio_path"] = str(self.project_paths.audio)
        self._write_media(media_data)

        print("========== 3. 字幕识别 ==========")
        media_data, main_media = self._read_main_media()
        Volcengine().transcribe_audio(main_media["vocals_audio_path"], self.project_paths.subtitles)
        main_media["subtitles"] = {
            "srt_path": str(self.project_paths.subtitles["srt"]),
            "json_path": str(self.project_paths.subtitles["json"]),
        }
        self._write_media(media_data)

        print("========== 3.1 语音分类 ==========")
        from core.speechbrain import SpeechBrain
        SpeechBrain().diarize(
            main_media["vocals_audio_path"],
            self.project_paths.subtitles,
            threshold=0.5,
            min_cluster_ratio=0.01,
            core_reassignment_threshold=0.55,
            short_assignment_threshold=0.48,
            assignment_margin=0.03,
        )

        print("========== 3.2 人物识别 ==========")
        strip_srt(self.project_paths.subtitles['srt'], self.project_paths.subtitles['stripped_srt'], keep_index=False)
        ChatGPT(usage_report_path=self.project_paths.llm_cost_report).recognise_speaker(self.project_paths.subtitles['stripped_srt'], self.project_paths.speaker_mapping)
        apply_speaker_mapping(self.project_paths.subtitles['srt'], self.project_paths.speaker_mapping)
        
        print("========== 3.3 生成故事 拆分场景 ==========")
        strip_srt(self.project_paths.subtitles['srt'], self.project_paths.subtitles['stripped_srt'], keep_index=True)
        ChatGPT(usage_report_path=self.project_paths.llm_cost_report).generate_story(self.project_paths.subtitles['stripped_srt'], self.project_paths.story)
        

        print("========== 4. AI 脚本 ==========")
        ChatGPT(usage_report_path=self.project_paths.llm_cost_report).generate_script(self.project_paths.subtitles['stripped_srt'], self.project_paths.script, self.project_paths.story)
        apply_timeline(self.project_paths.script, self.project_paths.subtitles['json'], self.project_paths.story)
        save_script(self.project_paths, read_json(self.project_paths.script))

        print("========== 5. TTS ==========")

        self._generate_script_tts()

        print("========== 6. 剪辑 ==========")

        self._cut_script_videos()

        print("========== 7. 混音 ==========")

        self._mix_script_audio()

        print("========== 8. 拼接 ==========")

        self._concat_script_videos()

        music = None
        if background_music:
            music = resolve_background_music(background_music)
            music["volume"] = (background_music_volume if background_music_volume is not None
                               else music.get("default_volume", 0.08))
        MainPostProcessor(self.project_paths).run(
            None, None,
            caption_layout=preprocess_profile.get("caption_layout", DEFAULT_CAPTION_LAYOUT),
            text_layout=preprocess_profile.get("overlay_layout"),
            background_opacity=preprocess_profile.get('background_opacity'),
            background_music=music,
        )
        media_data, main_media = self._read_main_media()
        render = load_metadata(self.project_paths)['render']
        subtitle = render['subtitle']

        print("========== 13. 上传成片到 Drive ==========")
        if upload:
            safe_file_name = safe_filename(subtitle or title)
            output_path = self.project_paths.root / f"{safe_file_name}.mp4"
            shutil.copy2(main_media["final_video_path"], output_path)
            upload_to_drive(output_path, folder_name=title)
    
        print("========== 14. 上传整集母版到 S3 ==========")
        master = main_media["source_master"]
        prefix = f"videos/masters/v{master['version']}/{master['fingerprint']}"
        s3 = S3()
        s3_url = s3.upload_file(
            main_media["source_video_path"],
            f"{prefix}/source.mp4"
        )
        if not s3_url:
            raise RuntimeError("母版上传失败，未写入数据库")
        manifest_path = self.project_paths.root/"source_master_upload.json"
        save_json(manifest_path, master)
        metadata_url = s3.upload_file(manifest_path, f"{prefix}/preprocess.json", content_type="application/json")
        if not metadata_url:
            raise RuntimeError("母版配置上传失败，未写入数据库")
        master.update(video_url=s3_url, metadata_url=metadata_url)
        self._write_media(media_data)
        print(f"视频已上传到 S3: {s3_url}")

        print("========== 15. 写入数据库 ==========")
        database_result = PostCutService().save_episode_to_db(self.project_paths, s3_url, title, episode)
        metadata = load_metadata(self.project_paths)
        metadata['database'] = database_result
        save_metadata(self.project_paths, metadata)
        finish_llm_cost_report(self.project_paths.llm_cost_report)
