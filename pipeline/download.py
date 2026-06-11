from uuid import uuid4

from core.cmd import run_cmd
from pipeline.video import concat_videos
from core.path import ProjectPaths

def download_video(urls, output_path):

    if output_path.exists():
        output_path.unlink()
    
    if isinstance(urls, str):
        urls = [urls]

    root_path = ProjectPaths()
    
    downloaded_files = []

    for index, url in enumerate(urls):

        temp_video = root_path.root / f"{index:03d}.mp4"

        cmd = [
            "yt-dlp",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", str(temp_video),
            url
        ]

        run_cmd(cmd)

        downloaded_files.append(temp_video)

    concat_videos(root_path.root, output_path)


    print(f"下载完成: {output_path}")