from pathlib import Path
import shutil
import json
from core.utils import ms_to_seconds, read_json, write_json

from core.path import ProjectPaths
from services.ali import Ali
from services.postgresql import PostgresClient
from services.s3 import S3

from services.volcengine import Volcengine
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
from pipeline.audio import export_audio, mix_narration_audio
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


def read_search_media():
    media = read_json(project_paths.media) if project_paths.media.exists() else {}
    return media, media.setdefault("search", {"scenes": {}, "hook": {}})


def write_search_media(media):
    write_json(media, project_paths.media)


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
scenes = read_json(project_paths.scene_selected_subtitle)
scene_video_paths = download_scene_videos(scenes, project_paths.download, s3_client)
media, search_media = read_search_media()
search_media["scenes"] = {
    scene_id: {"source_video_path": video_path, "segments": {}}
    for scene_id, video_path in scene_video_paths.items()
}
write_search_media(media)
print("========== 06. 生成并提取 Hook 片段 ==========")
Ali().generate_hook(theme, project_paths.scene_selected_subtitle,project_paths.hook)
build_hook_segment(project_paths.scene_selected_subtitle, project_paths.hook, project_paths.hook)
print("========== 07. AI 生成场景解说词 ==========")
Ali().refine_narration(project_paths.scene_selected_subtitle)


print("========== 08. 生成场景与 Hook 的 TTS ==========")
tts = Volcengine()
hook = read_json(project_paths.hook)
hook_audio_path = project_paths.narration_audios / "hook.mp3"
hook["hook_length"] = tts.generate_tts(hook["hook_narration"], hook_audio_path)
write_json(hook, project_paths.hook, ensure_ascii=False, indent=2)

scenes = read_json(project_paths.scene_selected_subtitle)
media, search_media = read_search_media()
for scene in scenes:
    scene_media = search_media["scenes"][str(scene["scene_id"])]
    for segment in scene.get("segments", []):
        text = segment.get("narration")
        if not text:
            continue

        audio_path = (
            project_paths.narration_audios
            / f"scene_{scene['scene_id']}_segment_{segment['segment_id']}.mp3"
        )
        segment["narration_length"] = tts.generate_tts(text, audio_path)
        scene_media["segments"][str(segment["segment_id"])] = {
            "narration_audio_path": str(audio_path)
        }

search_media["hook"]["narration_audio_path"] = str(hook_audio_path)
write_json(scenes, project_paths.scene_selected_subtitle, ensure_ascii=False, indent=2)
write_search_media(media)

print("========== 09. 按已选字幕裁剪场景与 Hook 视频 ==========")
scenes = read_json(project_paths.scene_selected_subtitle)
media, search_media = read_search_media()
for scene in scenes:
    scene_media = search_media["scenes"][str(scene["scene_id"])]
    input_video = Path(scene_media["source_video_path"])
    if not input_video.exists():
        print(f"[ERROR] 找不到视频: {input_video}")
        continue
    for segment in scene.get("segments", []):
        if not segment.get("subtitles"):
            continue
        segment_media = scene_media["segments"].setdefault(str(segment["segment_id"]), {})
        segment_media["clip_video_path"] = str(
            cut_video(
                input_video,
                segment["subtitles"],
                ms_to_seconds(segment.get("narration_length", 0)),
                project_paths.clips
                / f"scene_{scene['scene_id']}_segment_{segment['segment_id']}.mp4",
            )
        )
write_search_media(media)

hook = read_json(project_paths.hook)
media, search_media = read_search_media()
hook_scene_media = search_media["scenes"][str(hook["scene_id"])]
search_media["hook"]["clip_video_path"] = str(
    cut_video(
        Path(hook_scene_media["source_video_path"]),
        hook["subtitles"],
        ms_to_seconds(hook.get("hook_length", 0)),
        project_paths.clips / "hook.mp4",
        narration_position="after",
        keep_gaps=True,
    )
)
write_search_media(media)
print("========== 10. 为场景与 Hook 混入解说音频 ==========")
scenes = read_json(project_paths.scene_selected_subtitle)
media, search_media = read_search_media()
for scene in scenes:
    for segment in scene.get("segments", []):
        segment_media = search_media["scenes"][str(scene["scene_id"])]["segments"][str(segment["segment_id"])]
        video_path = Path(segment_media["clip_video_path"])
        narration_audio_path = Path(segment_media["narration_audio_path"])
        if not video_path.exists():
            print(f"[ERROR] 找不到视频: {video_path}")
            continue
        if not narration_audio_path.exists():
            print(f"[ERROR] 找不到旁白: {narration_audio_path}")
            continue

        output_path = (
            project_paths.final_clips
            / f"scene_{scene['scene_id']}_segment_{segment['segment_id']}_final.mp4"
        )
        mix_narration_audio(
            video_path,
            narration_audio_path,
            output_path,
        )
        segment_media["final_video_path"] = str(output_path)
write_search_media(media)

hook = read_json(project_paths.hook)
hook_output_path = project_paths.final_clips / "hook_final.mp4"
media, search_media = read_search_media()
hook_video_path = Path(search_media["hook"]["clip_video_path"])
hook_audio_path = Path(search_media["hook"]["narration_audio_path"])
if not hook_video_path.exists():
    print(f"[ERROR] 找不到hook视频: {hook_video_path}")
elif not hook_audio_path.exists():
    print(f"[ERROR] 找不到hook音频: {hook_audio_path}")
else:
    mix_narration_audio(
        hook_video_path,
        hook_audio_path,
        hook_output_path,
        alignment="end",
    )
    search_media["hook"]["final_video_path"] = str(hook_output_path)
    write_search_media(media)
print("========== 11. 拼接 Hook 与场景成片 ==========")
scenes = read_json(project_paths.scene_selected_subtitle)
media, search_media = read_search_media()
video_paths = [search_media["hook"]["final_video_path"]]
for scene in scenes:
    video_paths.extend(
        search_media["scenes"][str(scene["scene_id"])]["segments"][str(segment["segment_id"])]["final_video_path"]
        for segment in sorted(
            scene.get("segments", []),
            key=lambda item: item["segment_id"],
        )
    )
concat_video_paths(
    video_paths,
    project_paths.concatenated_video,
    project_paths.root / "final_video_concat_list.txt",
)
search_media["concatenated_video_path"] = str(project_paths.concatenated_video)
write_search_media(media)



print("========== 12. 加速成片 ==========")

speed_up(search_media["concatenated_video_path"], project_paths.speed_up_video, speed=1.2)
search_media["speed_up_video_path"] = str(project_paths.speed_up_video)
write_search_media(media)

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

mosaic_regions(search_media["speed_up_video_path"], project_paths.masked_video, region)
search_media["masked_video_path"] = str(project_paths.masked_video)
write_search_media(media)


print("========== 14. 导出成片音频 ==========")
export_audio(search_media["speed_up_video_path"], project_paths.final_audio)
search_media["final_audio_path"] = str(project_paths.final_audio)
write_search_media(media)

print("========== 15. 识别成片语音并生成字幕 ==========")
Volcengine().transcribe_audio(search_media["final_audio_path"], project_paths.final_subtitles)
search_media["final_subtitles"] = {
    "srt_path": str(project_paths.final_subtitles["srt"]),
    "json_path": str(project_paths.final_subtitles["json"]),
}
write_search_media(media)

print("========== 16. AI 修正成片字幕 ==========")
popup_text, _ = ai.fix_subtitles(
    search_media["final_subtitles"]["srt_path"],
    search_media["final_subtitles"]["srt_path"],
)
safe_file_name = safe_filename(subtitle)

print("========== 17. 添加字幕并保留原比例成片 ==========")
add_subtitles(
    search_media["masked_video_path"],
    search_media["final_subtitles"]["srt_path"],
    project_paths.subtitle_video,
    y=40,
    font_size=30,
)
search_media["subtitle_video_path"] = str(project_paths.subtitle_video)
output_path_origin = project_paths.root / f"{safe_file_name}_origin.mp4"
shutil.copy(search_media["subtitle_video_path"], output_path_origin)
search_media["subtitle_video_origin_path"] = str(output_path_origin)
write_search_media(media)

print("========== 18. 转换为竖屏分辨率 ==========")

change_resolution(
    search_media["subtitle_video_path"],
    project_paths.changed_resolution_video,
    width=1080,
    height=1920,
    fps=30,
)
search_media["changed_resolution_video_path"] = str(project_paths.changed_resolution_video)
write_search_media(media)

print("========== 19. 添加标题、副标题与弹幕文案 ==========")
add_text_overlay(
    search_media["changed_resolution_video_path"],
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
search_media["text_overlay_video_path"] = str(project_paths.text_overlay_video)
write_search_media(media)

print("========== 20. 添加 GIF 动画 ==========")
add_gif_overlay(
    search_media["text_overlay_video_path"],
    project_paths.gif_overlay_video,
    Path("assets") / "like.gif",
    x=500,
    y=1500,
    scale=2.0
)
search_media["final_video_path"] = str(project_paths.gif_overlay_video)
write_search_media(media)

print("========== 21. 导出并上传成片 ==========")
output_path = project_paths.root / f"{safe_file_name}.mp4"
shutil.copy2(search_media["final_video_path"], output_path)
search_media["exported_video_path"] = str(output_path)
write_search_media(media)
upload_to_drive(output_path, folder_name="雍正王朝解析")
upload_to_drive(output_path_origin, folder_name="雍正王朝解析")
