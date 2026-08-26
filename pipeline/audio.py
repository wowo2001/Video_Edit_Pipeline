from pathlib import Path

from core.cmd import run_cmd
from core.ffmpeg import extract_audio, mix_background_narration, mix_narration
from core.utils import read_json


BACKGROUND_MUSIC_REGISTRY = Path("assets/background_music.json")


def resolve_background_music(selection, registry_path=BACKGROUND_MUSIC_REGISTRY):
    """Resolve a user-selected background music id or name from the asset registry."""
    if not selection:
        return None

    entries = read_json(registry_path)
    music = next(
        (
            item
            for item in entries
            if selection in {item.get("id"), item.get("name")}
        ),
        None,
    )
    if not music:
        raise ValueError(f"未登记的背景音乐: {selection}")

    music_path = Path(music["path"])
    if not music_path.is_file():
        raise FileNotFoundError(f"背景音乐文件不存在: {music_path}")
    return {**music, "path": music_path}


def mix_background_music(input_video, music_path, output_path, volume=0.08):
    """Loop low-volume music underneath a video's existing audio without changing duration."""
    volume = float(volume)
    if not 0 <= volume <= 1:
        raise ValueError("背景音乐音量必须在 0 到 1 之间")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filters = (
        "[0:a]aresample=48000[original];"
        f"[1:a]aresample=48000,volume={volume}[bgm];"
        "[original][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-filter_complex",
            filters,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            str(output_path),
        ]
    )


def export_audio(input_path, output_path):
    output_path = Path(output_path)
    if output_path.exists():
        output_path.unlink()

    extract_audio(input_path, output_path)
    print(f"\n✅ 音频导出完成: {output_path}")


def mix_narration_audio(video_path, narration_audio_path, output_path, alignment="start"):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"视频路径: {video_path}, 旁白路径: {narration_audio_path}, 输出路径: {output_path}")
    mix_narration(video_path, narration_audio_path, output_path, alignment=alignment)


def mix_background_narration_audio(
    video_path,
    narration_audio_path,
    output_path,
):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"背景视频: {video_path}, 旁白路径: {narration_audio_path}, 输出路径: {output_path}")
    mix_background_narration(
        video_path,
        narration_audio_path,
        output_path,
    )
