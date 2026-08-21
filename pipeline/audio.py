from pathlib import Path

from core.ffmpeg import extract_audio, mix_narration
from core.utils import read_json, write_json


def export_audio(input_path, output_path):
    if output_path.exists():
        output_path.unlink()

    extract_audio(input_path, output_path)
    print(f"\n✅ 音频导出完成: {output_path}")


def mix_audio(video_path, narration_audio_path, script_path, output_path):
    _mix_narration_audio(
        video_path / "hook.mp4",
        narration_audio_path / "hook.mp3",
        output_path / "hook_final.mp4",
        alignment="end",
    )

    for item in read_json(script_path)["clips"]:
        place = item["place"]
        clip_video_path = video_path / f"clip_{place}.mp4"
        clip_audio_path = narration_audio_path / f"clip_{place}.mp3"
        clip_output_path = output_path / f"clip_{place}_final.mp4"
        print(f"正在处理剪辑 {clip_video_path} 的混音...")
        _mix_narration_audio(clip_video_path, clip_audio_path, clip_output_path)


def _mix_narration_audio(video_path, narration_audio_path, output_path, alignment="start"):
    print(f"视频路径: {video_path}, 旁白路径: {narration_audio_path}, 输出路径: {output_path}")
    mix_narration(video_path, narration_audio_path, output_path, alignment=alignment)


def mix_audio_segment_temp(scene_path, output_path):
    output_path.mkdir(parents=True, exist_ok=True)
    scenes = read_json(scene_path)

    for scene in scenes:
        scene_id = scene["scene_id"]
        for segment in scene.get("segments", []):
            segment_id = segment["segment_id"]
            clip_video_path = Path(segment["clip_video"])
            clip_audio_path = Path(segment["narration_audio"])
            clip_output_path = output_path / f"scene_{scene_id}_segment_{segment_id}_final.mp4"

            if not clip_video_path.exists():
                print(f"[ERROR] 找不到视频: {clip_video_path}")
                continue
            if not clip_audio_path.exists():
                print(f"[ERROR] 找不到旁白: {clip_audio_path}")
                continue

            print(f"正在混音 scene:{scene_id} segment:{segment_id}")
            _mix_narration_audio(clip_video_path, clip_audio_path, clip_output_path)
            segment["final_video_path"] = str(clip_output_path)

    write_json(scenes, scene_path)


def mix_audio_hook_temp(hook_path, output_path):
    output_path.mkdir(parents=True, exist_ok=True)
    hook = read_json(hook_path)
    clip_video_path = Path(hook["hook_video"])
    clip_audio_path = Path(hook["hook_audio"])
    output_file = output_path / "hook_final.mp4"

    if not clip_video_path.exists():
        print(f"[ERROR] 找不到hook视频: {clip_video_path}")
        return
    if not clip_audio_path.exists():
        print(f"[ERROR] 找不到hook音频: {clip_audio_path}")
        return

    print("正在混音 hook")
    _mix_narration_audio(clip_video_path, clip_audio_path, output_file, alignment="end")
    hook["final_video_path"] = str(output_file)
    write_json(hook, hook_path)
    return hook
