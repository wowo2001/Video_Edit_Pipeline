from core.cmd import run_cmd
from core.ffmpeg import extract_audio,get_duration, mix_start_aligned, mix_start_aligned
from core.ffmpeg import mix_end_aligned,concat_mp3s
from core.demucs import extract_vocals_demucs
from core.path import ProjectPaths
import json


from pipeline import video
def export_all_audio(input_path, output_path):
    mp4_files = sorted(input_path.glob("*.mp4"),
    key=lambda p: int(p.stem))

    if not mp4_files:
        raise FileNotFoundError(f"No mp4 files found in {input_path}")

    vocal_files = []

    for mp4_file in mp4_files:
        mp3_file = mp4_file.with_suffix(".mp3")

        print(f"Extracting: {mp4_file.name}")

        if not mp3_file.exists():
            extract_audio(mp4_file, mp3_file)

        print(f"Separating vocals: {mp3_file.name}")

        extract_vocals_demucs(
            mp3_file,
            ProjectPaths().vocals_path / mp3_file.stem,
        )

        vocal_files.append(mp3_file)

    filelist = input_path / "mp3_list.txt"

    with open(filelist, "w", encoding="utf-8") as f:
        for mp3 in vocal_files:
            f.write(f"file '{mp3.absolute()}'\n")

    concat_mp3s(filelist, output_path)

    print(f"\n✅ 音频导出完成: {output_path}")

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

def mix_audio_temp(video_path, narration_audio_path, script_path, output_path):

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)


    for item in data:

        place = item["place"]

        clip_video_path = (
            video_path /
            f"clip_{place}.mp4"
        )

        clip_audio = (
            narration_audio_path /
            f"clip_{place}.mp3"
        )

        clip_output = (
            output_path /
            f"clip_{place}_final.mp4"
        )


        print(
            f"正在混音: {clip_video_path}"
        )


        _mix_clip_audio(
            clip_video_path,
            clip_audio,
            clip_output
        )