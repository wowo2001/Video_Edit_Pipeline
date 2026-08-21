from core.utils import read_json, write_json


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
            f"[{index}] {subtitle['speaker']}：{subtitle['content']}"
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
            segment["subtitles"] = [
                subtitle_map[subtitle_id]
                for subtitle_id in segment.get("subtitle_ids", [])
                if subtitle_id in subtitle_map
            ]
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
            result["local_video_path"] = scene["local_video_path"]
            result["hook_narration"] = hook["hook_narration"]
            write_json(result, output_path)
            return result

    raise Exception("没有找到对应segment")
