from pathlib import Path
import shutil
import json
from core.utils import read_json, write_json

from core.path import ProjectPaths
from services.ali import Ali
from services.postgresql import PostgresClient
from services.s3 import S3

from services.volcengine import Volcengine
from pipeline.video import concat_videos, cut_segment_video_temp
from pipeline.audio import mix_audio_segment_temp
from pipeline.video import change_resolution,speed_up,mosaic_regions,add_subtitles,add_gif_overlay,concat_segment_videos,add_text_overlay,cut_hook_video_temp
from pipeline.audio import export_audio,mix_audio_hook_temp
from core.utils import safe_filename, clear_workdir
from pipeline.download import download_scene_videos
from pipeline.scenes import (
    attach_subtitles_to_segments,
    attach_subtitles_to_selected_scenes,
    build_hook_segment,
    save_scene_candidates,
)
from services.google_drive import upload_to_drive
from services.text_embedding_service import TextEmbeddingService
from services.chatgpt import ChatGPT

project_paths = ProjectPaths()
client = PostgresClient()
text_embedding_service = TextEmbeddingService()
s3_client = S3()

# clear_workdir(ProjectPaths().root,ProjectPaths().vocals_path)
search = "四阿哥"

drama_title = "雍正王朝"
ai = ChatGPT()
# ========== 01. 按语义检索候选场景（当前未启用） ==========
# embedding = text_embedding_service.encode(search)
# rows = client.search_scene(
#     query_embedding=embedding,
#     drama_title=drama_title,
#     limit = 50
# )
# save_scene_candidates(rows,project_paths.scene_candidate)

questions = read_json(project_paths.questions)
question = questions["问题"]
scene_ids = questions["场景"]
subtitle = questions["标题"]
strategy = questions["解说角度"]

scenes = []

# ========== 01. 根据任务指定的场景 ID 生成候选场景 ==========
for scene_id in scene_ids:
    row = client.search_scene_by_id(scene_id)

    if row:
        scenes.append(
            {
                "scene_id": row[0],
                "drama_title": row[1],
                "video_url": row[2],
                "title": row[3],
                "event": row[4],
                "summary": row[5]
            }
        )

output_path = Path(project_paths.scene_candidate)

write_json(
        scenes,
        output_path,
        ensure_ascii=False,
        indent=2
    )
print(f"✅ 候选场景已保存: {output_path}")

theme = f"{question}从{strategy}角度分析解说词，结合历史背景和人物性格，深入剖析人物的动机和策略。"

print("========== 02. AI 筛选解说场景 ==========")
ai.select_scene(project_paths.scene_candidate, question,theme, project_paths.selected_scene)

print("========== 03. 从数据库补全选中场景的字幕 ==========")
attach_subtitles_to_selected_scenes(
    project_paths.selected_scene,
    project_paths.scene_candidate,
    project_paths.scene_with_subtitle,
    client,
)

print("========== 04. AI 拆分场景片段并选取对白 ==========")

scenes = read_json(project_paths.scene_with_subtitle)
scene_clips = []

for scene in scenes:

    result = ai.split_scene_segment(
        theme,
        scene
    )

    scene_clips.append(
    {
        "scene_id": scene["scene_id"],
        **result
    }
)


write_json(
        scene_clips,
        project_paths.scene_clips,
        ensure_ascii=False,
        indent=2
    )
attach_subtitles_to_segments(
    project_paths.scene_with_subtitle,
    project_paths.scene_clips,
    project_paths.scene_selected_subtitle
)

print("========== 05. 下载并标准化场景源视频 ==========")
download_scene_videos(project_paths.scene_selected_subtitle, project_paths.download, s3_client)
print("========== 06. 生成并提取 Hook 片段 ==========")
Ali().generate_hook(theme, project_paths.scene_selected_subtitle,project_paths.hook)
build_hook_segment(project_paths.scene_selected_subtitle, project_paths.hook, project_paths.hook)
print("========== 07. AI 生成场景解说词 ==========")
Ali().refine_narration(project_paths.scene_selected_subtitle)


print("========== 08. 生成场景与 Hook 的 TTS ==========")
Volcengine().generate_tts_temp(project_paths.scene_selected_subtitle, project_paths.narration_audios)
Volcengine().generate_hook_tts(project_paths.hook, project_paths.narration_audios)

print("========== 09. 按已选字幕裁剪场景与 Hook 视频 ==========")
cut_segment_video_temp(project_paths.scene_selected_subtitle, project_paths.clips)
cut_hook_video_temp(project_paths.hook, project_paths.clips)
print("========== 10. 为场景与 Hook 混入解说音频 ==========")
mix_audio_segment_temp(project_paths.scene_selected_subtitle, project_paths.final_clips)
mix_audio_hook_temp(project_paths.hook, project_paths.final_clips)
print("========== 11. 拼接 Hook 与场景成片 ==========")

concat_segment_videos(project_paths.scene_selected_subtitle, project_paths.hook, project_paths.concatenated_video)



print("========== 12. 加速成片 ==========")

speed_up(project_paths.concatenated_video, project_paths.speed_up_video, speed=1.2)

print("========== 13. 遮挡原视频字幕 ==========")
region = [
{
    "x": 200,
    "y": 50,
    "width": 200,
    "height": 100,
    "mosaic_size": 10,
},
{
    "x": 850,
    "y": 50,
    "width": 200,
    "height": 100,
    "mosaic_size": 10,
}]

mosaic_regions(project_paths.speed_up_video,project_paths.masked_video,region)


print("========== 14. 导出成片音频 ==========")
export_audio(project_paths.speed_up_video, project_paths.final_audio)

print("========== 15. 识别成片语音并生成字幕 ==========")
Volcengine().transcribe_audio(project_paths.final_audio, project_paths.final_subtitles)

print("========== 16. AI 修正成片字幕 ==========")
popup_text, _ = ai.fix_subtitles(project_paths.final_subtitles['srt'], project_paths.final_subtitles['srt'])
safe_file_name = safe_filename(subtitle)

print("========== 17. 添加字幕并保留原比例成片 ==========")
add_subtitles(project_paths.masked_video, project_paths.final_subtitles['srt'], project_paths.subtitle_video, y=40, font_size=30)
output_path_origin = project_paths.root / f"{safe_file_name}_origin.mp4"
shutil.copy(project_paths.subtitle_video, output_path_origin)

print("========== 18. 转换为竖屏分辨率 ==========")

change_resolution(project_paths.subtitle_video, project_paths.changed_resolution_video
                          , width=1080, height=1920, fps=30)

print("========== 19. 添加标题、副标题与弹幕文案 ==========")
add_text_overlay(
    project_paths.changed_resolution_video,
    project_paths.text_overlay_video,
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
    popup_y=750
)

print("========== 20. 添加 GIF 动画 ==========")
add_gif_overlay(
    project_paths.text_overlay_video,
    project_paths.gif_overlay_video,
    Path("assets") / "like.gif",
    x=500,
    y=1500,
    scale=2.0
)

print("========== 21. 导出并上传成片 ==========")
output_path = project_paths.root / f"{safe_file_name}.mp4"
shutil.copy2(project_paths.gif_overlay_video, output_path)
upload_to_drive(output_path, folder_name="雍正王朝解析")
upload_to_drive(output_path_origin, folder_name="雍正王朝解析")
