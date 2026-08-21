import shutil
from pathlib import Path

from core.path import ProjectPaths
from core.utils import ms_to_seconds, read_json, safe_filename, write_json
from pipeline.audio import export_audio, mix_narration_audio
from pipeline.download import download_scene_videos
from pipeline.scenes import (
    attach_subtitles_to_segments,
    attach_subtitles_to_selected_scenes,
    build_hook_segment,
)
from pipeline.video import (
    add_gif_overlay,
    add_subtitles,
    add_text_overlay,
    change_resolution,
    concat_video_paths,
    cut_video,
    mosaic_regions,
    speed_up,
)
from services.ali import Ali
from services.chatgpt import ChatGPT
from services.postgresql import PostgresClient
from services.s3 import S3
from services.volcengine import Volcengine


class SearchPipeline:
    def __init__(self, project_paths=None):
        self.paths = project_paths or ProjectPaths()
        self.ai = ChatGPT()
        self.ali = Ali()
        self.database = PostgresClient()
        self.s3 = S3()
        self.tts = Volcengine()

    def _read_media(self):
        media = read_json(self.paths.media) if self.paths.media.exists() else {}
        return media, media.setdefault("search", {"scenes": {}, "hook": {}})

    def _write_media(self, media):
        write_json(media, self.paths.media)

    def _load_task(self):
        task = read_json(self.paths.questions)
        question = task["问题"]
        strategy = task["解说角度"]
        theme = (
            f"{question}从{strategy}角度分析解说词，"
            "结合历史背景和人物性格，深入剖析人物的动机和策略。"
        )
        return question, task["场景"], task["标题"], theme

    def _save_scene_candidates(self, scene_ids):
        scenes = []
        for scene_id in scene_ids:
            row = self.database.search_scene_by_id(scene_id)
            if not row:
                continue

            scenes.append(
                {
                    "scene_id": row[0],
                    "drama_title": row[1],
                    "video_url": row[2],
                    "title": row[3],
                    "event": row[4],
                    "summary": row[5],
                }
            )

        write_json(scenes, self.paths.scene_candidate, ensure_ascii=False, indent=2)
        print(f"✅ 候选场景已保存: {self.paths.scene_candidate}")

    def _select_scenes(self, question, theme):
        self.ai.select_scene(
            self.paths.scene_candidate,
            question,
            theme,
            self.paths.selected_scene,
        )
        attach_subtitles_to_selected_scenes(
            self.paths.selected_scene,
            self.paths.scene_candidate,
            self.paths.scene_with_subtitle,
            self.database,
        )

    def _build_segments(self, theme):
        scene_clips = []
        for scene in read_json(self.paths.scene_with_subtitle):
            scene_clips.append(
                {
                    "scene_id": scene["scene_id"],
                    **self.ai.split_scene_segment(theme, scene),
                }
            )

        write_json(scene_clips, self.paths.scene_clips, ensure_ascii=False, indent=2)
        attach_subtitles_to_segments(
            self.paths.scene_with_subtitle,
            self.paths.scene_clips,
            self.paths.scene_selected_subtitle,
        )

    def _download_scene_sources(self):
        scenes = read_json(self.paths.scene_selected_subtitle)
        video_paths = download_scene_videos(scenes, self.paths.download, self.s3)

        media, search_media = self._read_media()
        search_media["scenes"] = {
            scene_id: {"source_video_path": video_path, "segments": {}}
            for scene_id, video_path in video_paths.items()
        }
        self._write_media(media)

    def _generate_hook_and_narration(self, theme):
        self.ali.generate_hook(theme, self.paths.scene_selected_subtitle, self.paths.hook)
        build_hook_segment(
            self.paths.scene_selected_subtitle,
            self.paths.hook,
            self.paths.hook,
        )
        self.ali.refine_narration(self.paths.scene_selected_subtitle)

    def _generate_tts(self):
        hook = read_json(self.paths.hook)
        hook_audio_path = self.paths.narration_audios / "hook.mp3"
        hook["hook_length"] = self.tts.generate_tts(
            hook["hook_narration"],
            hook_audio_path,
        )
        write_json(hook, self.paths.hook, ensure_ascii=False, indent=2)

        scenes = read_json(self.paths.scene_selected_subtitle)
        media, search_media = self._read_media()
        for scene in scenes:
            scene_media = search_media["scenes"][str(scene["scene_id"])]
            for segment in scene.get("segments", []):
                narration = segment.get("narration")
                if not narration:
                    continue

                audio_path = self.paths.narration_audios / (
                    f"scene_{scene['scene_id']}_segment_{segment['segment_id']}.mp3"
                )
                segment["narration_length"] = self.tts.generate_tts(
                    narration,
                    audio_path,
                )
                scene_media["segments"][str(segment["segment_id"])] = {
                    "narration_audio_path": str(audio_path)
                }

        search_media["hook"]["narration_audio_path"] = str(hook_audio_path)
        write_json(scenes, self.paths.scene_selected_subtitle, ensure_ascii=False, indent=2)
        self._write_media(media)

    def _cut_videos(self):
        scenes = read_json(self.paths.scene_selected_subtitle)
        media, search_media = self._read_media()
        for scene in scenes:
            scene_media = search_media["scenes"][str(scene["scene_id"])]
            input_video = Path(scene_media["source_video_path"])
            if not input_video.exists():
                print(f"[ERROR] 找不到视频: {input_video}")
                continue

            for segment in scene.get("segments", []):
                subtitles = segment.get("subtitles")
                if not subtitles:
                    continue

                output_path = self.paths.clips / (
                    f"scene_{scene['scene_id']}_segment_{segment['segment_id']}.mp4"
                )
                segment_media = scene_media["segments"].setdefault(
                    str(segment["segment_id"]),
                    {},
                )
                segment_media["clip_video_path"] = str(
                    cut_video(
                        input_video,
                        subtitles,
                        ms_to_seconds(segment.get("narration_length", 0)),
                        output_path,
                    )
                )

        hook = read_json(self.paths.hook)
        hook_scene = search_media["scenes"][str(hook["scene_id"])]
        search_media["hook"]["clip_video_path"] = str(
            cut_video(
                Path(hook_scene["source_video_path"]),
                hook["subtitles"],
                ms_to_seconds(hook.get("hook_length", 0)),
                self.paths.clips / "hook.mp4",
                narration_position="after",
                keep_gaps=True,
            )
        )
        self._write_media(media)

    def _mix_audio(self):
        scenes = read_json(self.paths.scene_selected_subtitle)
        media, search_media = self._read_media()
        for scene in scenes:
            scene_media = search_media["scenes"][str(scene["scene_id"])]
            for segment in scene.get("segments", []):
                segment_media = scene_media["segments"].get(str(segment["segment_id"]))
                if not segment_media:
                    continue

                video_path = Path(segment_media["clip_video_path"])
                audio_path = Path(segment_media["narration_audio_path"])
                if not video_path.exists() or not audio_path.exists():
                    print(f"[ERROR] 缺少剪辑或旁白: {video_path} / {audio_path}")
                    continue

                output_path = self.paths.final_clips / (
                    f"scene_{scene['scene_id']}_segment_{segment['segment_id']}_final.mp4"
                )
                mix_narration_audio(video_path, audio_path, output_path)
                segment_media["final_video_path"] = str(output_path)

        hook_media = search_media["hook"]
        hook_video_path = Path(hook_media["clip_video_path"])
        hook_audio_path = Path(hook_media["narration_audio_path"])
        if hook_video_path.exists() and hook_audio_path.exists():
            output_path = self.paths.final_clips / "hook_final.mp4"
            mix_narration_audio(
                hook_video_path,
                hook_audio_path,
                output_path,
                alignment="end",
            )
            hook_media["final_video_path"] = str(output_path)
        else:
            print(f"[ERROR] 缺少 hook 剪辑或旁白: {hook_video_path} / {hook_audio_path}")

        self._write_media(media)

    def _concat_videos(self):
        scenes = read_json(self.paths.scene_selected_subtitle)
        media, search_media = self._read_media()
        video_paths = [search_media["hook"]["final_video_path"]]

        for scene in scenes:
            segment_media = search_media["scenes"][str(scene["scene_id"])]["segments"]
            video_paths.extend(
                segment_media[str(segment["segment_id"])]["final_video_path"]
                for segment in sorted(
                    scene.get("segments", []),
                    key=lambda item: item["segment_id"],
                )
            )

        concat_video_paths(
            video_paths,
            self.paths.concatenated_video,
            self.paths.root / "final_video_concat_list.txt",
        )
        search_media["concatenated_video_path"] = str(self.paths.concatenated_video)
        self._write_media(media)

    def _speed_up_video(self):
        media, search_media = self._read_media()
        speed_up(search_media["concatenated_video_path"], self.paths.speed_up_video, speed=1.2)
        search_media["speed_up_video_path"] = str(self.paths.speed_up_video)
        self._write_media(media)

    def _mask_original_subtitles(self):
        media, search_media = self._read_media()
        regions = [
            {"x": 200, "y": 50, "width": 200, "height": 100, "mosaic_size": 10},
            {"x": 850, "y": 50, "width": 200, "height": 100, "mosaic_size": 10},
        ]
        mosaic_regions(search_media["speed_up_video_path"], self.paths.masked_video, regions)
        search_media["masked_video_path"] = str(self.paths.masked_video)
        self._write_media(media)

    def _export_final_audio(self):
        media, search_media = self._read_media()
        export_audio(search_media["speed_up_video_path"], self.paths.final_audio)
        search_media["final_audio_path"] = str(self.paths.final_audio)
        self._write_media(media)

    def _transcribe_final_audio(self):
        media, search_media = self._read_media()
        self.tts.transcribe_audio(search_media["final_audio_path"], self.paths.final_subtitles)
        search_media["final_subtitles"] = {
            "srt_path": str(self.paths.final_subtitles["srt"]),
            "json_path": str(self.paths.final_subtitles["json"]),
        }
        self._write_media(media)

    def _fix_final_subtitles(self):
        _, search_media = self._read_media()
        return self.ai.fix_subtitles(
            search_media["final_subtitles"]["srt_path"],
            search_media["final_subtitles"]["srt_path"],
        )[0]

    def _add_subtitles(self, subtitle):
        media, search_media = self._read_media()
        safe_name = safe_filename(subtitle)
        add_subtitles(
            search_media["masked_video_path"],
            search_media["final_subtitles"]["srt_path"],
            self.paths.subtitle_video,
            y=40,
            font_size=30,
        )
        search_media["subtitle_video_path"] = str(self.paths.subtitle_video)

        original_video = self.paths.root / f"{safe_name}_origin.mp4"
        shutil.copy(self.paths.subtitle_video, original_video)
        search_media["subtitle_video_origin_path"] = str(original_video)
        self._write_media(media)
        return safe_name, original_video

    def _change_to_vertical_video(self):
        media, search_media = self._read_media()
        change_resolution(
            search_media["subtitle_video_path"],
            self.paths.changed_resolution_video,
            width=1080,
            height=1920,
            fps=30,
        )
        search_media["changed_resolution_video_path"] = str(self.paths.changed_resolution_video)
        self._write_media(media)

    def _add_title_and_comments(self, drama_title, subtitle, popup_text):
        media, search_media = self._read_media()
        add_text_overlay(
            search_media["changed_resolution_video_path"],
            self.paths.text_overlay_video,
            drama_title,
            subtitle,
            font_size_title=80,
            font_size_sub=60,
            title_y=400,
            sub_y=450,
            title_color="#FFCC00",
            sub_color="#FFCC00",
            popup_text=popup_text,
            popup_font_size=42,
            popup_color="#FFFFFF",
            popup_y=750,
        )
        search_media["text_overlay_video_path"] = str(self.paths.text_overlay_video)
        self._write_media(media)

    def _add_gif_overlay(self):
        media, search_media = self._read_media()
        add_gif_overlay(
            search_media["text_overlay_video_path"],
            self.paths.gif_overlay_video,
            Path("assets") / "like.gif",
            x=500,
            y=1500,
            scale=2.0,
        )
        search_media["final_video_path"] = str(self.paths.gif_overlay_video)
        self._write_media(media)

    def _export_videos(self, safe_name):
        media, search_media = self._read_media()
        output_path = self.paths.root / f"{safe_name}.mp4"
        shutil.copy2(search_media["final_video_path"], output_path)
        search_media["exported_video_path"] = str(output_path)
        self._write_media(media)
        return output_path

    def run(self):
        question, scene_ids, subtitle, theme = self._load_task()
        drama_title = "雍正王朝"

        print("========== 01. 根据任务场景生成候选场景 ==========")
        self._save_scene_candidates(scene_ids)
        print("========== 02. AI 筛选解说场景 ==========")
        self._select_scenes(question, theme)
        print("========== 03. AI 拆分场景片段并选取对白 ==========")
        self._build_segments(theme)
        print("========== 04. 下载并标准化场景源视频 ==========")
        self._download_scene_sources()
        print("========== 05. 生成 Hook 与场景解说 ==========")
        self._generate_hook_and_narration(theme)
        print("========== 06. 生成场景与 Hook 的 TTS ==========")
        self._generate_tts()
        print("========== 07. 按已选字幕裁剪视频 ==========")
        self._cut_videos()
        print("========== 08. 混入解说音频 ==========")
        self._mix_audio()
        print("========== 09. 拼接 Hook 与场景 ==========")
        self._concat_videos()
        print("========== 10. 加速成片 ==========")
        self._speed_up_video()
        print("========== 11. 遮挡原视频字幕 ==========")
        self._mask_original_subtitles()
        print("========== 12. 导出成片音频 ==========")
        self._export_final_audio()
        print("========== 13. 识别成片语音并生成字幕 ==========")
        self._transcribe_final_audio()
        print("========== 14. AI 修正成片字幕 ==========")
        popup_text = self._fix_final_subtitles()
        print("========== 15. 添加字幕并保留原比例成片 ==========")
        safe_name, original_video = self._add_subtitles(subtitle)
        print("========== 16. 转换为竖屏分辨率 ==========")
        self._change_to_vertical_video()
        print("========== 17. 添加标题、副标题与弹幕文案 ==========")
        self._add_title_and_comments(drama_title, subtitle, popup_text)
        print("========== 18. 添加 GIF 动画 ==========")
        self._add_gif_overlay()
        print("========== 19. 导出成片 ==========")
        output_path = self._export_videos(safe_name)

        from services.google_drive import upload_to_drive

        print("========== 20. 上传成片 ==========")
        upload_to_drive(output_path, folder_name=f"{drama_title}解析")
        upload_to_drive(original_video, folder_name=f"{drama_title}解析")


if __name__ == "__main__":
    SearchPipeline().run()
