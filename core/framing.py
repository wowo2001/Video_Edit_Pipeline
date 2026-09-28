"""Frame-format helpers used by the translated news videos."""

from pathlib import Path

from core.cmd import run_cmd


def crop_to_four_three(input_file, output_file):
    """Center-crop the standard 1280x720 pipeline video to 960x720 (4:3)."""
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    vf = "crop=960:720:(iw-960)/2:(ih-720)/2,setsar=1"
    run_cmd([
        "ffmpeg", "-y", "-i", str(input_file), "-vf", vf,
        "-c:v", "libx264", "-crf", "23", "-preset", "fast", "-c:a", "copy",
        str(output_file),
    ])


def four_three_to_vertical(input_file, output_file, width=1080, height=1920, fps=30):
    """Place an already-cropped 4:3 frame inside a 9:16 vertical canvas."""
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale={width}:-2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    run_cmd([
        "ffmpeg", "-y", "-i", str(input_file), "-vf", vf, "-r", str(fps),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", str(output_file),
    ])
