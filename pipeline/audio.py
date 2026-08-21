from pathlib import Path

from core.ffmpeg import extract_audio, mix_narration


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
