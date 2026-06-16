from uuid import uuid4

from core.cmd import run_cmd
from pipeline.video import concat_videos
from core.ffmpeg import encode_to_standard
from core.path import ProjectPaths

def download_video(urls, output_path):

    if output_path.exists():
        output_path.unlink()
    
    if isinstance(urls, str):
        urls = [urls]

    root_path = ProjectPaths()

    for index, url in enumerate(urls):

        temp_video = root_path.origin / f"temp_{index:03d}.mp4"
        video = root_path.origin / f"{index:03d}.mp4"

        cmd = [
            "yt-dlp",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", str(temp_video),
            url
        ]

        run_cmd(cmd)

        encode_to_standard(temp_video, video)
        temp_video.unlink(missing_ok=True)

    concat_videos(root_path.origin, output_path)


    print(f"下载完成: {output_path}")