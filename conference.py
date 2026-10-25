"""End-to-end Australian Parliament commentary-video workflow.

Running this module with a task file creates an isolated workspace for every
source, then downloads, transcribes, analyses, renders and uploads every
candidate topic selected for that source.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Windows terminals may otherwise use cp1252 and fail before the workflow starts.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.path import ProjectPaths
from core.ffmpeg import dub_video_segment, get_duration
from core.utils import ms_to_srt_time, read_json, safe_filename, write_json
from pipeline.download import download_video
from pipeline.audio import boost_tts_audio, export_audio
from pipeline.video import cut_video_range, fit_forward_video_range
from services.chatgpt import ChatGPT
from services.volcengine import Volcengine


NARRATOR_TTS_VOICE = "zh_male_m191_uranus_bigtts"

MALE_DIALOGUE_TTS_VOICES = [
    "zh_male_liufei_uranus_bigtts",
    "ICL_uranus_zh_male_lvchaxiaoge_tob",
]
FEMALE_DIALOGUE_TTS_VOICES = [
    "ICL_uranus_zh_female_kefunvshengwenhecuishou_tob",
    "zh_female_meilinvyou_uranus_bigtts",
    "zh_female_gufengshaoyu_uranus_bigtts",
    "zh_female_tvbnv_uranus_bigtts",
]


def replace_video_audio(video_path: Path, audio_path: Path, output_path: Path) -> None:
    """Keep the visual stream and replace—not mix—the source audio."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-shortest", str(output_path),
        ],
        check=True,
    )


def _read_workspace_media(paths: ProjectPaths) -> tuple[dict, Path]:
    """Read the shared source media.json when invoked inside a candidate subfolder."""
    for directory in (paths.root, *paths.root.parents):
        candidate = directory / "media.json"
        if candidate.exists():
            return read_json(candidate), candidate
    raise FileNotFoundError(f"找不到工作区 media.json: {paths.root}")


def concat_preview_clips(video_paths: list[str | Path], output_path: Path, list_path: Path) -> None:
    """Concatenate preview clips while rebuilding timestamps and audio format."""
    if not video_paths:
        raise ValueError("没有可拼接的预览片段")
    inputs = []
    filters = []
    labels = []
    for index, video_path in enumerate(video_paths):
        inputs.extend(["-i", str(video_path)])
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS[v{index}]")
        filters.append(f"[{index}:a]asetpts=PTS-STARTPTS[a{index}]")
        labels.append(f"[v{index}][a{index}]")
    filters.append(f"{''.join(labels)}concat=n={len(video_paths)}:v=1:a=1[vout][aout]")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters),
                "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "fast",
                "-crf", "23", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(output_path),
            ],
            check=True,
        )
    finally:
        list_path.unlink(missing_ok=True)


def create_black_transition(output_path: Path, duration_seconds: float = 0.35) -> None:
    """Create a short silent black clip compatible with the horizontal preview."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c=black:s=1280x720:r=25:d={duration_seconds}",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(duration_seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output_path),
        ],
        check=True,
    )


def crossfade_preview_clips(video_paths: list[str | Path], output_path: Path, duration_seconds: float = 0.12) -> None:
    """Join discontinuous source clips with a brief video and audio crossfade."""
    if not video_paths:
        raise ValueError("没有可交叉淡化的预览片段")
    current = Path(video_paths[0])
    if len(video_paths) == 1:
        shutil.copy2(current, output_path)
        return
    temporary_paths: list[Path] = []
    for index, next_path in enumerate(video_paths[1:], start=1):
        is_last = index == len(video_paths) - 1
        target = output_path if is_last else output_path.parent / f"{output_path.stem}_xfade_{index:02d}.mp4"
        if not is_last:
            temporary_paths.append(target)
        video_duration_result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1", str(current),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        offset = max(0.0, float(video_duration_result.stdout.strip()) - duration_seconds)
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(current), "-i", str(next_path), "-filter_complex",
                "[0:v]settb=AVTB,setpts=PTS-STARTPTS,fps=25,format=yuv420p[v0];"
                "[1:v]settb=AVTB,setpts=PTS-STARTPTS,fps=25,format=yuv420p[v1];"
                f"[v0][v1]xfade=transition=fade:duration={duration_seconds}:offset={offset}[v];"
                "[0:a]aresample=48000,asetpts=PTS-STARTPTS[a0];"
                "[1:a]aresample=48000,asetpts=PTS-STARTPTS[a1];"
                f"[a0][a1]acrossfade=d={duration_seconds}[a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(target),
            ],
            check=True,
        )
        if current in temporary_paths and current.exists():
            current.unlink()
            temporary_paths.remove(current)
        current = target


def create_workspace(title: str | None = None) -> ProjectPaths:
    """Create one fresh workspace for each Parliament source job."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = safe_filename(title) if title else "parliament"
    workspace = Path("work") / "parliament" / f"{timestamp}_{name}_{uuid4().hex[:8]}"
    return ProjectPaths(workspace)


def download_english_caption(url: str, origin_dir: Path, index: int) -> Path | None:
    """Download a human English caption when available, otherwise auto-caption.

    YouTube decides whether a video exposes captions.  A missing caption is
    recorded as None rather than failing the video download job.
    """
    output_template = origin_dir / f"{index:03d}.%(ext)s"
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "en-orig,en",
        "--sub-format",
        "srt",
        "--skip-download",
        "-o",
        str(output_template),
        url,
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(f"未能下载英文字幕: {url}")
        return None

    candidates = sorted(origin_dir.glob(f"{index:03d}*.srt"))
    if not candidates:
        print(f"该视频没有可下载的英文字幕: {url}")
        return None

    # Prefer the original-English track, then an ordinary English track.
    for candidate in candidates:
        if ".en-orig." in candidate.name:
            return candidate
    for candidate in candidates:
        if ".en." in candidate.name:
            return candidate
    return candidates[0]


def fetch_youtube_metadata(url: str) -> dict | None:
    """Read source context without downloading the video again."""
    result = subprocess.run(
        [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--skip-download",
            "--dump-single-json", "--no-warnings", url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        print(f"未能读取 YouTube 元数据: {url}")
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"YouTube 元数据格式无效: {url}")
        return None
    return {
        "youtube_id": data.get("id"),
        "title": data.get("title"),
        "channel": data.get("channel") or data.get("uploader"),
        "channel_id": data.get("channel_id"),
        "published_at": data.get("upload_date"),
        "duration_seconds": data.get("duration"),
        "webpage_url": data.get("webpage_url") or url,
        "description": data.get("description") or "",
    }


def record_source_metadata(paths: ProjectPaths) -> list[dict]:
    """Attach YouTube title and related source context to media.json."""
    media_data = read_json(paths.media)
    metadata_items = []
    for source in media_data["sources"]:
        metadata = fetch_youtube_metadata(source["url"])
        if metadata:
            source["youtube_metadata"] = metadata
            metadata_items.append(metadata)
    media_data["main"]["source_metadata"] = metadata_items
    if metadata_items:
        primary = metadata_items[0]
        media_data["main"]["source_context"] = {
            "title": primary["title"],
            "channel": primary["channel"],
            "published_at": primary["published_at"],
            "youtube_id": primary["youtube_id"],
        }
    write_json(media_data, paths.media)
    return metadata_items


_SRT_BLOCK = re.compile(
    r"^\s*\d+\s*\n"
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})[^\n]*\n"
    r"(?P<text>.*?)(?=\n\s*\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _srt_timestamp_to_ms(value: str) -> int:
    hours, minutes, seconds_and_ms = value.split(":")
    seconds, milliseconds = seconds_and_ms.split(",")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(milliseconds)
    )


def import_caption_for_main_flow(caption_path: Path, paths: ProjectPaths) -> None:
    """Store the untouched caption as main.py-compatible SRT and JSON.

    The JSON deliberately preserves the source's text and time range one-to-one;
    it only supplies the ``utterances`` container expected by SpeechBrain and
    the main commentary pipeline.
    """
    shutil.copy2(caption_path, paths.subtitles["srt"])
    source = caption_path.read_text(encoding="utf-8-sig")
    utterances = []
    for match in _SRT_BLOCK.finditer(source):
        text = " ".join(line.strip() for line in match.group("text").splitlines())
        if not text:
            continue
        utterances.append(
            {
                "start_time": _srt_timestamp_to_ms(match.group("start")),
                "end_time": _srt_timestamp_to_ms(match.group("end")),
                "text": text,
                "attribute": {},
            }
        )
    if not utterances:
        raise ValueError(f"无法从字幕读取有效时间轴: {caption_path}")
    write_json(
        {"utterances": utterances, "source": "youtube_caption"},
        paths.subtitles["json"],
    )


def _write_plain_srt(utterances: list[dict], output_path: Path) -> None:
    """Write source captions without speaker labels."""
    with open(output_path, "w", encoding="utf-8") as file:
        for index, utterance in enumerate(utterances, start=1):
            file.write(
                f"{index}\n{ms_to_srt_time(utterance['start_time'])} --> "
                f"{ms_to_srt_time(utterance['end_time'])}\n"
                f"{utterance['text'].strip()}\n\n"
            )


def _normalise_sentence_groups(groups: list, count: int) -> list[list[int]]:
    """Keep only ordered adjacent AI groups; preserve any omitted text alone."""
    if not isinstance(groups, list):
        groups = []
    result: list[list[int]] = []
    cursor = 0
    for group in groups:
        if not isinstance(group, list) or not group:
            continue
        if not all(isinstance(item, int) for item in group):
            continue
        if group != list(range(group[0], group[-1] + 1)):
            continue
        if group[0] < cursor or group[-1] >= count:
            continue
        while cursor < group[0]:
            result.append([cursor])
            cursor += 1
        result.append(group)
        cursor = group[-1] + 1
    while cursor < count:
        result.append([cursor])
        cursor += 1
    return result


def merge_english_subtitles_before_diarization(paths: ProjectPaths) -> Path:
    """Use AI grammar grouping while preserving source text and time ranges."""
    media_data = read_json(paths.media)
    subtitle_source = str(media_data.get("main", {}).get("subtitles", {}).get("source") or "")
    raw_stem = "subtitles_cloud_raw" if subtitle_source.startswith("volcengine") else "subtitles_raw"
    raw_json_path = paths.root / f"{raw_stem}.json"
    raw_srt_path = paths.root / f"{raw_stem}.srt"
    # A re-run must always work from the untouched caption, not an earlier merge.
    subtitles = read_json(raw_json_path) if raw_json_path.exists() else read_json(paths.subtitles["json"])
    utterances = subtitles.get("utterances", [])
    if not utterances:
        raise ValueError("缺少可合并的字幕 utterances")

    if not raw_json_path.exists():
        write_json(subtitles, raw_json_path)
    if not raw_srt_path.exists():
        shutil.copy2(paths.subtitles["srt"], raw_srt_path)

    source_items = [[index, utterance["text"].strip()] for index, utterance in enumerate(utterances)]
    groups = ChatGPT(usage_report_path=paths.llm_cost_report).merge_english_subtitles_before_diarization(
        source_items
    )
    groups = _normalise_sentence_groups(groups, len(utterances))

    merged_utterances = []
    for source_indices in groups:
        parts = [utterances[index] for index in source_indices]
        first, last = parts[0], parts[-1]
        merged_utterances.append(
            {
                "start_time": first["start_time"],
                "end_time": last["end_time"],
                "text": " ".join(part["text"].strip() for part in parts),
                "attribute": {},
                "source_indices": source_indices,
            }
        )

    subtitles["utterances"] = merged_utterances
    subtitles["source"] = f"{subtitle_source or 'subtitle'}_grammar_merged"
    write_json(subtitles, paths.subtitles["json"])
    _write_plain_srt(merged_utterances, paths.subtitles["srt"])

    media_data["main"]["raw_subtitles"] = {
        "srt_path": str(raw_srt_path),
        "json_path": str(raw_json_path),
        "utterance_count": len(utterances),
    }
    media_data["main"]["merged_english_subtitle_count"] = len(merged_utterances)
    write_json(media_data, paths.media)
    print(f"AI 英文短句整合完成: {len(utterances)} → {len(merged_utterances)}")
    return paths.subtitles["json"]


def transcribe_parliament_english_subtitles(paths: ProjectPaths) -> Path:
    """Create the shared English subtitle timeline from the source audio.

    Parliament videos often have incomplete or overly fragmented YouTube
    captions.  The production workflow therefore always uses the same cloud
    transcription source as the translation workflow, while retaining any
    downloaded YouTube captions only as source reference files.
    """
    from pipeline.audio import export_audio

    media_data = read_json(paths.media)
    if not paths.audio.exists():
        export_audio(paths.video, paths.audio)
    else:
        print(f"复用已有原始音轨: {paths.audio}")

    Volcengine().transcribe_audio(paths.audio, paths.subtitles, language="en-US")
    media_data["main"]["source_audio_path"] = str(paths.audio)
    media_data["main"]["subtitles"] = {
        "srt_path": str(paths.subtitles["srt"]),
        "json_path": str(paths.subtitles["json"]),
        "source": "volcengine_en-US",
    }
    write_json(media_data, paths.media)
    return paths.subtitles["json"]


def classify_speakers(paths: ProjectPaths) -> Path:
    """Cluster speakers from the original audio without vocal separation."""
    from core.speechbrain import SpeechBrain
    from pipeline.audio import export_audio

    media_data = read_json(paths.media)
    if not paths.audio.exists():
        export_audio(paths.video, paths.audio)
    else:
        print(f"复用已有原始音轨: {paths.audio}")
    media_data["main"]["source_audio_path"] = str(paths.audio)

    SpeechBrain().diarize(
        paths.audio,
        paths.subtitles,
        threshold=0.5,
        min_cluster_ratio=0.01,
        core_reassignment_threshold=0.55,
        short_assignment_threshold=0.48,
        assignment_margin=0.03,
    )
    media_data["main"]["speaker_clustered_subtitles"] = {
        "srt_path": str(paths.subtitles["srt"]),
        "json_path": str(paths.subtitles["json"]),
    }
    write_json(media_data, paths.media)
    print(f"语音聚类完成: {paths.subtitles['json']}")
    return paths.subtitles["json"]


def classify_speaker_genders(paths: ProjectPaths) -> dict:
    """Classify every full-video speaker using short aggregated audio samples.

    Audio extraction deliberately uses ffmpeg, not torch/torchaudio.  That
    keeps the parent process lightweight while each gender-model worker runs
    in a fresh, single-threaded Python process on Windows.
    """
    subtitles = read_json(paths.subtitles["json"])
    media_data = read_json(paths.media)
    audio_path = Path(media_data.get("main", {}).get("source_audio_path", paths.audio))
    if not audio_path.exists():
        raise ValueError("缺少原始音轨；请先运行 --step cluster")

    max_duration_ms = 30_000
    speaker_ranges: dict[str, list[tuple[int, int]]] = {}
    accumulated_ms: dict[str, int] = {}
    for utterance in subtitles.get("utterances", []):
        speaker = utterance.get("attribute", {}).get("speaker", "UNKNOWN")
        if speaker == "UNKNOWN":
            continue
        start, end = int(utterance["start_time"]), int(utterance["end_time"])
        if end - start < 300:
            continue
        already = accumulated_ms.get(speaker, 0)
        if already >= max_duration_ms:
            continue
        end = min(end, start + max_duration_ms - already)
        speaker_ranges.setdefault(speaker, []).append((start, end))
        accumulated_ms[speaker] = already + end - start

    gender_audio_dir = paths.root / "gender_audio"
    gender_environment = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    genders = {}
    for speaker, ranges in speaker_ranges.items():
        output_audio = gender_audio_dir / f"{speaker}.wav"
        output_audio.parent.mkdir(parents=True, exist_ok=True)
        filters = []
        labels = []
        for index, (start, end) in enumerate(ranges):
            label = f"a{index}"
            filters.append(
                f"[0:a]atrim=start={start / 1000:.3f}:end={end / 1000:.3f},"
                f"asetpts=PTS-STARTPTS[{label}]"
            )
            labels.append(f"[{label}]")
        filters.append(
            f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1,"
            "aformat=channel_layouts=mono:sample_rates=16000[out]"
        )
        extract = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(audio_path), "-filter_complex",
                ";".join(filters), "-map", "[out]", str(output_audio),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if extract.returncode != 0 or not output_audio.exists():
            raise RuntimeError(f"无法汇集 {speaker} 的全片音频样本: {extract.stderr[-800:]}")
        result = subprocess.run(
            [sys.executable, "-m", "core.voice_gender", str(output_audio)],
            capture_output=True,
            text=True,
            check=False,
            env=gender_environment,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{speaker} 的性别模型失败（退出码 {result.returncode}）："
                f"{result.stderr[-800:]}"
            )
        try:
            genders[speaker] = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as error:
            raise RuntimeError(f"{speaker} 的性别模型没有返回 JSON：{result.stdout[-800:]}") from error

    media_data["main"]["speaker_gender_mapping"] = genders
    media_data["main"]["speaker_gender_audio_dir"] = str(gender_audio_dir)
    write_json(media_data, paths.media)
    print(f"声音性别判断完成: {len(genders)} 个声纹簇")
    return genders


def recognise_parliament_speakers(paths: ProjectPaths) -> Path:
    """Identify clustered speakers using merged captions and YouTube metadata."""
    media_data = read_json(paths.media)
    source_context = media_data.get("main", {}).get("source_context", {})
    if not source_context:
        raise ValueError("缺少 source_context；请先运行 --step metadata")

    subtitles = read_json(paths.subtitles["json"])
    speaker_lines = []
    seen_speakers = set()
    for utterance in subtitles.get("utterances", []):
        speaker = utterance.get("attribute", {}).get("speaker", "UNKNOWN")
        if speaker == "UNKNOWN":
            continue
        seen_speakers.add(speaker)
        speaker_lines.append(f"[{speaker}] {utterance.get('text', '').strip()}")
    if not speaker_lines:
        raise ValueError("字幕没有聚类 speaker；请先运行 --step cluster")

    profiles = ChatGPT(usage_report_path=paths.llm_cost_report).recognise_parliament_speakers(
        source_context, speaker_lines
    )
    if not isinstance(profiles, dict):
        raise ValueError("说话人识别结果不是 JSON 对象")

    # Keep a detail-rich result for review, and a simple mapping compatible with
    # the later main.py workflow. Unknown identities retain their cluster label.
    normalised_profiles = {}
    mapping = {}
    for speaker in sorted(seen_speakers):
        profile = profiles.get(speaker, {})
        if not isinstance(profile, dict):
            profile = {}
        name = profile.get("name")
        if not isinstance(name, str) or not name.strip():
            name = None
        normalised_profiles[speaker] = {
            "name": name,
            "role": str(profile.get("role") or "Unknown"),
            "confidence": str(profile.get("confidence") or "low"),
            "evidence": str(profile.get("evidence") or ""),
        }
        mapping[speaker] = name or speaker

    profiles_path = paths.root / "speaker_profiles.json"
    write_json(normalised_profiles, profiles_path, ensure_ascii=False, indent=2)
    write_json(mapping, paths.speaker_mapping, ensure_ascii=False, indent=2)

    for utterance in subtitles.get("utterances", []):
        attribute = utterance.setdefault("attribute", {})
        raw_speaker = attribute.get("speaker")
        profile = normalised_profiles.get(raw_speaker)
        if profile:
            attribute["speaker_name"] = profile["name"] or raw_speaker
            attribute["speaker_role"] = profile["role"]
            attribute["speaker_confidence"] = profile["confidence"]
    write_json(subtitles, paths.subtitles["json"])

    media_data["main"]["speaker_recognition"] = {
        "profiles_path": str(profiles_path),
        "mapping_path": str(paths.speaker_mapping),
        "input": "merged_subtitles_and_source_context",
    }
    write_json(media_data, paths.media)
    print(f"说话人识别完成: {profiles_path}")
    return profiles_path


def _normalise_content_segments(segments: object, utterance_count: int) -> list[dict]:
    """Guarantee an ordered complete coverage even if the model omits an item."""
    if not isinstance(segments, list):
        segments = []
    result = []
    cursor = 0
    for item in segments:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start_index"), item.get("end_index")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < cursor or end < start or start >= utterance_count:
            continue
        end = min(end, utterance_count - 1)
        if cursor < start:
            result.append({
                "start_index": cursor, "end_index": start - 1,
                "topic": "Unsegmented transition", "summary": "未被模型归类的连续字幕。",
            })
        result.append({
            "start_index": start,
            "end_index": end,
            "topic": str(item.get("topic") or "Untitled segment"),
            "summary": str(item.get("summary") or ""),
        })
        cursor = end + 1
    if cursor < utterance_count:
        result.append({
            "start_index": cursor, "end_index": utterance_count - 1,
            "topic": "Unsegmented transition", "summary": "未被模型归类的连续字幕。",
        })
    return result


def segment_parliament_content(paths: ProjectPaths) -> Path:
    """Segment merged, diarised captions into flexible consecutive topics."""
    media_data = read_json(paths.media)
    source_context = media_data.get("main", {}).get("source_context", {})
    subtitles = read_json(paths.subtitles["json"])
    utterances = subtitles.get("utterances", [])
    if not source_context:
        raise ValueError("缺少 source_context；请先运行 --step metadata")
    if not utterances:
        raise ValueError("缺少合并字幕")

    result = ChatGPT(usage_report_path=paths.llm_cost_report).segment_parliament_content(
        source_context, utterances
    )
    segments = _normalise_content_segments(result.get("segments"), len(utterances))
    output = {
        "source": {
            "subtitle_path": str(paths.subtitles["json"]),
            "utterance_count": len(utterances),
            "source_context": source_context,
        },
        "segments": segments,
    }
    output_path = paths.root / "content_segments.json"
    write_json(output, output_path, ensure_ascii=False, indent=2)
    media_data["main"]["content_segments_path"] = str(output_path)
    write_json(media_data, paths.media)
    print(f"内容分段完成: {len(utterances)} 句 → {len(segments)} 段: {output_path}")
    return output_path


def select_chinese_australia_topic(paths: ProjectPaths) -> Path:
    """Extract all daily-life-relevant segments; retain a primary topic for compatibility."""
    media_data = read_json(paths.media)
    source_context = media_data.get("main", {}).get("source_context", {})
    segments_path = paths.root / "content_segments.json"
    if not segments_path.exists():
        raise ValueError("缺少 content_segments.json；请先运行 --step segment")
    segment_data = read_json(segments_path)
    raw_segments = segment_data.get("segments", [])
    segments = [
        {
            "segment_id": f"s{index:02d}",
            "start_index": segment["start_index"],
            "end_index": segment["end_index"],
            "topic": segment["topic"],
            "summary": segment["summary"],
        }
        for index, segment in enumerate(raw_segments, start=1)
    ]
    result = ChatGPT(usage_report_path=paths.llm_cost_report).select_chinese_australia_topic(
        source_context, segments
    )
    candidates = result.get("candidates") if isinstance(result, dict) else None
    if not isinstance(candidates, list):
        raise ValueError("选题结果缺少 candidates")

    valid_ids = {segment["segment_id"] for segment in segments}
    cleaned_candidates = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        ids = candidate.get("segment_ids")
        if not isinstance(ids, list) or not ids or any(item not in valid_ids for item in ids):
            continue
        cleaned_candidates.append({
            "topic_id": str(candidate.get("topic_id") or f"topic_{len(cleaned_candidates) + 1}"),
            "title": str(candidate.get("title") or "Untitled topic"),
            "segment_ids": ids,
            "relevance": str(candidate.get("relevance") or ""),
            "source_basis": str(candidate.get("source_basis") or ""),
            "commentary_angle": str(candidate.get("commentary_angle") or ""),
            "viewer_takeaway": str(candidate.get("viewer_takeaway") or ""),
        })
    selected_id = result.get("selected_topic_id") if isinstance(result, dict) else None
    if not cleaned_candidates and selected_id is None:
        output = {
            "source_context": source_context,
            "candidates": [],
            "selected_topic_id": None,
            "commentary_angle": "",
            "viewer_takeaway": "",
            "no_candidate_reason": str(result.get("no_candidate_reason") or "没有符合筛选标准的候选选题。"),
        }
        output_path = paths.root / "selected_topic.json"
        write_json(output, output_path, ensure_ascii=False, indent=2)
        media_data["main"]["selected_topic_path"] = str(output_path)
        write_json(media_data, paths.media)
        print(f"华人日常选题完成：无合格候选: {output_path}")
        return output_path
    if selected_id not in {item["topic_id"] for item in cleaned_candidates}:
        raise ValueError("选题结果没有选择有效候选 topic")

    output = {
        "source_context": source_context,
        "candidates": cleaned_candidates,
        "selected_topic_id": selected_id,
        "commentary_angle": str(result.get("commentary_angle") or ""),
        "viewer_takeaway": str(result.get("viewer_takeaway") or ""),
    }
    output_path = paths.root / "selected_topic.json"
    write_json(output, output_path, ensure_ascii=False, indent=2)
    media_data["main"]["selected_topic_path"] = str(output_path)
    write_json(media_data, paths.media)
    print(f"华人日常选题完成: {output_path}")
    return output_path


def _candidate_topic_paths(paths: ProjectPaths, topic_id: str) -> ProjectPaths:
    """Create an isolated output directory while sharing the original source inputs."""
    topic_paths = ProjectPaths(paths.root / "topics" / safe_filename(topic_id))
    shared_segments = paths.root / "content_segments.json"
    if not shared_segments.exists():
        raise ValueError("缺少 content_segments.json；请先运行 --step segment")
    shutil.copy2(shared_segments, topic_paths.root / "content_segments.json")
    topic_paths.video = paths.video
    topic_paths.audio = paths.audio
    topic_paths.subtitles = paths.subtitles
    topic_paths.media = paths.media
    topic_paths.llm_cost_report = paths.llm_cost_report
    return topic_paths


def produce_all_candidate_topics(paths: ProjectPaths, topic_ids: set[str] | None = None) -> Path:
    """Create one complete local short-video package for every selected candidate.

    Downloading, caption merge, speaker analysis and source segmentation stay shared.
    Each candidate receives only its own LLM plan, TTS, preview and final files.
    Upload is deliberately a separate explicit step.
    """
    selected_path = paths.root / "selected_topic.json"
    if not selected_path.exists():
        raise ValueError("缺少 selected_topic.json；请先运行 --step select-topic")
    selection = read_json(selected_path)
    candidates = selection.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("没有可制作的候选选题")
    if not candidates:
        output_path = paths.root / "candidate_topic_outputs.json"
        write_json({
            "source_selection": str(selected_path),
            "topics": [],
            "status": "skipped",
            "reason": str(selection.get("no_candidate_reason") or "没有符合筛选标准的候选选题。"),
        }, output_path, ensure_ascii=False, indent=2)
        print(f"没有可制作的候选选题，已跳过: {output_path}")
        return output_path

    results = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate.get("topic_id"):
            continue
        topic_id = str(candidate["topic_id"])
        if topic_ids is not None and topic_id not in topic_ids:
            continue
        topic_paths = _candidate_topic_paths(paths, topic_id)
        topic_selection = {**selection, "selected_topic_id": topic_id}
        write_json(topic_selection, topic_paths.root / "selected_topic.json", ensure_ascii=False, indent=2)
        try:
            plan_parliament_commentary(topic_paths)
            translate_commentary_dialogue(topic_paths)
            generate_commentary_tts(topic_paths)
            render_commentary_preview(topic_paths)
            final_path = create_commentary_short_video(topic_paths)
            results.append({
                "topic_id": topic_id,
                "title": candidate.get("title", ""),
                "status": "completed",
                "workspace": str(topic_paths.root),
                "final_video_path": str(final_path),
                "cover_path": str(topic_paths.root / "commentary_cover.png"),
            })
        except Exception as error:
            results.append({
                "topic_id": topic_id,
                "title": candidate.get("title", ""),
                "status": "failed",
                "workspace": str(topic_paths.root),
                "error": str(error),
            })

    output_path = paths.root / "candidate_topic_outputs.json"
    write_json({"source_selection": str(selected_path), "topics": results}, output_path, ensure_ascii=False, indent=2)
    media_data = read_json(paths.media)
    media_data["main"]["candidate_topic_outputs_path"] = str(output_path)
    write_json(media_data, paths.media)
    if not any(item["status"] == "completed" for item in results):
        raise RuntimeError("所有候选选题都未能生成成片；请查看 candidate_topic_outputs.json")
    # Candidate production is the publish workflow: every completed local video
    # is uploaded automatically unless the run itself fails before this point.
    upload_all_candidate_topic_videos(paths)
    print(f"全部候选选题制作完成: {len(results)} 条: {output_path}")
    return output_path


def _is_strictly_continuous_indices(indices: object, allowed: set[int]) -> bool:
    return (
        isinstance(indices, list)
        and bool(indices)
        and all(isinstance(item, int) and item in allowed for item in indices)
        and indices == list(range(indices[0], indices[-1] + 1))
    )


def plan_parliament_commentary(paths: ProjectPaths) -> Path:
    """Create a search-style narration/original-dialogue plan for one topic."""
    selected_path = paths.root / "selected_topic.json"
    segments_path = paths.root / "content_segments.json"
    if not selected_path.exists() or not segments_path.exists():
        raise ValueError("缺少选题或内容分段；请先运行 --step segment 和 --step select-topic")
    selected_topic = read_json(selected_path)
    content_segments = read_json(segments_path).get("segments", [])
    selected_id = selected_topic.get("selected_topic_id")
    candidate = next(
        (item for item in selected_topic.get("candidates", []) if item.get("topic_id") == selected_id),
        None,
    )
    if not candidate:
        raise ValueError("selected_topic.json 中没有有效的 selected_topic_id")

    # Each candidate needs its own editorial framing.  Never carry the primary
    # candidate's top-level angle into a different topic.
    is_primary_candidate = candidate.get("topic_id") == selected_topic.get("selected_topic_id")
    candidate_angle = str(candidate.get("commentary_angle") or "")
    candidate_takeaway = str(candidate.get("viewer_takeaway") or "")
    if is_primary_candidate:
        candidate_angle = candidate_angle or str(selected_topic.get("commentary_angle") or "")
        candidate_takeaway = candidate_takeaway or str(selected_topic.get("viewer_takeaway") or "")
    topic_context = {
        "selected_topic_id": candidate["topic_id"],
        "candidates": [candidate],
        "commentary_angle": candidate_angle,
        "viewer_takeaway": candidate_takeaway,
    }

    selected_segment_ids = set(candidate.get("segment_ids", []))
    chosen_ranges = [
        item for index, item in enumerate(content_segments, start=1)
        if f"s{index:02d}" in selected_segment_ids
    ]
    subtitles = read_json(paths.subtitles["json"])
    all_utterances = subtitles.get("utterances", [])
    allowed_indices = {
        index
        for segment in chosen_ranges
        for index in range(segment["start_index"], segment["end_index"] + 1)
    }
    utterances = [
        {**item, "index": index}
        for index, item in enumerate(all_utterances)
        if index in allowed_indices
    ]
    if not utterances:
        raise ValueError("选题没有可用字幕")

    media_data = read_json(paths.media)
    source_context = media_data.get("main", {}).get("source_context", {})
    advertisement = media_data.get("main", {}).get("advertisement")
    if not isinstance(advertisement, str) or not advertisement.strip():
        advertisement = None
    else:
        advertisement = advertisement.strip()
    plan = ChatGPT(usage_report_path=paths.llm_cost_report).plan_parliament_commentary(
        topic_context, source_context, utterances, advertisement
    )
    raw_segments = plan.get("segments") if isinstance(plan, dict) else None
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("解说计划缺少 segments")

    validated_segments = []
    previous_index = -1
    for number, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            continue
        segment_type = item.get("type")
        if segment_type == "narration_only":
            key = "visual_subtitle_indices"
        elif segment_type == "with_dialogue":
            key = "dialogue_subtitle_indices"
        else:
            continue
        indices = item.get(key)
        if not _is_strictly_continuous_indices(indices, allowed_indices):
            continue
        # A dubbed dialogue clip has exactly one synthetic voice.  Do not let a
        # journalist's question and a minister's answer pass plan validation as
        # one clip: that would only fail later, after the plan has been saved.
        if segment_type == "with_dialogue":
            speakers = {
                all_utterances[index].get("attribute", {}).get("speaker")
                for index in indices
            }
            if len(speakers) != 1 or None in speakers or "UNKNOWN" in speakers:
                continue
        if indices[0] <= previous_index:
            continue
        previous_index = indices[-1]
        validated_segment = {
            "segment_id": number,
            "type": segment_type,
            "purpose": str(item.get("purpose") or ""),
            "narration": str(item.get("narration") or ""),
            key: indices,
        }
        if isinstance(item.get("audience_question"), str) and item["audience_question"].strip():
            validated_segment["audience_question"] = item["audience_question"].strip()
        if item.get("advertisement") is True:
            validated_segment["advertisement"] = True
        validated_segments.append(validated_segment)
    if not validated_segments:
        raise ValueError("解说计划没有可用且顺序正确的段落")

    output = {
        "selected_topic": candidate,
        "commentary_angle": candidate_angle,
        "viewer_takeaway": candidate_takeaway,
        "title": str(candidate.get("title") or ""),
        "summary": str(plan.get("summary") or ""),
        "segments": validated_segments,
    }
    advertisement_segments = [item["segment_id"] for item in validated_segments if item.get("advertisement")]
    if advertisement:
        output["advertisement"] = {
            "source": advertisement,
            "segment_ids": advertisement_segments,
        }
    output_path = paths.root / "commentary_plan.json"
    write_json(output, output_path, ensure_ascii=False, indent=2)
    media_data["main"]["commentary_plan_path"] = str(output_path)
    write_json(media_data, paths.media)
    print(f"解说分镜规划完成: {len(validated_segments)} 段: {output_path}")
    return output_path


def translate_commentary_dialogue(paths: ProjectPaths) -> Path:
    """Translate planned original dialogue and assign a gender-matched voice."""
    plan_path = paths.root / "commentary_plan.json"
    if not plan_path.exists():
        raise ValueError("缺少 commentary_plan.json；请先运行 --step plan")
    plan = read_json(plan_path)
    subtitles = read_json(paths.subtitles["json"]).get("utterances", [])
    media_data = read_json(paths.media)
    genders = media_data.get("main", {}).get("speaker_gender_mapping", {})

    dialogue_rows = []
    for segment in plan.get("segments", []):
        if segment.get("type") != "with_dialogue":
            continue
        indices = segment.get("dialogue_subtitle_indices", [])
        if not indices or any(not isinstance(index, int) or index >= len(subtitles) for index in indices):
            raise ValueError(f"segment {segment.get('segment_id')} 缺少有效的原声字幕索引")
        utterances = [subtitles[index] for index in indices]
        speakers = {
            item.get("attribute", {}).get("speaker") for item in utterances
        }
        if len(speakers) != 1 or None in speakers:
            raise ValueError(f"segment {segment.get('segment_id')} 的中文配音必须对应单一 speaker")
        speaker = speakers.pop()
        dialogue_rows.append({
            "segment_id": segment["segment_id"],
            "speaker": speaker,
            "speaker_name": utterances[0].get("attribute", {}).get("speaker_name") or speaker,
            "subtitle_indices": indices,
            "english_text": " ".join(item.get("text", "").strip() for item in utterances),
        })
    if not dialogue_rows:
        output_path = paths.root / "dialogue_dubbing.json"
        write_json([], output_path, ensure_ascii=False, indent=2)
        write_json(plan, plan_path, ensure_ascii=False, indent=2)
        media_data["main"]["dialogue_dubbing_path"] = str(output_path)
        media_data["main"]["dialogue_voice_mapping"] = {}
        write_json(media_data, paths.media)
        print("当前解说计划没有人物台词段，将只生成中文旁白")
        return output_path

    translation_input = [
        {"index": index, "text": row["english_text"]}
        for index, row in enumerate(dialogue_rows)
    ]
    translation_result = ChatGPT(usage_report_path=paths.llm_cost_report).translate_subtitles(
        translation_input
    )
    translation_map = {
        item.get("index"): item.get("text")
        for item in translation_result.get("translations", [])
        if isinstance(item, dict) and isinstance(item.get("index"), int) and isinstance(item.get("text"), str)
    }
    if set(translation_map) != set(range(len(dialogue_rows))):
        raise ValueError("人物原声翻译缺少或包含无效序号")

    speakers = sorted({row["speaker"] for row in dialogue_rows})
    voice_mapping = {}
    voice_lists = {"male": MALE_DIALOGUE_TTS_VOICES, "female": FEMALE_DIALOGUE_TTS_VOICES}
    for gender in ("male", "female"):
        matching = [speaker for speaker in speakers if genders.get(speaker, {}).get("gender") == gender]
        for index, speaker in enumerate(matching):
            voice_mapping[speaker] = voice_lists[gender][index % len(voice_lists[gender])]
    missing = [speaker for speaker in speakers if speaker not in voice_mapping]
    if missing:
        raise ValueError(f"这些 speaker 缺少男女判断，无法分配配音：{', '.join(missing)}")

    records = []
    by_segment = {}
    for index, row in enumerate(dialogue_rows):
        record = {
            **row,
            "chinese_text": translation_map[index],
            "gender": genders[row["speaker"]]["gender"],
            "gender_confidence": genders[row["speaker"]].get("confidence"),
            "voice": voice_mapping[row["speaker"]],
        }
        records.append(record)
        by_segment[row["segment_id"]] = record
    for segment in plan["segments"]:
        record = by_segment.get(segment.get("segment_id"))
        if record:
            segment["dubbed_dialogue"] = {
                key: record[key] for key in (
                    "speaker", "speaker_name", "subtitle_indices", "english_text",
                    "chinese_text", "gender", "gender_confidence", "voice",
                )
            }

    output_path = paths.root / "dialogue_dubbing.json"
    write_json(records, output_path, ensure_ascii=False, indent=2)
    write_json(plan, plan_path, ensure_ascii=False, indent=2)
    media_data["main"]["dialogue_dubbing_path"] = str(output_path)
    media_data["main"]["dialogue_voice_mapping"] = voice_mapping
    write_json(media_data, paths.media)
    print(f"人物中文配音准备完成: {len(records)} 段: {output_path}")
    return output_path


def generate_commentary_tts(paths: ProjectPaths) -> Path:
    """Generate fixed-narrator TTS and gender-matched character dub TTS."""
    plan_path = paths.root / "commentary_plan.json"
    dubbing_path = paths.root / "dialogue_dubbing.json"
    if not plan_path.exists() or not dubbing_path.exists():
        raise ValueError("缺少解说计划或人物配音稿；请先运行 --step translate-dialogue")
    plan = read_json(plan_path)
    dubbing_records = read_json(dubbing_path)
    dubbing_by_segment = {item["segment_id"]: item for item in dubbing_records}
    tts = Volcengine()
    tts_dir = paths.root / "commentary_tts"

    for segment in plan.get("segments", []):
        segment_id = segment.get("segment_id")
        narration = str(segment.get("narration") or "").strip()
        if not narration:
            raise ValueError(f"segment {segment_id} 缺少旁白")
        narration_path = tts_dir / f"segment_{segment_id:02d}_narration.mp3"
        segment["narration_audio_path"] = str(narration_path)
        segment["narration_duration_ms"] = tts.generate_tts(
            narration, narration_path, speaker=NARRATOR_TTS_VOICE
        )
        boost_tts_audio(narration_path)

        audience_question = str(segment.get("audience_question") or "").strip()
        if audience_question:
            if not audience_question.startswith("那么问题来了"):
                audience_question = f"那么问题来了：{audience_question.lstrip('：: ')}"
                segment["audience_question"] = audience_question
            question_path = tts_dir / f"segment_{segment_id:02d}_question.mp3"
            segment["audience_question_audio_path"] = str(question_path)
            segment["audience_question_duration_ms"] = tts.generate_tts(
                audience_question, question_path, speaker=NARRATOR_TTS_VOICE
            )
            boost_tts_audio(question_path)

        if segment.get("type") != "with_dialogue":
            continue
        dub = dubbing_by_segment.get(segment_id)
        if not dub:
            raise ValueError(f"segment {segment_id} 缺少人物中文配音稿")
        dub_path = tts_dir / f"segment_{segment_id:02d}_dialogue.mp3"
        dub["audio_path"] = str(dub_path)
        dub["duration_ms"] = tts.generate_tts(
            dub["chinese_text"], dub_path, speaker=dub["voice"]
        )
        boost_tts_audio(dub_path)
        segment.setdefault("dubbed_dialogue", {}).update({
            "audio_path": dub["audio_path"], "duration_ms": dub["duration_ms"],
        })

    write_json(plan, plan_path, ensure_ascii=False, indent=2)
    write_json(dubbing_records, dubbing_path, ensure_ascii=False, indent=2)
    media_data = read_json(paths.media)
    media_data["main"]["commentary_tts"] = {
        "directory": str(tts_dir),
        "narrator_voice": NARRATOR_TTS_VOICE,
    }
    write_json(media_data, paths.media)
    print(f"解说与人物中文 TTS 完成: {tts_dir}")
    return plan_path


def refresh_all_commentary_questions(paths: ProjectPaths) -> Path:
    """Refresh only the closing-question audio and local renders for completed topic outputs."""
    topic_paths_list = [paths]
    manifest_path = paths.root / "candidate_topic_outputs.json"
    if manifest_path.exists():
        for item in read_json(manifest_path).get("topics", []):
            if item.get("status") == "completed" and item.get("topic_id"):
                topic_paths_list.append(_candidate_topic_paths(paths, str(item["topic_id"])))

    refreshed = []
    for topic_paths in topic_paths_list:
        plan_path = topic_paths.root / "commentary_plan.json"
        if not plan_path.exists():
            continue
        plan = read_json(plan_path)
        if not any(segment.get("audience_question") for segment in plan.get("segments", [])):
            continue
        generate_commentary_tts(topic_paths)
        render_commentary_preview(topic_paths)
        final_path = create_commentary_short_video(topic_paths)
        refreshed.append(str(final_path))
    output_path = paths.root / "refreshed_commentary_questions.json"
    write_json({"videos": refreshed}, output_path, ensure_ascii=False, indent=2)
    return output_path


def render_commentary_preview(paths: ProjectPaths) -> Path:
    """Render a horizontal review cut before any vertical crop or subtitles."""
    plan_path = paths.root / "commentary_plan.json"
    if not plan_path.exists():
        raise ValueError("缺少 commentary_plan.json；请先运行 --step tts")
    plan = read_json(plan_path)
    subtitles = read_json(paths.subtitles["json"]).get("utterances", [])
    source_duration = get_duration(paths.video)
    render_dir = paths.root / "commentary_preview_segments"
    render_dir.mkdir(parents=True, exist_ok=True)
    rendered = []

    for segment in plan.get("segments", []):
        segment_id = int(segment["segment_id"])
        narration_audio = Path(segment["narration_audio_path"])
        narration_duration_s = int(segment["narration_duration_ms"]) / 1000
        if not narration_audio.exists():
            raise ValueError(f"segment {segment_id} 缺少主播旁白音频")

        if segment["type"] == "narration_only":
            indices = segment.get("visual_subtitle_indices", [])
            if not indices:
                raise ValueError(f"segment {segment_id} 缺少画面锚点")
            anchor = subtitles[indices[0]]
            start, end = fit_forward_video_range(
                anchor["start_time"] / 1000, narration_duration_s, source_duration
            )
            visual_path = render_dir / f"{segment_id:02d}_visual.mp4"
            final_path = render_dir / f"{segment_id:02d}_final.mp4"
            cut_video_range(paths.video, visual_path, start, end)
            replace_video_audio(visual_path, narration_audio, final_path)
            render_info = {
                "type": "narration_only", "visual_range_seconds": {"start": start, "end": end},
                "source_range_seconds": {"start": start, "end": end},
                "final_video_path": str(final_path),
            }
        elif segment["type"] == "with_dialogue":
            dub = segment.get("dubbed_dialogue", {})
            indices = dub.get("subtitle_indices") or segment.get("dialogue_subtitle_indices", [])
            if not indices or not dub.get("audio_path") or not dub.get("duration_ms"):
                raise ValueError(f"segment {segment_id} 缺少人物中文配音资料")
            dialogue_start = subtitles[indices[0]]["start_time"] / 1000
            dialogue_end = subtitles[indices[-1]]["end_time"] / 1000
            prelude_start = max(0, dialogue_start - narration_duration_s)
            prelude_visual = render_dir / f"{segment_id:02d}_prelude_visual.mp4"
            prelude_final = render_dir / f"{segment_id:02d}_prelude_final.mp4"
            dubbed_final = render_dir / f"{segment_id:02d}_dubbed.mp4"
            final_path = render_dir / f"{segment_id:02d}_final.mp4"
            cut_video_range(paths.video, prelude_visual, prelude_start, dialogue_start)
            replace_video_audio(prelude_visual, narration_audio, prelude_final)
            speed = dub_video_segment(
                paths.video, Path(dub["audio_path"]), dubbed_final,
                int(dialogue_start * 1000), int(dialogue_end * 1000), int(dub["duration_ms"]),
            )
            concat_preview_clips(
                [prelude_final, dubbed_final], final_path,
                render_dir / f"{segment_id:02d}_concat.txt",
            )
            render_info = {
                "type": "with_dialogue_dubbed",
                "narration_visual_range_seconds": {"start": prelude_start, "end": dialogue_start},
                "dubbed_dialogue_range_seconds": {"start": dialogue_start, "end": dialogue_end},
                "source_range_seconds": {"start": prelude_start, "end": dialogue_end},
                "dubbed_video_speed": speed,
                "final_video_path": str(final_path),
            }
        else:
            raise ValueError(f"未知分镜类型: {segment['type']}")

        question_audio_path = segment.get("audience_question_audio_path")
        question_duration_ms = segment.get("audience_question_duration_ms")
        if question_audio_path and question_duration_ms:
            question_duration_s = int(question_duration_ms) / 1000
            question_start = render_info["source_range_seconds"]["end"]
            question_start, question_end = fit_forward_video_range(
                question_start, question_duration_s, source_duration
            )
            question_visual = render_dir / f"{segment_id:02d}_question_visual.mp4"
            question_final = render_dir / f"{segment_id:02d}_question_final.mp4"
            combined_final = render_dir / f"{segment_id:02d}_with_question.mp4"
            cut_video_range(paths.video, question_visual, question_start, question_end)
            replace_video_audio(question_visual, Path(question_audio_path), question_final)
            concat_preview_clips(
                [render_info["final_video_path"], question_final], combined_final,
                render_dir / f"{segment_id:02d}_question_concat.txt",
            )
            render_info["final_video_path"] = str(combined_final)
            render_info["audience_question_visual_range_seconds"] = {
                "start": question_start, "end": question_end,
            }
            render_info["source_range_seconds"]["end"] = question_end
        segment["render_preview"] = render_info
        rendered.append(render_info)

    output_path = paths.root / "commentary_preview_horizontal.mp4"
    timeline_paths = []
    previous_source_end = None
    for index, render_info in enumerate(rendered, start=1):
        source_range = render_info["source_range_seconds"]
        if previous_source_end is not None and abs(source_range["start"] - previous_source_end) > 0.15:
            render_info["crossfade_before_seconds"] = 0.12
        timeline_paths.append(render_info["final_video_path"])
        previous_source_end = source_range["end"]
    crossfade_preview_clips(timeline_paths, output_path)
    write_json(plan, plan_path, ensure_ascii=False, indent=2)
    media_data = read_json(paths.media)
    media_data["main"]["commentary_preview_horizontal_path"] = str(output_path)
    write_json(media_data, paths.media)
    print(f"横版混音预览完成: {output_path}")
    return output_path


def write_commentary_chinese_subtitles(paths: ProjectPaths, preview_path: Path) -> Path:
    """Build explicitly wrapped subtitles from the existing script and TTS timing."""
    from pipeline.avatar_video import build_timeline, video_duration, write_script_subtitles

    plan = read_json(paths.root / "commentary_plan.json")
    events = build_timeline(plan, paths.root, video_duration(preview_path))
    write_json(events, paths.root / "commentary_layout_timeline.json")
    write_script_subtitles(events, paths.final_subtitles["srt"],
                           paths.root / "final_subtitles.ass", paths.final_subtitles["json"])
    return paths.final_subtitles["srt"]


def create_commentary_short_video(paths: ProjectPaths) -> Path:
    """Compose animated avatar/news layout, then burn script-derived subtitles."""
    from pipeline.avatar_video import render_avatar_layout, burn_avatar_subtitles, prepend_cover
    from pipeline.cover import create_portrait_cover, create_landscape_cover

    media_data, media_path = _read_workspace_media(paths)
    main_media = media_data["main"]
    preview_path = paths.root / "commentary_preview_horizontal.mp4"
    if not preview_path.exists():
        raise ValueError("缺少横版预览；请先运行 --step preview")
    plan = read_json(paths.root / "commentary_plan.json")
    selection_path = paths.root / "selected_topic.json"
    selection = read_json(selection_path) if selection_path.exists() else {}
    candidate = next((item for item in selection.get("candidates", [])
                      if item.get("topic_id") == selection.get("selected_topic_id")), {})
    subtitle = str(candidate.get("title") or plan.get("title") or main_media.get("task_subtitle") or "")
    cover_path = create_portrait_cover(subtitle, paths.root / "commentary_cover.png")
    landscape_cover = create_landscape_cover(subtitle, paths.root / "commentary_cover_landscape.png")
    layout_path = paths.root / "commentary_avatar_layout.mp4"
    body_path = paths.root / "commentary_body.mp4"
    final_path = paths.root / "commentary_news.mp4"
    print("========== 10.1 生成封面、保留完整新闻画面 ==========", flush=True)
    srt_path = write_commentary_chinese_subtitles(paths, preview_path)
    events = read_json(paths.root / "commentary_layout_timeline.json")
    print("========== 10.2 解说与原声画中画动画 ==========", flush=True)
    render_avatar_layout(preview_path, layout_path, events)
    print("========== 10.3 烧录得意黑字幕（程序换行） ==========", flush=True)
    burn_avatar_subtitles(layout_path, paths.root / "final_subtitles.ass", body_path)
    print("========== 10.4 插入 1 秒片头封面 ==========", flush=True)
    prepend_cover(body_path, cover_path, final_path)
    main_media["commentary_cover_path"] = str(cover_path)
    main_media["commentary_cover_landscape_path"] = str(landscape_cover)
    main_media["commentary_body_video_path"] = str(body_path)
    main_media["commentary_chinese_subtitles_path"] = str(srt_path)
    main_media.pop("commentary_cropped_4_3_video_path", None)
    main_media["commentary_layout_source_video_path"] = str(preview_path)
    main_media["commentary_vertical_video_path"] = str(layout_path)
    main_media["commentary_news_video_path"] = str(final_path)
    main_media["news_title"] = str(main_media.get("task_title") or "澳洲政策解读")
    main_media["news_subtitle"] = subtitle
    main_media.setdefault("commentary_covers", {})[str(paths.root)] = str(cover_path)
    main_media.setdefault("commentary_subtitles", {})[str(paths.root)] = {
        "source": "script_duration_estimate",
        "final_video_offset_seconds": 1.0,
        "source_video_path": str(preview_path),
        "srt_path": str(srt_path),
        "ass_path": str(paths.root / "final_subtitles.ass"),
        "json_path": str(paths.final_subtitles["json"]),
    }
    write_json(media_data, media_path)
    return final_path


def upload_commentary_short_video(paths: ProjectPaths) -> str:
    """Upload the finished Parliament commentary to its existing Drive workflow."""
    from services.google_drive import upload_to_drive

    media_data = read_json(paths.media)
    main_media = media_data["main"]
    video_path = main_media.get("commentary_news_video_path")
    if not video_path or not Path(video_path).exists():
        raise ValueError("缺少发布版视频；请先运行 --step final")
    folder_name = str(main_media.get("task_title") or "澳洲政策解读")
    filename = f"{safe_filename(main_media.get('news_subtitle') or folder_name)}.mp4"
    file_id = upload_to_drive(video_path, folder_name=folder_name, filename=filename)
    main_media["google_drive"] = {
        "folder_name": folder_name,
        "file_id": file_id,
        "filename": filename,
        "video_path": str(video_path),
    }
    write_json(media_data, paths.media)
    return file_id


def upload_all_candidate_topic_videos(paths: ProjectPaths) -> Path:
    """Upload every completed candidate-topic video with its own title-based filename."""
    from services.google_drive import upload_to_drive

    output_path = paths.root / "candidate_topic_outputs.json"
    if not output_path.exists():
        raise ValueError("缺少 candidate_topic_outputs.json；请先运行 --step all-topics")
    output = read_json(output_path)
    folder_name = str(read_json(paths.media)["main"].get("task_title") or "澳洲政策解读")
    for item in output.get("topics", []):
        if item.get("status") != "completed":
            continue
        video_path = Path(item.get("final_video_path") or "")
        if not video_path.exists():
            item["upload_status"] = "failed"
            item["upload_error"] = "发布版视频文件不存在"
            continue
        filename = f"{safe_filename(item.get('title') or item.get('topic_id') or 'topic')}.mp4"
        file_id = upload_to_drive(video_path, folder_name=folder_name, filename=filename)
        item["google_drive"] = {
            "folder_name": folder_name,
            "file_id": file_id,
            "filename": filename,
        }
        item["upload_status"] = "completed"
    write_json(output, output_path, ensure_ascii=False, indent=2)
    return output_path


class ParliamentVideoPipeline:
    """Parliament-specific source for the existing main.py commentary flow.

    It reuses the main commentary flow's speaker recognition, topic planning,
    structured script, TTS and edit stages.  YouTube captions are retained as
    a reference, but the production subtitle timeline is cloud-transcribed.
    """

    def __init__(self, project_paths: ProjectPaths):
        self.project_paths = project_paths

    def download_sources_and_captions(
        self, urls: str | list[str], title: str | None = None, subtitle: str | None = None, advertisement: str | None = None
    ) -> None:
        """Run main-flow step 1: source video plus available English captions."""
        if isinstance(urls, str):
            urls = [urls]
        if not urls:
            raise ValueError("任务缺少 urls")

        download_video(
            urls=urls,
            output_path=self.project_paths.video,
            origin_path=self.project_paths.origin,
            media_path=self.project_paths.media,
        )

        media_data = read_json(self.project_paths.media)
        media_data["main"]["task_title"] = title or ""
        media_data["main"]["task_subtitle"] = subtitle or ""
        if advertisement:
            media_data["main"]["advertisement"] = advertisement
        caption_paths: list[str] = []
        for index, source in enumerate(media_data["sources"]):
            caption_path = download_english_caption(
                source["url"], self.project_paths.origin, index
            )
            source["source_caption"] = {
                "srt_path": str(caption_path) if caption_path else None,
                "language": "en-orig" if caption_path else None,
                "available": caption_path is not None,
            }
            if caption_path:
                caption_paths.append(str(caption_path))

        media_data["main"]["source_caption_paths"] = caption_paths
        if len(caption_paths) == 1:
            import_caption_for_main_flow(Path(caption_paths[0]), self.project_paths)
            media_data["main"]["subtitles"] = {
                "srt_path": str(self.project_paths.subtitles["srt"]),
                "json_path": str(self.project_paths.subtitles["json"]),
                "source": "youtube_caption",
            }
        elif len(caption_paths) > 1:
            print("多视频任务暂未自动合并字幕；已保留每个源视频各自的 caption。")
        write_json(media_data, self.project_paths.media)
        record_source_metadata(self.project_paths)
        print(f"第 1 步完成，工作区: {self.project_paths.root}")

    def run(self, urls, title, subtitle=None, advertisement=None, **_unused) -> None:
        """Run one source job through production and upload every candidate."""
        print("========== 1. 下载视频和英文字幕 ==========")
        self.download_sources_and_captions(urls, title, subtitle, advertisement)
        print("========== 1.05 云端英文字幕识别 ==========")
        transcribe_parliament_english_subtitles(self.project_paths)
        print("========== 1.1 AI 整合英文短句 ==========")
        merge_english_subtitles_before_diarization(self.project_paths)
        print("========== 2. 语音聚类 ==========")
        classify_speakers(self.project_paths)
        print("========== 2.1 声音性别判断 ==========")
        classify_speaker_genders(self.project_paths)
        print("========== 3. 说话人识别 ==========")
        recognise_parliament_speakers(self.project_paths)
        print("========== 4. 内容分段 ==========")
        segment_parliament_content(self.project_paths)
        print("========== 5. 华人日常选题 ==========")
        select_chinese_australia_topic(self.project_paths)
        print("========== 5.1 制作并上传全部候选选题 ==========")
        produce_all_candidate_topics(self.project_paths)


def main(tasks_path: str | Path = "conference_tasks.json") -> None:
    """Run every Parliament task through rendering and Google Drive upload."""
    jobs = read_json(tasks_path)
    if not isinstance(jobs, list):
        raise ValueError("任务文件必须是 JSON 数组")

    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            raise ValueError(f"任务 {index} 必须是 JSON 对象")
        urls = job.get("urls") or job.get("url")
        if not urls:
            raise ValueError(f"任务 {index} 缺少 url 或 urls")
        advertisement = job.get("广告") if "广告" in job else job.get("advertisement")
        if advertisement is not None and not isinstance(advertisement, str):
            raise ValueError(f"任务 {index} 的广告必须是字符串或 null")
        paths = create_workspace(job.get("subtitle") or job.get("title"))
        ParliamentVideoPipeline(paths).run(
            urls=urls,
            title=job.get("title"),
            subtitle=job.get("subtitle"),
            advertisement=advertisement.strip() if isinstance(advertisement, str) and advertisement.strip() else None,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create and upload all Australian Parliament commentary videos."
    )
    parser.add_argument(
        "--tasks",
        default="conference_tasks.json",
        help="JSON task file path (default: conference_tasks.json)",
    )
    parser.add_argument(
        "--workspace",
        help="Existing workspace to process (required for every --step except download)",
    )
    parser.add_argument(
        "--step",
        choices=("download", "merge", "cluster", "gender", "recognise", "segment", "select-topic", "all-topics", "refresh-questions", "plan", "translate-dialogue", "tts", "preview", "final", "upload", "upload-topics", "metadata"),
        default="download",
        help="Workflow checkpoint to run; without --step, runs the full workflow and uploads all topics",
    )
    parser.add_argument(
        "--topic-ids",
        help="Comma-separated candidate topic IDs; only used by --step all-topics",
    )
    arguments = parser.parse_args()
    if arguments.step in {"merge", "cluster", "gender", "recognise", "segment", "select-topic", "all-topics", "refresh-questions", "plan", "translate-dialogue", "tts", "preview", "final", "upload", "upload-topics", "metadata"}:
        if not arguments.workspace:
            parser.error(f"--step {arguments.step} requires --workspace")
        paths = ProjectPaths(arguments.workspace)
        if arguments.step == "merge":
            print("========== 1.1 AI 整合英文短句 ==========")
            merge_english_subtitles_before_diarization(paths)
        elif arguments.step == "cluster":
            print("========== 2. 语音聚类 ==========")
            classify_speakers(paths)
        elif arguments.step == "gender":
            print("========== 2.1 声音性别判断 ==========")
            classify_speaker_genders(paths)
        elif arguments.step == "recognise":
            print("========== 3. 说话人识别 ==========")
            recognise_parliament_speakers(paths)
        elif arguments.step == "segment":
            print("========== 4. 内容分段 ==========")
            segment_parliament_content(paths)
        elif arguments.step == "select-topic":
            print("========== 5. 华人日常选题 ==========")
            select_chinese_australia_topic(paths)
        elif arguments.step == "all-topics":
            print("========== 5.1 制作全部候选选题 ==========")
            requested_topic_ids = (
                {item.strip() for item in arguments.topic_ids.split(",") if item.strip()}
                if arguments.topic_ids else None
            )
            produce_all_candidate_topics(paths, requested_topic_ids)
        elif arguments.step == "refresh-questions":
            print("========== 5.2 更新片尾互动 ==========")
            refresh_all_commentary_questions(paths)
        elif arguments.step == "plan":
            print("========== 6. 解说分镜规划 ==========")
            plan_parliament_commentary(paths)
        elif arguments.step == "translate-dialogue":
            print("========== 7. 人物原声中文配音准备 ==========")
            translate_commentary_dialogue(paths)
        elif arguments.step == "tts":
            print("========== 8. 生成解说与人物中文配音 ==========")
            generate_commentary_tts(paths)
        elif arguments.step == "preview":
            print("========== 9. 生成横版混音预览 ==========")
            render_commentary_preview(paths)
        elif arguments.step == "final":
            print("========== 10. 裁画面、烧录字幕与标题、生成竖版成片 ==========")
            create_commentary_short_video(paths)
        elif arguments.step == "upload":
            print("========== 11. 上传发布版视频 ==========")
            upload_commentary_short_video(paths)
        elif arguments.step == "upload-topics":
            print("========== 11. 上传全部候选成片 ==========")
            upload_all_candidate_topic_videos(paths)
        else:
            print("========== 1.2 写入 YouTube 元数据 ==========")
            record_source_metadata(paths)
    else:
        main(arguments.tasks)
