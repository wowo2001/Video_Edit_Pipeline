from core.cmd import run_cmd
from core.ffmpeg import encode_to_standard
from core.utils import write_json
from pipeline.video import concat_videos


def download_video(urls, output_path, origin_path, media_path):

    if output_path.exists():
        output_path.unlink()
    
    if isinstance(urls, str):
        urls = [urls]

    origin_path.mkdir(parents=True, exist_ok=True)

    media = []
    for index, url in enumerate(urls):

        temp_video = origin_path / f"temp_{index:03d}.mp4"
        video = origin_path / f"{index:03d}.mp4"

        cmd = [
            "yt-dlp",
            "--extractor-args", "youtube:player_client=mweb",
            "--js-runtimes", "node",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", str(temp_video),
            url
        ]

        run_cmd(cmd)

        encode_to_standard(temp_video, video)
        temp_video.unlink(missing_ok=True)
        media.append({"url": url, "video_path": str(video)})

    concat_videos(origin_path, output_path)
    write_json({"media": media}, media_path)

    print(f"下载完成: {output_path}")
