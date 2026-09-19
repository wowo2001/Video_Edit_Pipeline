import shutil
from pathlib import Path

from core.ffmpeg import get_duration
from core.llm_cost import finish_llm_cost_report, start_llm_cost_report
from core.path import ProjectPaths
from core.utils import ms_to_seconds, read_json, safe_filename, write_json
from pipeline.audio import (
    export_audio,
    mix_background_music,
    mix_background_narration_audio,
    mix_narration_audio,
    resolve_background_music,
)
from pipeline.download import download_scene_videos
from pipeline.scenes import (
    attach_subtitles_to_segments,
    attach_subtitles_to_selected_scenes,
    build_hook_segment,
    normalize_segment_type,
    NARRATION_ONLY,
)
from pipeline.video import (
    add_gif_overlay,
    add_subtitles,
    add_text_overlay,
    change_resolution,
    concat_video_paths,
    cut_video,
    cut_video_range,
    fit_forward_video_range,
    mosaic_regions,
)
from services.chatgpt import ChatGPT
from services.postgresql import PostgresClient
from services.s3 import S3
from services.volcengine import Volcengine


class SearchPipeline:
    def __init__(self, project_paths=None):
        self.paths = project_paths or ProjectPaths()
        start_llm_cost_report(self.paths.llm_cost_report)
        self.ai = ChatGPT(usage_report_path=self.paths.llm_cost_report)
        self.database = PostgresClient()
        self.s3 = S3()
        self.tts = Volcengine()
        self.background_music = None
        self.background_music_volume = None

    def _read_media(self):
        media = read_json(self.paths.media) if self.paths.media.exists() else {}
        return media, media.setdefault("search", {"scenes": {}, "hook": {}})

    def _write_media(self, media):
        write_json(media, self.paths.media)

    @staticmethod
    def _has_question_outro_capacity(input_video, dialogue_end, question_duration):
        remaining_duration = get_duration(input_video) - dialogue_end
        return remaining_duration >= question_duration, remaining_duration

    def _load_task(self, task):
        question = task.get("问题") or task.get("question")
        strategy = task.get("解说角度") or task.get("strategy")
        scene_ids = task.get("场景") or task.get("scene_ids")
        subtitle = task.get("标题") or task.get("subtitle")
        if not all([question, strategy, scene_ids, subtitle]):
            raise ValueError(
                "Search task 必须包含 问题、解说角度、场景、标题 "
                "（也支持 question、strategy、scene_ids、subtitle）。"
            )
        theme = (
            f"{question}从{strategy}角度分析解说词，"
            "结合历史背景和人物性格，深入剖析人物的动机和策略。"
        )
        return question, scene_ids, subtitle, theme

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
        scenes = read_json(self.paths.scene_with_subtitle)
        for scene in scenes:
            scene_clips.append(
                {
                    "scene_id": scene["scene_id"],
                    **self.ai.split_scene_segment(theme, scene),
                }
            )

        ending_scene = next(
            (scene for scene in reversed(scenes) if scene.get("audience_question")),
            None,
        )
        if ending_scene:
            ending_plan = next(
                plan for plan in scene_clips if plan["scene_id"] == ending_scene["scene_id"]
            )
            if not ending_plan.get("segments"):
                raise ValueError("结尾场景必须至少包含一个 segment 才能添加 audience_question")
            ending_plan["segments"][-1]["audience_question"] = ending_scene[
                "audience_question"
            ]

        write_json(scene_clips, self.paths.scene_clips, ensure_ascii=False, indent=2)
        attach_subtitles_to_segments(
            self.paths.scene_with_subtitle,
            self.paths.scene_clips,
            self.paths.scene_selected_subtitle,
        )

    def _download_scene_sources(self):
        scenes = read_json(self.paths.scene_selected_subtitle)
        video_paths = download_scene_videos(
            scenes,
            self.paths.search_download_cache,
            self.s3,
        )

        media, search_media = self._read_media()
        search_media["scenes"] = {
            scene_id: {"source_video_path": video_path, "segments": {}}
            for scene_id, video_path in video_paths.items()
        }
        self._write_media(media)

    def _generate_hook_and_narration(self, theme, advertisement=None):
        self.ai.generate_hook(theme, self.paths.scene_selected_subtitle, self.paths.hook)
        build_hook_segment(
            self.paths.scene_selected_subtitle,
            self.paths.hook,
            self.paths.hook,
        )
        if advertisement:
            self.ai.refine_narration(
                self.paths.scene_selected_subtitle, advertisement=advertisement,
            )
        else:
            self.ai.refine_narration(self.paths.scene_selected_subtitle)

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
                audience_question = segment.get("audience_question")
                if audience_question:
                    question_audio_path = self.paths.narration_audios / (
                        f"scene_{scene['scene_id']}_segment_{segment['segment_id']}_question.mp3"
                    )
                    segment["audience_question_length"] = self.tts.generate_tts(
                        audience_question,
                        question_audio_path,
                    )
                    scene_media["segments"][str(segment["segment_id"])].update(
                        {
                            "audience_question_audio_path": str(question_audio_path),
                        }
                    )

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
                output_path = self.paths.clips / (
                    f"scene_{scene['scene_id']}_segment_{segment['segment_id']}.mp4"
                )
                segment_media = scene_media["segments"].setdefault(
                    str(segment["segment_id"]),
                    {},
                )
                segment_type = normalize_segment_type(segment.get("type", "with_dialogue"))
                narration_duration = ms_to_seconds(
                    segment.get("narration_length", 0)
                )
                segment_media["type"] = segment_type

                if segment_type == NARRATION_ONLY:
                    visual_subtitles = segment.get("visual_subtitles")
                    if not visual_subtitles:
                        print(
                            "[ERROR] narration_only segment 缺少定位字幕: "
                            f"scene {scene['scene_id']} segment {segment['segment_id']}"
                        )
                        continue
                    anchor_start = ms_to_seconds(visual_subtitles[0]["start_time"])
                    visual_start, visual_end = fit_forward_video_range(
                        anchor_start,
                        narration_duration,
                        get_duration(input_video),
                    )
                    segment_media["clip_video_path"] = str(
                        cut_video_range(
                            input_video,
                            output_path,
                            visual_start,
                            visual_end,
                        )
                    )
                    segment_media["narration_visual_range"] = {
                        "start": visual_start,
                        "end": visual_end,
                    }
                    content_end = visual_end
                else:
                    subtitles = segment.get("subtitles")
                    if not subtitles:
                        print(
                            "[ERROR] with_dialogue segment 缺少原声字幕: "
                            f"scene {scene['scene_id']} segment {segment['segment_id']}"
                        )
                        continue
                    segment_media["clip_video_path"] = str(
                        cut_video(
                            input_video,
                            subtitles,
                            narration_duration,
                            output_path,
                        )
                    )
                    content_end = ms_to_seconds(subtitles[-1]["end_time"])

                audience_question_duration = ms_to_seconds(
                    segment.get("audience_question_length", 0)
                )
                if audience_question_duration:
                    question_video_path = self.paths.clips / (
                        f"scene_{scene['scene_id']}_segment_{segment['segment_id']}_question.mp4"
                    )
                    question_start = content_end
                    has_capacity, remaining_duration = self._has_question_outro_capacity(
                        input_video,
                        question_start,
                        audience_question_duration,
                    )
                    if has_capacity:
                        segment_media["audience_question_video_path"] = str(
                            cut_video_range(
                                input_video,
                                question_video_path,
                                question_start,
                                question_start + audience_question_duration,
                            )
                        )
                    else:
                        segment_media.pop("audience_question_audio_path", None)
                        segment_media.pop("audience_question_video_path", None)
                        segment_media["audience_question_skipped_reason"] = (
                            "源视频在最后一句原声后仅剩 "
                            f"{max(0, remaining_duration):.3f} 秒，不足以播放 "
                            f"{audience_question_duration:.3f} 秒的问题。"
                        )
                        print(
                            "[WARN] 跳过结尾问题："
                            f"scene {scene['scene_id']} segment {segment['segment_id']} "
                            f"剩余画面 {max(0, remaining_duration):.3f}s，"
                            f"问题需要 {audience_question_duration:.3f}s"
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
                question_audio_path = segment_media.get("audience_question_audio_path")
                if question_audio_path:
                    narration_video_path = self.paths.final_clips / (
                        f"scene_{scene['scene_id']}_segment_{segment['segment_id']}_narration.mp4"
                    )
                    question_video_path = Path(
                        segment_media["audience_question_video_path"]
                    )
                    question_mix_video_path = self.paths.final_clips / (
                        f"scene_{scene['scene_id']}_segment_{segment['segment_id']}_question.mp4"
                    )
                    if normalize_segment_type(segment.get("type", "with_dialogue")) == NARRATION_ONLY:
                        mix_background_narration_audio(
                            video_path,
                            audio_path,
                            narration_video_path,
                        )
                    else:
                        mix_narration_audio(
                            video_path,
                            audio_path,
                            narration_video_path,
                        )
                    mix_narration_audio(
                        question_video_path,
                        Path(question_audio_path),
                        question_mix_video_path,
                    )
                    concat_video_paths(
                        [narration_video_path, question_mix_video_path],
                        output_path,
                        self.paths.root / (
                            f"scene_{scene['scene_id']}_segment_{segment['segment_id']}_final_concat.txt"
                        ),
                    )
                    narration_video_path.unlink(missing_ok=True)
                    question_mix_video_path.unlink(missing_ok=True)
                else:
                    if normalize_segment_type(segment.get("type", "with_dialogue")) == NARRATION_ONLY:
                        mix_background_narration_audio(
                            video_path,
                            audio_path,
                            output_path,
                        )
                    else:
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

    def _prepare_post_processing_video(self):
        media, search_media = self._read_media()
        source_video = search_media["concatenated_video_path"]
        search_media.pop("speed_up_video_path", None)
        search_media.pop("post_speed_video_path", None)
        search_media["subtitle_source_video_path"] = source_video
        search_media["post_processing_video_path"] = source_video
        search_media.pop("background_music", None)
        if self.background_music:
            music = resolve_background_music(self.background_music)
            volume = (
                self.background_music_volume
                if self.background_music_volume is not None
                else music.get("default_volume", 0.08)
            )
            mix_background_music(
                source_video,
                music["path"],
                self.paths.background_music_video,
                volume,
            )
            search_media["post_processing_video_path"] = str(self.paths.background_music_video)
            search_media["background_music"] = {
                "id": music["id"],
                "name": music["name"],
                "source_audio_path": str(music["path"]),
                "volume": float(volume),
                "mixed_video_path": str(self.paths.background_music_video),
            }
        self._write_media(media)

    def _mask_original_subtitles(self):
        media, search_media = self._read_media()
        regions = [
            {"x": 200, "y": 50, "width": 200, "height": 100, "mosaic_size": 10},
            {"x": 850, "y": 50, "width": 200, "height": 100, "mosaic_size": 10},
        ]
        mosaic_regions(search_media["post_processing_video_path"], self.paths.masked_video, regions)
        search_media["masked_video_path"] = str(self.paths.masked_video)
        self._write_media(media)

    def _export_subtitle_audio(self):
        media, search_media = self._read_media()
        export_audio(search_media["subtitle_source_video_path"], self.paths.subtitle_audio)
        search_media["subtitle_audio_path"] = str(self.paths.subtitle_audio)
        self._write_media(media)

    def _transcribe_subtitle_audio(self):
        media, search_media = self._read_media()
        self.tts.transcribe_audio(search_media["subtitle_audio_path"], self.paths.final_subtitles)
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
            font_size=26,
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

    def run(self, task):
        question, scene_ids, subtitle, theme = self._load_task(task)
        advertisement = task.get("广告")
        if advertisement is not None and not isinstance(advertisement, str):
            raise ValueError("广告必须是字符串或 null")
        advertisement = advertisement.strip() if advertisement else None
        drama_title = task.get("剧名") or task.get("drama_title") or "雍正王朝"
        self.background_music = task.get("背景音乐") or task.get("background_music")
        self.background_music_volume = (
            task.get("background_music_volume")
            if task.get("background_music_volume") is not None
            else task.get("背景音乐音量")
        )

        print("========== 01. 根据任务场景生成候选场景 ==========")
        self._save_scene_candidates(scene_ids)
        print("========== 02. AI 筛选解说场景 ==========")
        self._select_scenes(question, theme)
        print("========== 03. AI 拆分场景片段并选取对白 ==========")
        self._build_segments(theme)
        print("========== 04. 下载并标准化场景源视频 ==========")
        self._download_scene_sources()
        print("========== 05. 生成 Hook 与场景解说 ==========")
        self._generate_hook_and_narration(theme, advertisement=advertisement)
        print("========== 06. 生成场景与 Hook 的 TTS ==========")
        self._generate_tts()
        print("========== 07. 按已选字幕裁剪视频 ==========")
        self._cut_videos()
        print("========== 08. 混入解说音频 ==========")
        self._mix_audio()
        print("========== 09. 拼接 Hook 与场景 ==========")
        self._concat_videos()
        print("========== 10. 准备后处理视频（Search 不加速） ==========")
        self._prepare_post_processing_video()
        print("========== 11. 遮挡原视频字幕 ==========")
        self._mask_original_subtitles()
        print("========== 12. 导出字幕识别音频（不含背景音乐） ==========")
        self._export_subtitle_audio()
        print("========== 13. 识别成片语音并生成字幕 ==========")
        self._transcribe_subtitle_audio()
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
        finish_llm_cost_report(self.paths.llm_cost_report)


def main():
    tasks = read_json(ProjectPaths().search_task_file)
    if not isinstance(tasks, list):
        raise ValueError("question.json 必须是任务对象列表。")

    print(f"📦 Total search jobs: {len(tasks)}")
    for index, task in enumerate(tasks, start=1):
        job_name = safe_filename(task.get("标题") or task.get("subtitle") or f"search_{index}")
        project_paths = ProjectPaths(Path("work") / f"{index:03d}_{job_name}")
        print(f"\n▶ Search job {index}/{len(tasks)}")
        SearchPipeline(project_paths).run(task)

    print("\n🎬 ALL SEARCH JOBS DONE")


if __name__ == "__main__":
    main()
