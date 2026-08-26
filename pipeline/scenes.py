from core.utils import read_json, write_json

NARRATION_ONLY = "narration_only"
WITH_DIALOGUE = "with_dialogue"


def normalize_segment_type(segment_type):
    """Validate the explicit original-dialogue behavior selected by the director."""
    if segment_type in {NARRATION_ONLY, WITH_DIALOGUE}:
        return segment_type
    raise ValueError(f"未知 segment type: {segment_type}")


def save_scene_candidates(rows, output_path):
    scenes = [
        {
            "scene_id": row[0],
            "drama_title": row[1],
            "video_url": row[2],
            "title": row[3],
            "event": row[4],
            "summary": row[5],
        }
        for row in rows
    ]
    write_json(scenes, output_path)


def attach_subtitles_to_selected_scenes(
    selected_scene_path,
    scene_path,
    output_path,
    postgres_client,
):
    scene_map = {scene["scene_id"]: scene for scene in read_json(scene_path)}
    results = []

    for item in read_json(selected_scene_path):
        scene = scene_map.get(item["scene_id"])
        if not scene:
            continue

        scene["task"] = item["task"]
        scene["max_segments"] = item.get("max_segments", 2)
        if item.get("audience_question"):
            scene["audience_question"] = item["audience_question"]
        subtitles = [
            {
                "start_time": row[0],
                "end_time": row[1],
                "content": row[2],
                "speaker": row[3],
            }
            for row in postgres_client.get_subtitles_by_scene_id(item["scene_id"])
        ]
        scene["subtitles"] = subtitles
        scene["subtitles_plain_text"] = "\n".join(
            (
                f"[{index} | "
                f"{max(0, subtitle['end_time'] - subtitle['start_time']) / 1000:.1f}秒] "
                f"{subtitle['speaker']}：{subtitle['content']}"
            )
            for index, subtitle in enumerate(subtitles, start=1)
        )
        results.append(scene)

    write_json(results, output_path)
    return results


def attach_subtitles_to_segments(scene_path, segment_path, output_path):
    segment_mapping = {
        item["scene_id"]: item["segments"] for item in read_json(segment_path)
    }
    results = []

    for scene in read_json(scene_path):
        segments = segment_mapping.get(scene["scene_id"], [])
        if not segments:
            continue

        subtitle_map = {index + 1: subtitle for index, subtitle in enumerate(scene["subtitles"])}
        for segment in segments:
            segment_type = normalize_segment_type(segment.get("type", WITH_DIALOGUE))
            segment["type"] = segment_type
            if segment_type == NARRATION_ONLY:
                visual_ids = segment.get("visual_subtitle_ids", [])
                visual_subtitles = [
                    subtitle_map[subtitle_id]
                    for subtitle_id in visual_ids
                    if subtitle_id in subtitle_map
                ]
                segment["visual_subtitles"] = visual_subtitles
                segment["visual_anchor_duration_seconds"] = round(
                    sum(
                        max(0, subtitle["end_time"] - subtitle["start_time"])
                        for subtitle in visual_subtitles
                    )
                    / 1000,
                    3,
                )
                segment.pop("visual_subtitle_ids", None)
            else:
                segment_subtitles = [
                    subtitle_map[subtitle_id]
                    for subtitle_id in segment.get("subtitle_ids", [])
                    if subtitle_id in subtitle_map
                ]
                segment["subtitles"] = segment_subtitles
                segment["dialogue_duration_seconds"] = round(
                    sum(
                        max(0, subtitle["end_time"] - subtitle["start_time"])
                        for subtitle in segment_subtitles
                    )
                    / 1000,
                    3,
                )
                segment.pop("subtitle_ids", None)
        scene["segments"] = segments
        results.append(scene)

    write_json(results, output_path)
    return results


def build_hook_segment(scene_path, hook_path, output_path):
    hook = read_json(hook_path)
    for scene in read_json(scene_path):
        if scene["scene_id"] != hook["scene_id"]:
            continue
        for segment in scene["segments"]:
            if segment["segment_id"] != hook["segment_id"]:
                continue
            result = segment.copy()
            result["scene_id"] = hook["scene_id"]
            result["hook_narration"] = hook["hook_narration"]
            if not result.get("subtitles") and result.get("visual_subtitles"):
                result["subtitles"] = result["visual_subtitles"]
            write_json(result, output_path)
            return result

    raise Exception("没有找到对应segment")
