"""Chinese-to-English video translation workflow.

This is intentionally separate from ``translate.py``.  Each task creates a
fresh workspace before downloading its Chinese source video.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from core.demucs import extract_vocals_demucs
from core.ffmpeg import add_subtitles, add_text_overlay, change_resolution, concat_media, dub_video_segment
from core.path import ProjectPaths
from core.utils import ms_to_srt_time, read_json, safe_filename, write_json
from pipeline.audio import export_audio
from pipeline.download import download_video
from services.chatgpt import ChatGPT
from services.volcengine import Volcengine
from translate import _validate_merge_groups, classify_speaker_genders, classify_speakers


ENGLISH_MALE_NEWS_TTS_VOICES = [
    "en_male_russell_uranus_bigtts",
    "en_male_knightley_uranus_bigtts",
    "en_male_father-christmas_uranus_bigtts",
    "ICL_uranus_en_male_michael_tob",
]
ENGLISH_FEMALE_NEWS_TTS_VOICES = [
    "en_female_authoritative-british_uranus_bigtts",
    "en_female_zendaya_p1_uranus_bigtts",
    "en_female_wenrouzhishijieshuonv_uranus_bigtts",
    "en_female_jane_uranus_bigtts",
]


def create_workspace(title: str | None = None) -> ProjectPaths:
    """Create an isolated workspace for one Chinese-to-English task."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = safe_filename(title) if title else "translation"
    workspace = Path("work") / "translate_zh_to_en" / f"{timestamp}_{name}_{uuid4().hex[:8]}"
    return ProjectPaths(workspace)


def download_source_video(urls: str | list[str], title: str | None = None) -> ProjectPaths:
    """Create a workspace, then download the Chinese source video."""
    paths = create_workspace(title)
    download_video(
        urls=urls,
        output_path=paths.video,
        origin_path=paths.origin,
        media_path=paths.media,
    )
    media_data = read_json(paths.media)
    media_data["main"]["task_title"] = title or ""
    write_json(media_data, paths.media)
    return paths


def extract_source_audio(paths: ProjectPaths) -> None:
    """Extract source audio and concatenate Demucs-separated vocal tracks."""
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


def transcribe_chinese_subtitles(paths: ProjectPaths) -> None:
    """Recognize Simplified Chinese subtitles from separated vocals."""
    media_data = read_json(paths.media)
    main_media = media_data["main"]
    Volcengine().transcribe_audio(
        main_media["vocals_audio_path"],
        paths.subtitles,
        language="zh-CN",
    )
    main_media["subtitles"] = {
        "srt_path": str(paths.subtitles["srt"]),
        "json_path": str(paths.subtitles["json"]),
    }
    write_json(media_data, paths.media)


def merge_chinese_subtitles_before_diarization(paths: ProjectPaths) -> Path:
    """Merge ASR fragments before speaker classification, without time limits."""
    subtitles = read_json(paths.subtitles["json"])
    utterances = subtitles["utterances"]
    raw_path = paths.root / "subtitles_raw.json"
    write_json(subtitles, raw_path)

    source_items = [[index, utterance["text"].strip()] for index, utterance in enumerate(utterances)]
    try:
        groups = ChatGPT(usage_report_path=paths.llm_cost_report).merge_chinese_subtitles_before_diarization(source_items)
        groups = _validate_merge_groups(groups, [{"id": 0, "items": source_items}], utterances)
    except (KeyError, ValueError):
        print("⚠️ AI 短句分组不完整，已保留原始识别字幕")
        groups = [[index] for index in range(len(utterances))]

    merged_utterances = []
    for source_indices in groups:
        source_utterances = [utterances[index] for index in source_indices]
        first, last = source_utterances[0], source_utterances[-1]
        merged = dict(first)
        merged.pop("attribute", None)
        merged["source_indices"] = source_indices
        merged["text"] = "".join(item["text"].strip() for item in source_utterances)
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
    media_data["main"]["merged_chinese_subtitle_count"] = len(merged_utterances)
    write_json(media_data, paths.media)
    return paths.subtitles["json"]


def export_speaker_chinese_subtitles(paths: ProjectPaths) -> Path:
    """Export the post-clustering Chinese subtitles without changing speaker labels."""
    subtitles = read_json(paths.subtitles["json"])
    output_path = paths.root / "speaker_chinese_subtitles.json"
    records = [
        {
            "speaker": utterance.get("attribute", {}).get("speaker", "UNKNOWN"),
            "chinese": {
                "text": utterance["text"],
                "start_time": utterance["start_time"],
                "end_time": utterance["end_time"],
            },
        }
        for utterance in subtitles["utterances"]
    ]
    write_json(records, output_path)
    media_data = read_json(paths.media)
    media_data["main"]["speaker_chinese_subtitles_path"] = str(output_path)
    write_json(media_data, paths.media)
    return output_path


def translate_speaker_chinese_subtitles(paths: ProjectPaths) -> Path:
    """Add English translations and an English short-video subtitle."""
    output_path = paths.root / "speaker_chinese_subtitles.json"
    records = read_json(output_path)
    translation_input = [{"index": index, "text": record["chinese"]["text"]} for index, record in enumerate(records)]
    result = ChatGPT(usage_report_path=paths.llm_cost_report).translate_chinese_subtitles(translation_input)
    translations = {item.get("index"): item.get("text") for item in result["translations"]}
    if set(translations) != set(range(len(records))) or not all(isinstance(text, str) for text in translations.values()):
        raise ValueError("英文翻译结果缺少或包含无效序号")
    for index, record in enumerate(records):
        record["english"] = {"text": translations[index], "start_time": None, "end_time": None}
    write_json(records, output_path)
    media_data = read_json(paths.media)
    media_data["main"]["news_subtitle"] = result["subtitle"]
    write_json(media_data, paths.media)
    return output_path


def generate_english_tts(paths: ProjectPaths) -> Path:
    """Generate English TTS, retaining one voice per classified speaker."""
    output_path = paths.root / "speaker_chinese_subtitles.json"
    records = read_json(output_path)
    media_data = read_json(paths.media)
    genders = media_data["main"].get("speaker_gender_mapping", {})
    voices_by_gender = {"male": ENGLISH_MALE_NEWS_TTS_VOICES, "female": ENGLISH_FEMALE_NEWS_TTS_VOICES}
    speakers = sorted({record["speaker"] for record in records})
    grouped_speakers = {"male": [], "female": []}
    for speaker in speakers:
        gender = genders.get(speaker, {}).get("gender")
        if gender not in voices_by_gender:
            raise ValueError(f"说话人 {speaker} 缺少有效的性别判断")
        grouped_speakers[gender].append(speaker)
    voice_mapping = {
        speaker: voices_by_gender[gender][index % len(voices_by_gender[gender])]
        for gender, speaker_list in grouped_speakers.items()
        for index, speaker in enumerate(speaker_list)
    }

    tts_dir = paths.root / "english_tts"
    tts = Volcengine()
    current_time = 0
    for index, record in enumerate(records):
        english = record["english"]
        audio_path = tts_dir / f"{index:03d}.mp3"
        duration = tts.generate_tts(english["text"], audio_path, speaker=voice_mapping[record["speaker"]])
        english.update({
            "audio_path": str(audio_path),
            "voice": voice_mapping[record["speaker"]],
            "start_time": current_time,
            "end_time": current_time + duration,
        })
        current_time += duration
    write_json(records, output_path)
    media_data["main"]["speaker_voice_mapping"] = voice_mapping
    media_data["main"]["english_tts_dir"] = str(tts_dir)
    write_json(media_data, paths.media)
    return output_path


def create_english_dubbed_video(paths: ProjectPaths) -> Path:
    """Time-scale source video segments to the corresponding English TTS clips."""
    records_path = paths.root / "speaker_chinese_subtitles.json"
    records = read_json(records_path)
    media_data = read_json(paths.media)
    clips_dir = paths.root / "english_video_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_paths = []
    for index, record in enumerate(records):
        chinese, english = record["chinese"], record["english"]
        output_path = clips_dir / f"{index:03d}.mp4"
        speed = dub_video_segment(
            media_data["main"]["source_video_path"], english["audio_path"], output_path,
            chinese["start_time"], chinese["end_time"], english["end_time"] - english["start_time"],
        )
        english["video_path"] = str(output_path)
        english["video_speed"] = speed
        clip_paths.append(output_path)
    filelist_path = paths.root / "english_video_concat_list.txt"
    with open(filelist_path, "w", encoding="utf-8") as file:
        for clip_path in clip_paths:
            file.write(f"file '{clip_path.absolute()}'\n")
    final_video = paths.root / "english_dubbed_video.mp4"
    concat_media(filelist_path, final_video)
    write_json(records, records_path)
    media_data["main"]["english_dubbed_video_path"] = str(final_video)
    write_json(media_data, paths.media)
    return final_video


def add_english_dubbed_subtitles(paths: ProjectPaths) -> Path:
    """Burn English-only subtitles aligned to the English TTS timeline."""
    records = read_json(paths.root / "speaker_chinese_subtitles.json")
    srt_path = paths.root / "english_dubbed_subtitles.srt"
    with open(srt_path, "w", encoding="utf-8") as file:
        for index, record in enumerate(records, start=1):
            english = record["english"]
            file.write(f"{index}\n{ms_to_srt_time(english['start_time'])} --> {ms_to_srt_time(english['end_time'])}\n{english['text']}\n\n")
    media_data = read_json(paths.media)
    output_video = paths.root / "english_dubbed_subtitled.mp4"
    add_subtitles(
        media_data["main"]["english_dubbed_video_path"],
        srt_path,
        output_video,
        y=50,
        font_size=20,
    )
    media_data["main"]["english_dubbed_subtitles_path"] = str(srt_path)
    media_data["main"]["english_dubbed_subtitled_video_path"] = str(output_video)
    write_json(media_data, paths.media)
    return output_video


def create_english_news_short_video(paths: ProjectPaths) -> Path:
    """Create the same 1080x1920 title layout without burned-in subtitles."""
    media_data = read_json(paths.media)
    main_media = media_data["main"]
    title = main_media.get("task_title") or "Today’s News"
    subtitle = main_media.get("news_subtitle") or ""
    vertical_video = paths.root / "english_dubbed_vertical.mp4"
    final_video = paths.root / "english_dubbed_news.mp4"
    change_resolution(main_media["english_dubbed_video_path"], vertical_video, width=1080, height=1920, fps=30)
    add_text_overlay(vertical_video, final_video, title=title, subtitle=subtitle,
                     font_size_title=80, font_size_sub=60, title_y=400, sub_y=450,
                     title_color="#FFCC00", sub_color="#FFCC00", popup_comments=[],
                     popup_font_size=1, popup_color="#FFFFFF", popup_y=1)
    main_media["news_title"] = title
    main_media["english_dubbed_vertical_video_path"] = str(vertical_video)
    main_media["english_dubbed_news_video_path"] = str(final_video)
    write_json(media_data, paths.media)
    return final_video


def upload_english_news_video(paths: ProjectPaths) -> str:
    """Upload the English version to the task's Drive folder."""
    from services.google_drive import upload_to_drive

    media_data = read_json(paths.media)
    main_media = media_data["main"]
    title = main_media.get("task_title") or "Today’s News"
    filename = f"{safe_filename(main_media.get('news_subtitle') or title)}.mp4"
    file_id = upload_to_drive(main_media["english_dubbed_news_video_path"], folder_name=title, filename=filename)
    main_media["google_drive"] = {"folder_name": title, "file_id": file_id, "filename": filename,
                                  "video_path": main_media["english_dubbed_news_video_path"]}
    write_json(media_data, paths.media)
    return file_id


def main(tasks_path: str) -> None:
    """Run the full Chinese-to-English workflow for every listed task."""
    with open(tasks_path, "r", encoding="utf-8") as file:
        tasks = json.load(file)
    if not isinstance(tasks, list):
        raise ValueError("任务文件必须是 JSON 数组")

    for index, task in enumerate(tasks, start=1):
        urls = task.get("urls") or task.get("url")
        if not urls:
            raise ValueError(f"任务 {index} 缺少 url 或 urls")
        print("========== 1. 下载中文视频 ==========")
        paths = download_source_video(urls, task.get("title"))
        print(f"任务 {index} 下载完成，工作区: {paths.root}")
        print("========== 2. 提取人声音频 ==========")
        extract_source_audio(paths)
        print("========== 3. 中文字幕识别 ==========")
        transcribe_chinese_subtitles(paths)
        print("========== 3.05 AI 整合中文短句 ==========")
        merge_chinese_subtitles_before_diarization(paths)
        print("========== 3.1 语音分类 ==========")
        classify_speakers(paths)
        print("========== 3.15 声音性别判断 ==========")
        classify_speaker_genders(paths)
        print("========== 3.2 导出说话人中文字幕 ==========")
        export_speaker_chinese_subtitles(paths)
        print("========== 4. AI 翻译字幕 ==========")
        translate_speaker_chinese_subtitles(paths)
        print("========== 5. 英文 TTS ==========")
        generate_english_tts(paths)
        print("========== 6. 英文配音视频 ==========")
        create_english_dubbed_video(paths)
        print("========== 7. 生成无字幕竖版新闻视频 ==========")
        create_english_news_short_video(paths)
        if task.get("upload", False):
            print("========== 8. 上传 Google Drive ==========")
            upload_english_news_video(paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate Chinese videos into English.")
    parser.add_argument(
        "--tasks",
        default="translate_zh_to_en_tasks.json",
        help="JSON task file path (default: translate_zh_to_en_tasks.json)",
    )
    arguments = parser.parse_args()
    main(arguments.tasks)
