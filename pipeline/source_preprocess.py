"""Reusable whole-episode masters. Geometry is chosen once per drama batch."""
import hashlib
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

from core.cmd import run_cmd
from core.captions import (DEFAULT_CAPTION_LAYOUT, validate_caption_layout, overlay_layout,
                           DEFAULT_BACKGROUND_OPACITY, validate_background_opacity)

VERSION = 1


class SourceGeometryError(ValueError):
    pass


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def probe_source(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    data = json.loads(result.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    width, height = int(video["width"]), int(video["height"])
    sar = video.get("sample_aspect_ratio", "1:1")
    if sar not in ("N/A", "0:1"):
        width = round(width * float(Fraction(sar.replace(":", "/"))))
    rotation = next((int(s.get("rotation", 0)) for s in video.get("side_data_list", [])
                     if "rotation" in s), int(video.get("tags", {}).get("rotate", 0)))
    if abs(rotation) % 180 == 90:
        width, height = height, width
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("视频时长无效")
    rate = video.get("avg_frame_rate", "0/0")
    if rate == "0/0":
        rate = video.get("r_frame_rate", "25/1")
    if not 0 < float(Fraction(rate)) <= 120:
        raise ValueError("视频帧率无效")
    return {"width": width // 2 * 2, "height": height // 2 * 2,
            "duration": duration, "fps": rate,
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"])}


def default_profile(info, drama_title):
    aspect = info["width"] / info["height"]
    crop_width = min(1.0, (4 / 3) / aspect)
    crop_height = min(1.0, aspect / (4 / 3))
    return {"version": VERSION, "drama_title": drama_title,
            "reference": {k: info[k] for k in ("width", "height", "fps")},
            "crop": {"x": (1-crop_width)/2, "y": (1-crop_height)/2,
                     "width": crop_width, "height": crop_height},
            "blur_regions": [], "crf": 20, "preset": "medium", "max_height": 720,
            "caption_layout": dict(DEFAULT_CAPTION_LAYOUT), "overlay_layout": overlay_layout(),
            "background_opacity": DEFAULT_BACKGROUND_OPACITY}


def validate_profile(profile, drama_title=None):
    if not isinstance(profile, dict) or profile.get("version") != VERSION:
        raise ValueError("预处理配置版本无效，请重新选区")
    if drama_title is not None and profile.get("drama_title") != drama_title:
        raise ValueError("预处理配置的剧名与本批任务不一致")
    validate_caption_layout(profile.get("caption_layout", DEFAULT_CAPTION_LAYOUT))
    overlay_layout(profile.get("overlay_layout"))
    validate_background_opacity(profile.get('background_opacity', DEFAULT_BACKGROUND_OPACITY))
    reference = profile["reference"]
    if any(not isinstance(reference[k], int) or reference[k] < 2 for k in ("width", "height")):
        raise ValueError("参考画面尺寸无效")
    if not 0 < float(Fraction(reference["fps"])) <= 120:
        raise ValueError("参考帧率无效")
    if profile.get("crf") not in (18, 20, 22):
        raise ValueError("CRF 只能选择 18、20 或 22")
    if profile.get("preset") not in ("veryfast", "fast", "medium", "slow") or profile.get("max_height") != 720:
        raise ValueError("素材编码设置无效")
    regions = profile.get("blur_regions")
    if not isinstance(regions, list) or len(regions) > 20:
        raise ValueError("模糊区域最多 20 个")
    for box in [profile["crop"], *regions]:
        values = [box[k] for k in ("x", "y", "width", "height")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in values):
            raise ValueError("选区坐标无效")
        x, y, w, h = values
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 1.000001 or y+h > 1.000001:
            raise ValueError("选区超出画面")
    pixel_box(profile["crop"], reference["width"], reference["height"])
    for box in regions:
        pixel_box(box, reference["width"], reference["height"])
    return profile


def pixel_box(box, width, height):
    x, y = int(box["x"]*width)//2*2, int(box["y"]*height)//2*2
    w = min(int(box["width"]*width)//2*2, width-x)
    h = min(int(box["height"]*height)//2*2, height-y)
    if w < 4 or h < 4:
        raise ValueError("选区过小，请至少选择 4×4 像素")
    return x, y, w, h


def check_geometry(info, profile):
    ref = profile["reference"]
    if abs((info["width"]/info["height"])/(ref["width"]/ref["height"])-1) > .02:
        raise SourceGeometryError("本集宽高比与选区参考视频不同，已跳过；请单独配置后重试")
    if not info["has_audio"]:
        raise ValueError("素材没有原声音轨")
    pixel_box(profile["crop"], info["width"], info["height"])
    for box in profile["blur_regions"]:
        pixel_box(box, info["width"], info["height"])


def output_size(profile, infos):
    """One canvas for concatenation; do not upscale even a lower-resolution part."""
    ref = profile["reference"]
    _, _, rw, rh = pixel_box(profile["crop"], ref["width"], ref["height"])
    height = min(720, rh, *(pixel_box(profile["crop"], i["width"], i["height"])[3]
                            for i in infos)) // 2 * 2
    return max(4, int(height*rw/rh)//2*2), height


def encode_master(source, destination, profile, info=None, size=None, *, start=None, seconds=None):
    """Blur on source geometry, crop, resize and compress in a single encode."""
    validate_profile(profile)
    info = info or probe_source(source)
    check_geometry(info, profile)
    size = size or output_size(profile, [info])
    width, height = info["width"], info["height"]
    parts = [f"[0:v:0]scale={width}:{height},setsar=1[base]"]
    regions = profile["blur_regions"]
    if regions:
        parts.append(f"[base]split={len(regions)+1}[canvas]"+
                     "".join(f"[r{i}]" for i in range(len(regions))))
    current = "canvas" if regions else "base"
    for i, box in enumerate(regions):
        x, y, w, h = pixel_box(box, width, height)
        radius = max(1, min(round(18*height/720), w//4, h//4))
        parts.append(f"[r{i}]crop={w}:{h}:{x}:{y},boxblur={radius}:2,"
                     f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.15:t=fill[b{i}]")
        parts.append(f"[{current}][b{i}]overlay={x}:{y}[layer{i}]")
        current = f"layer{i}"
    x, y, w, h = pixel_box(profile["crop"], width, height)
    parts.append(f"[{current}]crop={w}:{h}:{x}:{y},scale={size[0]}:{size[1]},setsar=1[v]")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem+".encoding.mp4")
    command = ["ffmpeg", "-y"]
    if start is not None:
        command += ["-ss", str(start)]
    command += ["-i", str(source)]
    if seconds is not None:
        command += ["-t", str(seconds)]
    command += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "0:a:0",
                "-c:v", "libx264", "-preset", profile["preset"], "-crf", str(profile["crf"]),
                "-pix_fmt", "yuv420p", "-r", profile["reference"]["fps"],
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", str(temporary)]
    try:
        run_cmd(command)
        result = probe_source(temporary)
        expected = min(seconds, info["duration"]-(start or 0)) if seconds else info["duration"]
        if abs(result["duration"]-expected) > .25:
            raise ValueError("母版时长与源视频不一致，未采用本次输出")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def download_raw_video(url, cache_dir=Path("work/source_download_cache")):
    """Download/remux original streams without re-encoding; preserve for re-editing."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("视频 URL 无效")
    directory = Path(cache_dir)/hashlib.sha256(url.encode()).hexdigest()[:24]
    marker = directory/"download.json"
    if marker.exists():
        cached = load_json(marker)
        path = directory/cached["filename"]
        if cached.get("url") == url and path.is_file() and path.stat().st_size == cached.get("size"):
            return path
    directory.mkdir(parents=True, exist_ok=True)
    print(f"下载原始素材（不转码）: {url}", flush=True)
    result = subprocess.run([
        "yt-dlp", "--js-runtimes", "node", "--no-playlist", "--no-simulate", "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mkv", "--print", "after_move:filepath", "-o",
        str(directory.resolve()/"source.%(ext)s"), url,
    ], capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"下载失败: {result.stderr[-2000:]}")
    path = Path(result.stdout.strip().splitlines()[-1])
    if not path.is_file() or path.parent.resolve() != directory.resolve():
        raise RuntimeError("下载完成但没有找到原始素材")
    probe_source(path)
    save_json(marker, {"url": url, "filename": path.name, "size": path.stat().st_size})
    return path


def prepare_episode(urls, paths, profile):
    validate_profile(profile)
    urls = [urls] if isinstance(urls, str) else urls
    if not isinstance(urls, list) or not urls:
        raise ValueError("本集没有视频 URL")
    raw_paths = [download_raw_video(url) for url in urls]
    infos = [probe_source(p) for p in raw_paths]
    for info in infos:
        check_geometry(info, profile)
    size = output_size(profile, infos)
    # Subtitle placement affects the deliverable, never the whole-episode master.
    master_profile = {k: v for k, v in profile.items() if k not in ("caption_layout", "overlay_layout", "background_opacity")}
    signature = {"profile": master_profile, "size": size, "sources": [
        {"url": url, "path": str(p.resolve()), "size": p.stat().st_size,
         "mtime": p.stat().st_mtime_ns} for url, p in zip(urls, raw_paths)]}
    fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    marker = paths.root/"source_master.json"
    if marker.exists() and paths.video.is_file():
        previous = load_json(marker)
        if previous.get("fingerprint") == fingerprint and previous.get("file_size") == paths.video.stat().st_size:
            return previous["media"]
    sources = []
    for i, (url, raw, info) in enumerate(zip(urls, raw_paths, infos)):
        output = paths.origin/f"{i:03d}_master.mp4"
        encoded = encode_master(raw, output, profile, info, size)
        sources.append({"url": url, "raw_video_path": str(raw), "video_path": str(output),
                        "duration": encoded["duration"]})
    # Stream-copy concat, including a single source: no second video encode.
    listing = paths.root/"master_concat.txt"
    # Relative generated names keep source-title punctuation out of the concat parser.
    listing.write_text("".join(f"file 'origin/{i:03d}_master.mp4'\n" for i in range(len(sources))), encoding="utf-8")
    temporary = paths.video.with_name("source_master.encoding.mp4")
    try:
        run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                 "-c", "copy", "-movflags", "+faststart", str(temporary)])
        info = probe_source(temporary)
        temporary.replace(paths.video)
    finally:
        temporary.unlink(missing_ok=True)
    media = {"sources": sources, "main": {"source_video_path": str(paths.video),
             "source_master": {"version": VERSION, "fingerprint": fingerprint,
                               "profile": master_profile, "video": info}}}
    save_json(marker, {"fingerprint": fingerprint, "file_size": paths.video.stat().st_size, "media": media})
    return media
