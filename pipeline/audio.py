from core.cmd import run_cmd
from core.ffmpeg import concat_media, extract_audio, mix_narration
from core.demucs import extract_vocals_demucs
import json
from core.utils import read_json, write_json
from pathlib import Path


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

        extract_vocals_demucs(mp3_file)

        vocal_files.append(mp3_file)

    filelist = input_path / "mp3_list.txt"

    with open(filelist, "w", encoding="utf-8") as f:
        for mp3 in vocal_files:
            f.write(f"file '{mp3.absolute()}'\n")

    concat_media(filelist, output_path)

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

    data = read_json(script_path)
    for item in data["clips"]:
        place = item["place"]
        clip_video_path = video_path / f"clip_{place}.mp4"
        print(f"正在处理剪辑 {clip_video_path} 的混音...")
        clip_audio = narration_audio_path / f"clip_{place}.mp3"
        clip_output = output_path / f"clip_{place}_final.mp4"
        _mix_clip_audio(clip_video_path, clip_audio, clip_output)


    

def _mix_hook_audio(video_path, narration_audio_path, output_path):    
    mix_narration(video_path, narration_audio_path, output_path, alignment="end")

def _mix_clip_audio(video_path, narration_audio_path, output_path):    
    print(f"视频路径: {video_path}, 旁白路径: {narration_audio_path}, 输出路径: {output_path}")
    mix_narration(video_path, narration_audio_path, output_path)

def mix_audio_segment_temp(
    scene_path,
    output_path
):

    output_path.mkdir(
        parents=True,
        exist_ok=True
    )


    scenes = read_json(scene_path)


    for scene in scenes:

        scene_id = scene["scene_id"]


        for segment in scene.get(
            "segments",
            []
        ):

            segment_id = segment["segment_id"]


            clip_video_path = Path(
                segment["clip_video"]
            )


            clip_audio_path = Path(
                segment["narration_audio"]
            )


            clip_output = (
                output_path /
                f"scene_{scene_id}_segment_{segment_id}_final.mp4"
            )



            if not clip_video_path.exists():

                print(
                    f"[ERROR] 找不到视频: {clip_video_path}"
                )

                continue



            if not clip_audio_path.exists():

                print(
                    f"[ERROR] 找不到旁白: {clip_audio_path}"
                )

                continue



            print(
                f"正在混音 scene:{scene_id} segment:{segment_id}"
            )


            _mix_clip_audio(
                clip_video_path,
                clip_audio_path,
                clip_output
            )



            segment["final_video_path"] = str(
                clip_output
            )



    write_json(
                scenes,
                scene_path,
                ensure_ascii=False,
                indent=2
            )


def mix_audio_hook_temp(
    hook_path,
    output_path
):

    output_path.mkdir(
        parents=True,
        exist_ok=True
    )


    hook = read_json(hook_path)


    clip_video_path = Path(
        hook["hook_video"]
    )


    clip_audio_path = Path(
        hook["hook_audio"]
    )


    output_file = (
        output_path /
        "hook_final.mp4"
    )



    if not clip_video_path.exists():

        print(
            f"[ERROR] 找不到hook视频: {clip_video_path}"
        )

        return



    if not clip_audio_path.exists():

        print(
            f"[ERROR] 找不到hook音频: {clip_audio_path}"
        )

        return



    print(
        "正在混音 hook"
    )


    _mix_hook_audio(
        clip_video_path,
        clip_audio_path,
        output_file
    )



    hook["final_video_path"] = str(
        output_file
    )



    write_json(
                hook,
                hook_path,
                ensure_ascii=False,
                indent=2
            )

    return hook
