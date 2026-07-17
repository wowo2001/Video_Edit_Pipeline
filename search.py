from pathlib import Path
import shutil

from core.path import ProjectPaths
from services.ali import Ali
from services.postgresql import PostgresClient
from services.s3 import S3

from services.volcengine import Volcengine
from pipeline.video import concat_videos, cut_clips_temp
from pipeline.audio import mix_audio_temp
from pipeline.story import convert_row_data_to_json, generate_cadidate_script, generate_final_script
from pipeline.video import change_resolution,speed_up,mosaic_regions,add_subtitles,add_gif_overlay
from pipeline.audio import export_audio
from core.utils import safe_filename,clear_workdir
from services.google_drive import upload_to_drive

project_paths = ProjectPaths()
client = PostgresClient()
s3_client = S3()

# clear_workdir(ProjectPaths().root,ProjectPaths().vocals_path)
# print("====1. 导出故事====")
# rows = client.search_story(person="高俅", episode="水浒传")
# convert_row_data_to_json(rows, project_paths.story)

# print("====2. 故事大纲====")
# Ali().generate_script_temp(project_paths.script, project_paths.story)
generate_cadidate_script(project_paths.script, project_paths.candidate_metadata, 20, client)

print("====3. 选定脚本====")
Ali().generate_script_final(project_paths.script)
generate_final_script(project_paths.script, project_paths.candidate_metadata, project_paths.clips,s3_client)
 
print("====4. tts====")
Volcengine().generate_tts_temp(project_paths.script, project_paths.narration_audios)

print("====5. 剪辑====")
cut_clips_temp(project_paths.script, project_paths.clips)
print("====6. 混音====")
mix_audio_temp(project_paths.clips, project_paths.narration_audios, project_paths.script, project_paths.final_clips)
print("========== 8. 拼接 ==========")

concat_videos(project_paths.final_clips, project_paths.concatenated_video)

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






