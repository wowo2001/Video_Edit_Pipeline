from core.cmd import run_cmd
from core.ffmpeg import extract_audio,get_duration, mix_start_aligned, mix_start_aligned
from core.ffmpeg import mix_end_aligned
import json


from pipeline import video
def export_audio(input_path, output_path):

    if output_path.exists():
        output_path.unlink()

    extract_audio(input_path, output_path)

    print(f"\n✅ 音频导出完成: {output_path}")

def mix_audio(video_path, narration_audio_path, script_path, output_path):
    clip_video_path = video_path / "hook.mp4"
    audio_path = narration_audio_path / "hook.mp3"
    final_output_path = output_path / "hook_final.mp4"
    _mix_hook_audio(clip_video_path, audio_path, final_output_path)

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data["clips"]:
        place = item["place"]
        clip_video_path = video_path / f"clip_{place}.mp4"
        print(f"正在处理剪辑 {clip_video_path} 的混音...")
        clip_audio = narration_audio_path / f"clip_{place}.mp3"
        clip_output = output_path / f"clip_{place}_final.mp4"
        _mix_clip_audio(clip_video_path, clip_audio, clip_output)


    

def _mix_hook_audio(video_path, narration_audio_path, output_path):    
    video_dur = get_duration(video_path)
    voice_dur = get_duration(narration_audio_path)
    mix_end_aligned(video_path, narration_audio_path, output_path, voice_dur, video_dur)

def _mix_clip_audio(video_path, narration_audio_path, output_path):    
    voice_dur = get_duration(narration_audio_path)
    print(f"视频路径: {video_path}, 旁白路径: {narration_audio_path}, 输出路径: {output_path}, 旁白时长: {voice_dur}")
    mix_start_aligned(video_path, narration_audio_path, output_path, voice_dur)