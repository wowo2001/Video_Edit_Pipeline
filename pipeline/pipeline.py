
import shutil
import uuid

from core.path import ProjectPaths
from core.utils import ms_to_seconds, read_json, safe_filename, clear_workdir, write_json
from pipeline.subtitles import (
    apply_character_scene_mapping,
    apply_speaker_mapping,
    apply_timeline,
    chunk_srt_by_scenes,
    strip_srt,
)
from core.whisper import Whisper
from pipeline.audio import export_audio, mix_narration_audio
from core.ffmpeg import concat_media
from pipeline.download import download_video
from pipeline.video import add_gif_overlay, add_subtitles, change_resolution, concat_video_paths, cut_video, mask_sub, speed_up, add_text_overlay, mosaic_regions
from services.post_cut_service import PostCutService
from services.chatgpt import ChatGPT
from services.ali import Ali
from services.volcengine import Volcengine
from services.google_drive import upload_to_drive
from pathlib import Path
from core.demucs import extract_vocals_demucs
from core.speechbrain import SpeechBrain
from services.s3 import S3


class AutoVideoPipeline:

    def __init__(self, project_paths=None):
        self.project_paths = project_paths or ProjectPaths()

    def _read_main_media(self):
        media = read_json(self.project_paths.media)
        return media, media["main"]

    def _write_media(self, media):
        write_json(media, self.project_paths.media)

    def _record_tts_paths(self):
        media, main_media = self._read_main_media()
        script = read_json(self.project_paths.script)
        main_media["script_path"] = str(self.project_paths.script)
        main_media["hook"] = {
            "narration_audio_path": str(self.project_paths.narration_audios / "hook.mp3")
        }
        main_media["clips"] = {
            str(item["place"]): {
                "narration_audio_path": str(
                    self.project_paths.narration_audios / f"clip_{item['place']}.mp3"
                )
            }
            for item in script["clips"]
        }
        self._write_media(media)

    def _cut_script_videos(self):
        script = read_json(self.project_paths.script)
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

        for item in script["clips"]:
            clip_media = main_media["clips"][str(item["place"])]
            clip_media["video_path"] = str(
                cut_video(
                    main_media["source_video_path"],
                    item["clip"],
                    ms_to_seconds(item["narrative"]["length"]),
                    self.project_paths.clips / f"clip_{item['place']}.mp4",
                )
            )
        self._write_media(media)

    def _concat_script_videos(self):
        media, main_media = self._read_main_media()
        video_paths = [main_media["hook"]["final_video_path"]]
        video_paths.extend(
            main_media["clips"][str(item["place"])]["final_video_path"]
            for item in read_json(self.project_paths.script)["clips"]
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

        for item in read_json(self.project_paths.script)["clips"]:
            clip_media = main_media["clips"][str(item["place"])]
            clip_media["final_video_path"] = str(
                self.project_paths.final_clips / f"clip_{item['place']}_final.mp4"
            )
            mix_narration_audio(
                clip_media["video_path"],
                clip_media["narration_audio_path"],
                clip_media["final_video_path"],
            )
        self._write_media(media)

    def run(self, urls, title, subtitle = None, upload=False):

        print("========== 1. 下载视频 ==========")

        download_video(
            urls,
            self.project_paths.video,
            self.project_paths.origin,
            self.project_paths.media,
        )

        print("========== 2. 提取音频 ==========")

        media_data = read_json(self.project_paths.media)
        vocals_paths = []
        for index, media in enumerate(media_data["sources"]):
            audio_path = self.project_paths.audio_dir / f"{index:03d}.mp3"
            export_audio(Path(media["video_path"]), audio_path)
            vocals_path = extract_vocals_demucs(audio_path)

            media["audio_path"] = str(audio_path)
            media["vocals_path"] = str(vocals_path)
            vocals_paths.append(vocals_path)

        write_json(media_data, self.project_paths.media)
        with open(self.project_paths.vocals_filelist, "w", encoding="utf-8") as file:
            for vocals_path in vocals_paths:
                file.write(f"file '{vocals_path.absolute()}'\n")
        concat_media(self.project_paths.vocals_filelist, self.project_paths.audio)
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
        # Whisper().transcribe(self.project_paths.audio, self.project_paths.subtitles)

        print("========== 3.1 语音分类 ==========")
        SpeechBrain().diarize(main_media["vocals_audio_path"], self.project_paths.subtitles,threshold=0.65,min_cluster_ratio=0.01)

        print("========== 3.2 人物识别 ==========")
        strip_srt(self.project_paths.subtitles['srt'], self.project_paths.subtitles['stripped_srt'], keep_index=False)
        ChatGPT().recognise_speaker(self.project_paths.subtitles['stripped_srt'], self.project_paths.speaker_mapping)
        apply_speaker_mapping(self.project_paths.subtitles['srt'], self.project_paths.speaker_mapping)
        
        print("========== 3.3 生成故事 拆分场景 ==========")
        strip_srt(self.project_paths.subtitles['srt'], self.project_paths.subtitles['stripped_srt'], keep_index=True)
        ChatGPT().generate_story(self.project_paths.subtitles['stripped_srt'], self.project_paths.story)
        

        print("========== 4. AI 脚本 ==========")
        chunk_srt_by_scenes(self.project_paths.subtitles['stripped_srt'], self.project_paths.story,self.project_paths.subtitles['chunked_srt'])
        Ali().generate_script(self.project_paths.subtitles['stripped_srt'], self.project_paths.script, self.project_paths.story)
        apply_timeline(self.project_paths.script, self.project_paths.subtitles['json'])

        print("========== 5. TTS ==========")

        Volcengine().generate_tts(self.project_paths.script, self.project_paths.narration_audios)
        self._record_tts_paths()

        print("========== 6. 剪辑 ==========")

        self._cut_script_videos()

        print("========== 7. 混音 ==========")

        self._mix_script_audio()

        print("========== 8. 拼接 ==========")

        self._concat_script_videos()

        print("========== 9. 改变分辨率 ==========")
        media_data, main_media = self._read_main_media()
        change_resolution(
            main_media["concatenated_video_path"],
            self.project_paths.changed_resolution_video,
            width=1080,
            height=1920,
            fps=30,
        )
        main_media["changed_resolution_video_path"] = str(self.project_paths.changed_resolution_video)
        self._write_media(media_data)

        print("========== 10. 加速 ==========")

        speed_up(
            main_media["changed_resolution_video_path"],
            self.project_paths.speed_up_video,
            speed=1.2,
        )
        main_media["speed_up_video_path"] = str(self.project_paths.speed_up_video)
        self._write_media(media_data)

        print("========== 11. 掩码字幕 ==========")
        region = [
        {
            "x": 100,
            "y": 600,
            "width": 200,
            "height": 100,
            "mosaic_size": 8,
        },
        {
            "x": 800,
            "y": 600,
            "width": 200,
            "height": 100,
            "mosaic_size": 8,
        },
        {
            "x": 0,
            "y": 1250,
            "width": 1080,
            "height": 70,
            "mosaic_size": 8,
        }]
        # region = [
        # {
        #     "x": 0,
        #     "y": 1150,
        #     "width": 1080,
        #     "height": 50,
        #     "mosaic_size": 8,
        # }]
        mosaic_regions(main_media["speed_up_video_path"], self.project_paths.masked_video, region)
        main_media["masked_video_path"] = str(self.project_paths.masked_video)
        self._write_media(media_data)


        print("========== 12. 导出成片音频 ==========")
        export_audio(main_media["speed_up_video_path"], self.project_paths.final_audio)
        main_media["final_audio_path"] = str(self.project_paths.final_audio)
        self._write_media(media_data)

        print("========== 13. 成片语音识别导出字幕 ==========")
        Volcengine().transcribe_audio(main_media["final_audio_path"], self.project_paths.final_subtitles)
        main_media["final_subtitles"] = {
            "srt_path": str(self.project_paths.final_subtitles["srt"]),
            "json_path": str(self.project_paths.final_subtitles["json"]),
        }
        self._write_media(media_data)

        print("========== 14. AI修正字幕 ==========")
        popup_text, _ = Ali().fix_subtitles(
            main_media["final_subtitles"]["srt_path"],
            main_media["final_subtitles"]["srt_path"],
        )

        print("========== 15. 添加字幕 ==========")
        add_subtitles(
            main_media["masked_video_path"],
            main_media["final_subtitles"]["srt_path"],
            self.project_paths.subtitle_video,
            y=90,
            font_size=10,
        )
        main_media["subtitle_video_path"] = str(self.project_paths.subtitle_video)
        self._write_media(media_data)

        print("========== 16. 添加标题和副标题 ==========")
        add_text_overlay(
            main_media["subtitle_video_path"],
            self.project_paths.text_overlay_video,
            title,
            subtitle,
            font_size_title=80,
            font_size_sub=80,
            title_y=400,
            sub_y=450,
            title_color="#FFCC00",
            sub_color="#FFCC00",
            popup_text=popup_text,
            popup_font_size=42,
            popup_color="#FFFFFF",
            popup_y=750
        )
        main_media["text_overlay_video_path"] = str(self.project_paths.text_overlay_video)
        self._write_media(media_data)

        print("========== 17. 添加 GIF 动画 ==========")
        add_gif_overlay(
            main_media["text_overlay_video_path"],
            self.project_paths.gif_overlay_video,
            Path("assets") / "like.gif",
            x=500,
            y=1500,
            scale=2.0
        )
        main_media["final_video_path"] = str(self.project_paths.gif_overlay_video)
        self._write_media(media_data)

        print("========== 18. 上传 ==========")
        if upload:
            safe_file_name = safe_filename(subtitle)
            output_path = self.project_paths.root / f"{safe_file_name}.mp4"
            shutil.copy2(main_media["final_video_path"], output_path)
            upload_to_drive(output_path, folder_name=title)
    
        print("========== 19. 上传S3 ==========")
        uuid_value = uuid.uuid4()    
        video_key = f"videos/{uuid_value}.mp4"
        s3_url = S3().upload_file(
            main_media["source_video_path"],
            video_key
        )
        print(f"视频已上传到 S3: {s3_url}")

        print("========== 20. 写入数据库 ==========")
        scene_mapping = PostCutService().save_scene_to_db(
            story_path=self.project_paths.story,
            video_url=s3_url,
            drama_title=title
        )

        apply_character_scene_mapping(self.project_paths.subtitles['json'],self.project_paths.speaker_mapping,self.project_paths.story,scene_mapping,self.project_paths.subtitles_to_db)
        PostCutService().save_subtitle_to_db(self.project_paths.subtitles_to_db,
                                             s3_url,
                                             drama_title=title)

