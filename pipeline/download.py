from core.cmd import run_cmd

def download_video(url: str, output_path):

    if output_path.exists():
        output_path.unlink()

    cmd = [
        "yt-dlp",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        url
    ]

    run_cmd(cmd)

    print(f"下载完成: {output_path}")