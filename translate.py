"""Translation workflow.

Step 1 downloads a source video into a fresh workspace for every run.
"""

from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from core.path import ProjectPaths
from core.demucs import extract_vocals_demucs
from core.framing import crop_to_four_three, four_three_to_vertical
from core.ffmpeg import add_subtitles, add_text_overlay, concat_media, dub_video_segment
from core.utils import ms_to_srt_time
from core.utils import read_json, safe_filename, write_json
from pipeline.audio import export_audio
from pipeline.download import download_video
from services.chatgpt import ChatGPT
from services.volcengine import Volcengine

MALE_NEWS_TTS_VOICES = [
    "zh_male_liufei_uranus_bigtts",
    "zh_male_m191_uranus_bigtts",
    "ICL_uranus_zh_male_lvchaxiaoge_tob",
]

FEMALE_NEWS_TTS_VOICES = [
    "ICL_uranus_zh_female_kefunvshengwenhecuishou_tob",
    "zh_female_meilinvyou_uranus_bigtts",
    "zh_female_gufengshaoyu_uranus_bigtts",
    "zh_female_tvbnv_uranus_bigtts",
]

def create_workspace(title: str | None = None) -> ProjectPaths:
    """Create and return an isolated workspace for one translation job."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = safe_filename(title) if title else "translation"
    workspace = Path("work") / "translate" / f"{timestamp}_{name}_{uuid4().hex[:8]}"
    return ProjectPaths(workspace)


def download_source_video(
    urls: str | list[str], title: str | None = None, subtitle: str | None = None,
) -> ProjectPaths:
    """Create a new workspace, then download the source video into it."""
    paths = create_workspace(title)
    download_video(
        urls=urls,
        output_path=paths.video,
        origin_path=paths.origin,
        media_path=paths.media,
    )
    media_data = read_json(paths.media)
    media_data["main"]["task_title"] = title or ""
    if isinstance(subtitle, str) and subtitle.strip():
        media_data["main"]["task_subtitle"] = subtitle.strip()
    write_json(media_data, paths.media)
    return paths


def extract_source_audio(paths: ProjectPaths) -> None:
    """Extract and merge source vocals, recording all outputs in media.json."""
    media_data = read_json(paths.media)
    vocals_paths = []

    for index, media in enumerate(media_data["sources"]):
        audio_path = paths.audio_dir / f"{index:03d}.mp3"
        export_audio(Path(media["video_path"]), audio_path)
        vocals_path = extract_vocals_demucs(audio_path)

        media["audio_path"] = str(audio_path)
        media["vocals_path"] = str(vocals_path)
        vocals_paths.append(vocals_path)

    with open(paths.vocals_filelist, "w", encoding="utf-8") as file:
        for vocals_path in vocals_paths:
            file.write(f"file '{vocals_path.absolute()}'\n")

    concat_media(paths.vocals_filelist, paths.audio)
    media_data["main"]["vocals_audio_path"] = str(paths.audio)
    write_json(media_data, paths.media)


def transcribe_english_subtitles(paths: ProjectPaths) -> None:
    """Recognize English subtitles from the merged source vocals."""
    media_data = read_json(paths.media)
    main_media = media_data["main"]

    Volcengine().transcribe_audio(
        main_media["vocals_audio_path"],
        paths.subtitles,
        language="en-US",
    )
    main_media["subtitles"] = {
        "srt_path": str(paths.subtitles["srt"]),
        "json_path": str(paths.subtitles["json"]),
    }
    write_json(media_data, paths.media)


def classify_speakers(paths: ProjectPaths) -> None:
    """Assign each recognized subtitle to its nearest primary speaker cluster."""
    from core.speechbrain import SpeechBrain

    media_data = read_json(paths.media)
    SpeechBrain().diarize_to_primary_clusters(
        media_data["main"]["vocals_audio_path"],
        paths.subtitles,
        threshold=0.75,
        min_cluster_ratio=0.05,
    )


def classify_speaker_genders(paths: ProjectPaths) -> dict:
    """Infer perceived voice gender from aggregated audio for each speaker cluster."""
    import torch
    import torchaudio

    subtitles = read_json(paths.subtitles["json"])
    media_data = read_json(paths.media)
    waveform, sample_rate = torchaudio.load(media_data["main"]["vocals_audio_path"])
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    speaker_audio = {}
    max_samples = sample_rate * 30
    for utterance in subtitles["utterances"]:
        speaker = utterance.get("attribute", {}).get("speaker", "UNKNOWN")
        if speaker == "UNKNOWN":
            continue
        start = int(utterance["start_time"] * sample_rate / 1000)
        end = int(utterance["end_time"] * sample_rate / 1000)
        chunk = waveform[:, start:end]
        if chunk.shape[1] < int(sample_rate * 0.3):
            continue
        existing = speaker_audio.get(speaker)
        if existing is None:
            speaker_audio[speaker] = chunk[:, :max_samples]
        elif existing.shape[1] < max_samples:
            remaining = max_samples - existing.shape[1]
            speaker_audio[speaker] = torch.cat((existing, chunk[:, :remaining]), dim=1)

    gender_audio_dir = paths.root / "gender_audio"
    genders = {}
    for speaker, audio in speaker_audio.items():
        audio_path = gender_audio_dir / f"{speaker}.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(audio_path, audio, sample_rate)
        gender_environment = {
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
        result = subprocess.run(
            [sys.executable, "-m", "core.voice_gender", str(audio_path)],
            capture_output=True,
            text=True,
            check=True,
            env=gender_environment,
        )
        genders[speaker] = json.loads(result.stdout.strip().splitlines()[-1])
    media_data["main"]["speaker_gender_mapping"] = genders
    write_json(media_data, paths.media)
    return genders


def export_speaker_english_subtitles(paths: ProjectPaths) -> Path:
    """Export each English subtitle with its assigned speaker."""
    subtitles = read_json(paths.subtitles["json"])
    output_path = paths.root / "speaker_english_subtitles.json"
    records = [
        {
            "speaker": utterance.get("attribute", {}).get("speaker", "UNKNOWN"),
            "english": {
                "text": utterance["text"],
                "start_time": utterance["start_time"],
                "end_time": utterance["end_time"],
            },
        }
        for utterance in subtitles["utterances"]
    ]
    write_json(records, output_path)

    media_data = read_json(paths.media)
    media_data["main"]["speaker_english_subtitles_path"] = str(output_path)
    write_json(media_data, paths.media)
    return output_path


def _validate_merge_groups(groups: list, blocks: list[dict], records: list[dict]) -> list[list[int]]:
    """Split AI groups at safe boundaries and reject missing, repeated, or disordered items."""
    if not isinstance(groups, list):
        raise ValueError("短句整合结果必须包含 groups 数组")
    index_to_block = {
        index: block["id"]
        for block in blocks
        for index, _ in block["items"]
    }
    normalized_groups = []
    for group in groups:
        if not isinstance(group, list) or not group or not all(isinstance(index, int) for index in group):
            raise ValueError(f"无效的短句整合组: {group}")
        if group != list(range(group[0], group[-1] + 1)):
            raise ValueError(f"短句整合组必须使用连续序号: {group}")
        safe_group = []
        for index in group:
            if safe_group and index_to_block[index] != index_to_block[safe_group[-1]]:
                normalized_groups.append(safe_group)
                safe_group = []
            safe_group.append(index)
        normalized_groups.append(safe_group)

    flattened = [index for group in normalized_groups for index in group]
    if flattened != list(range(len(records))):
        raise ValueError("短句整合结果必须按顺序且恰好覆盖全部原始字幕")
    return normalized_groups


def merge_english_subtitles_before_diarization(paths: ProjectPaths) -> Path:
    """Merge English subtitle fragments before any speaker labels are assigned."""
    subtitles = read_json(paths.subtitles["json"])
    utterances = subtitles["utterances"]
    raw_path = paths.root / "subtitles_raw.json"
    write_json(subtitles, raw_path)

    source_items = [[index, utterance["text"].strip()] for index, utterance in enumerate(utterances)]
    # The complete recognizer sequence is deliberately sent to Luna unchanged.
    # A single validation block checks ordering only; it does not limit meaning.
    blocks = [{"id": 0, "items": source_items}]
    groups = ChatGPT(usage_report_path=paths.llm_cost_report).merge_english_subtitles_before_diarization(source_items)
    try:
        groups = _validate_merge_groups(groups, blocks, utterances)
    except (KeyError, ValueError):
        # Do not alter recognizer boundaries when Luna returns malformed JSON.
        print("⚠️ AI 短句分组不完整，已保留原始识别字幕")
        groups = [[index] for index in range(len(utterances))]

    merged_utterances = []
    for source_indices in groups:
        source_utterances = [utterances[index] for index in source_indices]
        first, last = source_utterances[0], source_utterances[-1]
        merged = dict(first)
        merged.pop("attribute", None)
        merged["source_indices"] = source_indices
        merged["text"] = " ".join(item["text"].strip() for item in source_utterances)
        merged["start_time"] = first["start_time"]
        merged["end_time"] = last["end_time"]
        merged_utterances.append(merged)

    subtitles["utterances"] = merged_utterances
    write_json(subtitles, paths.subtitles["json"])
    media_data = read_json(paths.media)
    media_data["main"]["raw_subtitles"] = {
        "json_path": str(raw_path),
        "utterance_count": len(utterances),
    }
    media_data["main"]["merged_english_subtitle_count"] = len(merged_utterances)
    write_json(media_data, paths.media)
    return paths.subtitles["json"]


def translate_speaker_english_subtitles(paths: ProjectPaths) -> Path:
    """Add AI-generated Chinese translations to the exported subtitle records."""
    output_path = paths.root / "speaker_english_subtitles.json"
    records = read_json(output_path)
    translation_input = [
        {"index": index, "text": record["english"]["text"]}
        for index, record in enumerate(records)
    ]
    translation_result = ChatGPT(usage_report_path=paths.llm_cost_report).translate_subtitles(
        translation_input
    )
    translations = translation_result["translations"]

    translation_map = {}
    for translation in translations:
        index = translation.get("index")
        text = translation.get("text")
        if not isinstance(index, int) or not isinstance(text, str):
            raise ValueError(f"无效的字幕翻译结果: {translation}")
        translation_map[index] = text

    expected_indexes = set(range(len(records)))
    if set(translation_map) != expected_indexes:
        raise ValueError("字幕翻译结果缺少或包含无效序号")

    for index, record in enumerate(records):
        record["chinese"] = {
            "text": translation_map[index],
            "start_time": None,
            "end_time": None,
        }
    write_json(records, output_path)
    media_data = read_json(paths.media)
    task_subtitle = media_data["main"].get("task_subtitle")
    if isinstance(task_subtitle, str) and task_subtitle.strip():
        media_data["main"]["news_subtitle"] = ChatGPT(
            usage_report_path=paths.llm_cost_report
        ).rewrite_australian_news_subtitle(task_subtitle)
    else:
        media_data["main"]["news_subtitle"] = translation_result["subtitle"]
    write_json(media_data, paths.media)
    return output_path

def generate_chinese_tts(paths: ProjectPaths) -> Path:
    """Generate Chinese speech with one stable news voice per speaker."""
    output_path = paths.root / "speaker_english_subtitles.json"
    records = read_json(output_path)
    speakers = sorted({record["speaker"] for record in records})
    media_data = read_json(paths.media)
    genders = media_data["main"].get("speaker_gender_mapping", {})
    voice_lists = {
        "male": MALE_NEWS_TTS_VOICES,
        "female": FEMALE_NEWS_TTS_VOICES,
    }
    speakers_by_gender = {"male": [], "female": []}
    for speaker in speakers:
        gender = genders.get(speaker, {}).get("gender")
        if gender not in voice_lists:
            raise ValueError(f"说话人 {speaker} 缺少有效的性别判断")
        speakers_by_gender[gender].append(speaker)

    voice_mapping = {}
    for gender, gender_speakers in speakers_by_gender.items():
        voices = voice_lists[gender]
        for index, speaker in enumerate(gender_speakers):
            voice_mapping[speaker] = voices[index % len(voices)]

    tts_dir = paths.root / "chinese_tts"
    tts = Volcengine()
    current_time = 0
    for index, record in enumerate(records):
        chinese = record.get("chinese")
        if not chinese or not chinese.get("text"):
            raise ValueError(f"第 {index + 1} 条字幕缺少中文翻译")

        speaker = record["speaker"]
        voice = voice_mapping[speaker]
        audio_path = tts_dir / f"{index:03d}.mp3"
        duration = tts.generate_tts(chinese["text"], audio_path, speaker=voice)
        chinese["audio_path"] = str(audio_path)
        chinese["voice"] = voice
        chinese["start_time"] = current_time
        chinese["end_time"] = current_time + duration
        current_time += duration

    write_json(records, output_path)
    media_data["main"]["speaker_voice_mapping"] = voice_mapping
    media_data["main"]["chinese_tts_dir"] = str(tts_dir)
    write_json(media_data, paths.media)
    return output_path

def create_chinese_dubbed_video(paths: ProjectPaths) -> Path:
    records_path = paths.root / "speaker_english_subtitles.json"
    records = read_json(records_path)
    media_data = read_json(paths.media)
    clips_dir = paths.root / "chinese_video_clips"
    clip_paths = []
    for index, record in enumerate(records):
        english, chinese = record["english"], record["chinese"]
        output_path = clips_dir / f"{index:03d}.mp4"
        speed = dub_video_segment(
            media_data["main"]["source_video_path"], chinese["audio_path"], output_path,
            english["start_time"], english["end_time"], chinese["end_time"] - chinese["start_time"],
        )
        chinese["video_path"] = str(output_path)
        chinese["video_speed"] = speed
        clip_paths.append(output_path)
    filelist_path = paths.root / "chinese_video_concat_list.txt"
    with open(filelist_path, "w", encoding="utf-8") as file:
        for clip_path in clip_paths:
            file.write(f"file '{clip_path.absolute()}'\n")
    final_video = paths.root / "chinese_dubbed_video.mp4"
    concat_media(filelist_path, final_video)
    write_json(records, records_path)
    media_data["main"]["chinese_dubbed_video_path"] = str(final_video)
    write_json(media_data, paths.media)
    return final_video


def add_chinese_dubbed_subtitles(paths: ProjectPaths) -> Path:
    """Create Chinese-only subtitles from the TTS timeline and burn them into the dubbed video."""
    records = read_json(paths.root / "speaker_english_subtitles.json")
    srt_path = paths.root / "chinese_dubbed_subtitles.srt"
    with open(srt_path, "w", encoding="utf-8") as file:
        for index, record in enumerate(records, start=1):
            chinese = record["chinese"]
            file.write(
                f"{index}\n{ms_to_srt_time(chinese['start_time'])} --> "
                f"{ms_to_srt_time(chinese['end_time'])}\n"
                f"{chinese['text']}\n\n"
            )

    media_data = read_json(paths.media)
    cropped_video = paths.root / "chinese_dubbed_cropped_4_3.mp4"
    crop_to_four_three(
        media_data["main"]["chinese_dubbed_video_path"],
        cropped_video,
    )
    output_video = paths.root / "chinese_dubbed_subtitled.mp4"
    add_subtitles(
        cropped_video,
        srt_path,
        output_video,
        y=50,
        font_size=20,
    )
    media_data["main"]["chinese_dubbed_cropped_4_3_video_path"] = str(cropped_video)
    media_data["main"]["chinese_dubbed_subtitles_path"] = str(srt_path)
    media_data["main"]["chinese_dubbed_subtitled_video_path"] = str(output_video)
    write_json(media_data, paths.media)
    return output_video


def create_news_short_video(paths: ProjectPaths) -> Path:
    """Convert the dubbed, subtitled video into the established vertical news format."""
    media_data = read_json(paths.media)
    title = media_data["main"].get("task_title") or "今日要闻"
    subtitle = media_data["main"].get("news_subtitle") or ""
    vertical_video = paths.root / "chinese_dubbed_vertical.mp4"
    final_video = paths.root / "chinese_dubbed_news.mp4"
    four_three_to_vertical(
        media_data["main"]["chinese_dubbed_subtitled_video_path"],
        vertical_video,
        width=1080,
        height=1920,
        fps=30,
    )
    add_text_overlay(
        vertical_video,
        final_video,
        title=title,
        subtitle=subtitle,
        font_size_title=80,
        font_size_sub=60,
        title_y=400,
        sub_y=450,
        title_color="#FFCC00",
        sub_color="#FFCC00",
        popup_comments=[],
        popup_font_size=1,
        popup_color="#FFFFFF",
        popup_y=1,
    )
    media_data["main"]["news_title"] = title
    media_data["main"]["chinese_dubbed_vertical_video_path"] = str(vertical_video)
    media_data["main"]["chinese_dubbed_news_video_path"] = str(final_video)
    write_json(media_data, paths.media)
    return final_video


def upload_news_video(paths: ProjectPaths) -> str:
    """Upload the completed vertical news video to the task's Drive folder."""
    from services.google_drive import upload_to_drive

    media_data = read_json(paths.media)
    main_media = media_data["main"]
    title = main_media.get("task_title") or "今日要闻"
    video_path = main_media["chinese_dubbed_news_video_path"]
    news_subtitle = main_media.get("news_subtitle") or title
    upload_filename = f"{safe_filename(news_subtitle)}.mp4"
    file_id = upload_to_drive(
        video_path,
        folder_name=title,
        filename=upload_filename,
    )
    main_media["google_drive"] = {
        "folder_name": title,
        "file_id": file_id,
        "filename": upload_filename,
        "video_path": str(video_path),
    }
    write_json(media_data, paths.media)
    return file_id

def main(task_file: str | Path = "translate_tasks.json") -> None:
    """Run every source listed in the supplied translation task file."""
    task_file = Path(task_file)
    jobs = read_json(task_file)

    for index, job in enumerate(jobs, start=1):
        urls = job.get("urls")
        if not urls:
            raise ValueError(f"任务 {index} 缺少 urls: {job}")
        url_list = [urls] if isinstance(urls, str) else urls
        if not isinstance(url_list, list) or not all(
            isinstance(url, str) and url.startswith(("http://", "https://"))
            for url in url_list
        ):
            raise ValueError(f"任务 {index} 的 urls 必须是一个或多个 HTTP(S) URL")

        print("========== 1. 下载视频 ==========")
        paths = download_source_video(urls, job.get("title"), job.get("subtitle"))
        print(f"任务 {index} 下载完成，工作区: {paths.root}")

        print("========== 2. 提取音频 ==========")
        extract_source_audio(paths)

        print("========== 3. 英文字幕识别 ==========")
        transcribe_english_subtitles(paths)

        print("========== 3.05 AI 整合英文短句 ==========")
        merge_english_subtitles_before_diarization(paths)

        print("========== 3.1 语音分类 ==========")
        classify_speakers(paths)

        print("========== 3.15 声音性别判断 ==========")
        classify_speaker_genders(paths)

        print("========== 3.2 导出说话人英文字幕 ==========")
        export_speaker_english_subtitles(paths)

        print("========== 4. AI 翻译字幕 ==========")
        translate_speaker_english_subtitles(paths)

        print("========== 5. 中文 TTS ==========")
        generate_chinese_tts(paths)

        print("========== 6. 中文配音视频 ==========")
        create_chinese_dubbed_video(paths)

        print("========== 7. 烧录中文字幕 ==========")
        add_chinese_dubbed_subtitles(paths)

        print("========== 8. 生成竖版新闻视频 ==========")
        create_news_short_video(paths)

        if job.get("upload", False):
            print("========== 9. 上传 Google Drive ==========")
            upload_news_video(paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate YouTube news videos into Chinese.")
    parser.add_argument(
        "--tasks",
        default="translate_tasks.json",
        help="JSON task file path (default: translate_tasks.json)",
    )
    arguments = parser.parse_args()
    main(arguments.tasks)
