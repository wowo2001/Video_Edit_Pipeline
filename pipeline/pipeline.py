
import shutil

from core.path import ProjectPaths
from core.utils import safe_filename, clear_workdir, strip_srt, apply_speaker_mapping, apply_timeline
from core.whisper import Whisper
from pipeline.audio import export_audio,mix_audio, export_all_audio
from pipeline.download import download_video
from pipeline.video import add_gif_overlay, add_subtitles, change_resolution, cut_video, concat_videos, mask_sub, speed_up, add_text_overlay, mosaic_regions
from services.chatgpt import ChatGPT
from services.ali import Ali
from services.volcengine import Volcengine
from services.google_drive import upload_to_drive
from pathlib import Path
from core.demucs import extract_vocals_demucs
from core.speechbrain import SpeechBrain


class AutoVideoPipeline:

    def __init__(self):
        self.project_paths = ProjectPaths()

    def run(self, urls, title, subtitle = None, upload=False):

        print("========== 1. 下载视频 ==========")

        download_video(urls, self.project_paths.video)

        print("========== 2. 提取音频 ==========")

        export_all_audio(self.project_paths.origin, self.project_paths.audio)

        print("========== 3. 字幕识别 ==========")
        Volcengine().transcribe_audio(self.project_paths.audio, self.project_paths.subtitles)
        # Whisper().transcribe(self.project_paths.audio, self.project_paths.subtitles)

        print("========== 3.1 语音分类 ==========")
        SpeechBrain().diarize(self.project_paths.audio, self.project_paths.subtitles,threshold=0.75,min_cluster_ratio=0.01)

        print("========== 3.2 人物识别 ==========")
        strip_srt(self.project_paths.subtitles['srt'], self.project_paths.subtitles['stripped_srt'], keep_index=False)
        Ali().recognise_speaker(self.project_paths.subtitles['stripped_srt'], self.project_paths.speaker_mapping)
        apply_speaker_mapping(self.project_paths.subtitles['srt'], self.project_paths.speaker_mapping)
        

        print("========== 4. GPT 脚本 ==========")
        strip_srt(self.project_paths.subtitles['srt'], self.project_paths.subtitles['stripped_srt'], keep_index=True)
        Ali().generate_script(self.project_paths.subtitles['stripped_srt'], self.project_paths.script)
        apply_timeline(self.project_paths.script, self.project_paths.subtitles['json'])

        print("========== 4.1 AI 脚本改进 ==========")
        apply_speaker_mapping_to_script(self.project_paths.script, self.project_paths.speaker_mapping)
        Ali().review_script(self.project_paths.script)

        print("========== 5. TTS ==========")

        Volcengine().generate_tts(self.project_paths.script, self.project_paths.narration_audios)

        print("========== 6. 剪辑 ==========")

        cut_video(self.project_paths.video, self.project_paths.clips, self.project_paths.script)

        print("========== 7. 混音 ==========")

        mix_audio(self.project_paths.clips, self.project_paths.narration_audios, self.project_paths.script, self.project_paths.final_clips)

        print("========== 8. 拼接 ==========")

        concat_videos(self.project_paths.final_clips, self.project_paths.concatenated_video)

        print("========== 9. 改变分辨率 ==========")

        change_resolution(self.project_paths.concatenated_video, self.project_paths.changed_resolution_video
                          , width=1080, height=1920, fps=30)

        print("========== 10. 加速 ==========")

        speed_up(self.project_paths.changed_resolution_video, self.project_paths.speed_up_video, speed=1.3)

        print("========== 11. 掩码字幕 ==========")
        region = [
        {
            "x": 100,
            "y": 500,
            "width": 200,
            "height": 200,
            "mosaic_size": 8,
        },
        {
            "x": 800,
            "y": 500,
            "width": 200,
            "height": 200,
            "mosaic_size": 8,
        },
        {
            "x": 0,
            "y": 1250,
            "width": 1080,
            "height": 50,
            "mosaic_size": 8,
        }]
        mosaic_regions(self.project_paths.speed_up_video,self.project_paths.masked_video,region)


        print("========== 12. 导出成片音频 ==========")
        export_audio(self.project_paths.speed_up_video, self.project_paths.final_audio)

        print("========== 13. 成片语音识别导出字幕 ==========")
        Volcengine().transcribe_audio(self.project_paths.final_audio, self.project_paths.final_subtitles)

        print("========== 14. AI修正字幕 ==========")
        popup_text, subtitle = Ali().fix_subtitles(self.project_paths.final_subtitles['srt'], self.project_paths.final_subtitles['srt'])

        print("========== 15. 添加字幕 ==========")
        add_subtitles(self.project_paths.masked_video, self.project_paths.final_subtitles['srt'], self.project_paths.subtitle_video, y=95)

        print("========== 16. 添加标题和副标题 ==========")
        add_text_overlay(
            self.project_paths.subtitle_video,
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
            popup_y=600
        )

        print("========== 17. 添加 GIF 动画 ==========")
        add_gif_overlay(
            self.project_paths.text_overlay_video,
            self.project_paths.gif_overlay_video,
            Path("assets") / "like.gif",
            x=500,
            y=1500,
            scale=2.0
        )

        print("========== 18. 上传 ==========")
        if upload:
            safe_file_name = safe_filename(subtitle)
            output_path = self.project_paths.root / f"{safe_file_name}.mp4"
            shutil.copy2(self.project_paths.gif_overlay_video, output_path)
            upload_to_drive(output_path, folder_name=title)
