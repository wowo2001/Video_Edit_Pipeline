import os
from urllib.parse import urlparse

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


def _get_filename_from_s3_url(s3_path):
    return os.path.basename(urlparse(s3_path).path)


def download_scene_videos(scene_path, download_dir, s3_client, standardize=True):
    scenes = read_json(scene_path)
    os.makedirs(download_dir, exist_ok=True)
    downloaded = {}

    for scene in scenes:
        s3_url = scene["video_url"]
        filename = _get_filename_from_s3_url(s3_url)
        local_path = downloaded.setdefault(s3_url, os.path.join(download_dir, filename))

        if os.path.exists(local_path):
            print(f"已存在，跳过: {local_path}")
        else:
            print(f"下载: {s3_url}")
            s3_client.download_file(s3_url, local_path)

        final_path = local_path
        if standardize:
            standard_dir = os.path.join(download_dir, "standard")
            os.makedirs(standard_dir, exist_ok=True)
            standard_path = os.path.join(standard_dir, filename)
            if not os.path.exists(standard_path):
                print(f"标准化视频: {local_path}")
                encode_to_standard(local_path, standard_path)
            final_path = standard_path
        scene["local_video_path"] = final_path

    write_json(scenes, scene_path)
    return scenes
