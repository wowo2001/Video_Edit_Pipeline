from pathlib import Path
import shutil
import json

from core.path import ProjectPaths
from services.ali import Ali
from services.postgresql import PostgresClient
from services.s3 import S3

from services.volcengine import Volcengine
from pipeline.video import concat_videos, cut_segment_video_temp
from pipeline.audio import mix_audio_segment_temp
from pipeline.story import convert_row_data_to_json, generate_cadidate_script, generate_final_script
from pipeline.video import change_resolution,speed_up,mosaic_regions,add_subtitles,add_gif_overlay,concat_segment_videos,add_text_overlay,cut_hook_video_temp
from pipeline.audio import export_audio,mix_audio_hook_temp
from core.utils import safe_filename,clear_workdir, save_scene_candidates, restore_scene_subtitle, restore_selected_subtitles, merge_scene_narration, download_scene_videos, restore_segment_subtitles,extract_hook_segment
from services.google_drive import upload_to_drive
from services.text_embedding_service import TextEmbeddingService

project_paths = ProjectPaths()
client = PostgresClient()
text_embedding_service = TextEmbeddingService()
s3_client = S3()

clear_workdir(ProjectPaths().root,ProjectPaths().vocals_path)

theme = "宋江为什么杀阎婆惜"
print("====1. 召回场景故事====")
embedding = text_embedding_service.encode(theme)
rows = client.search_scene(
    query_embedding=embedding,
    drama_title="水浒传"
)
save_scene_candidates(rows,project_paths.scene_candidate)

print("====2. AI选取场景====")
Ali().select_scene(project_paths.scene_candidate, theme, project_paths.selected_scene)

print("====3. 重现场景对白====")
restore_scene_subtitle(project_paths.selected_scene,project_paths.scene_candidate,project_paths.scene_with_subtitle,client)

print("====4. AI选择场景台词====")

with open(
    project_paths.scene_with_subtitle,
    "r",
    encoding="utf-8"
) as f:
    scenes = json.load(f)

scene_clips = []

for scene in scenes:

    result = Ali().split_scene_segment(
        theme,
        scene
    )

    scene_clips.append(
    {
        "scene_id": scene["scene_id"],
        **result
    }
)


with open(
    project_paths.scene_clips,
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        scene_clips,
        f,
        ensure_ascii=False,
        indent=2
    )

restore_segment_subtitles(
    project_paths.scene_with_subtitle,
    project_paths.scene_clips,
    project_paths.scene_selected_subtitle
)

print("====下载资源====")
download_scene_videos(project_paths.scene_selected_subtitle, project_paths.download, s3_client)
print("====生成hook====")
Ali().generate_hook(theme, project_paths.scene_selected_subtitle,project_paths.hook)
extract_hook_segment(project_paths.scene_selected_subtitle, project_paths.hook, project_paths.hook)
print("====5. AI润色解说词====")
Ali().refine_narration(project_paths.scene_selected_subtitle)


 
print("====4. tts====")
Volcengine().generate_tts_temp(project_paths.scene_selected_subtitle, project_paths.narration_audios)
Volcengine().generate_hook_tts(project_paths.hook, project_paths.narration_audios)

print("====5. 剪辑====")
cut_segment_video_temp(project_paths.scene_selected_subtitle, project_paths.clips)
cut_hook_video_temp(project_paths.hook, project_paths.clips)
print("====6. 混音====")
mix_audio_segment_temp(project_paths.scene_selected_subtitle, project_paths.final_clips)
mix_audio_hook_temp(project_paths.hook, project_paths.final_clips)
print("========== 8. 拼接 ==========")

concat_segment_videos(project_paths.scene_selected_subtitle, project_paths.hook, project_paths.concatenated_video)

print("========== 9. 改变分辨率 ==========")

change_resolution(project_paths.concatenated_video, project_paths.changed_resolution_video
                          , width=1080, height=1920, fps=30)

print("========== 10. 加速 ==========")

speed_up(project_paths.changed_resolution_video, project_paths.speed_up_video, speed=1.2)

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
    "y": 1200,
    "width": 1080,
    "height": 70,
    "mosaic_size": 8,
}]

mosaic_regions(project_paths.speed_up_video,project_paths.masked_video,region)


print("========== 12. 导出成片音频 ==========")
export_audio(project_paths.speed_up_video, project_paths.final_audio)

print("========== 13. 成片语音识别导出字幕 ==========")
Volcengine().transcribe_audio(project_paths.final_audio, project_paths.final_subtitles)

print("========== 14. AI修正字幕 ==========")
popup_text, subtitle = Ali().fix_subtitles(project_paths.final_subtitles['srt'], project_paths.final_subtitles['srt'])

print("========== 15. 添加字幕 ==========")
add_subtitles(project_paths.masked_video, project_paths.final_subtitles['srt'], project_paths.subtitle_video, y=95)

print("========== 16. 添加标题和副标题 ==========")
add_text_overlay(
    project_paths.subtitle_video,
    project_paths.text_overlay_video,
    "水浒传",
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

print("========== 17. 添加 GIF 动画 ==========")
add_gif_overlay(
    project_paths.text_overlay_video,
    project_paths.gif_overlay_video,
    Path("assets") / "like.gif",
    x=500,
    y=1500,
    scale=2.0
)

print("========== 18. 上传 ==========")
safe_file_name = safe_filename(subtitle)
output_path = project_paths.root / f"{safe_file_name}.mp4"
shutil.copy2(project_paths.gif_overlay_video, output_path)
upload_to_drive(output_path, folder_name="Test")






