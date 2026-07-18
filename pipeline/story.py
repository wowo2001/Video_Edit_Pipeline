import json
import os
from urllib.parse import urlparse
def convert_row_data_to_json(rows, story_path):

    data = []
    for row in rows:
        data.append({
            "story": row[0],
            "url": row[1]
        })

    with open(story_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def generate_cadidate_script(scene_path, cadidate_metadata_path, context, client, speaker=None):

    # 读取 scene
    with open(scene_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)

    candidate_metadata = []


    for item in scenes:

        scene_id = item["scene_id"]
        queries = item["scene"].get("search_queries", [])
        url = item["clip"]["url"]


        all_results = []


        # 多关键词搜索
        for query in queries:

            results = client.search_video_transcripts(
                text=query,
                limit=1,
                url=url,
                speaker=speaker
            )


            print(
                f"[Scene {scene_id}] query={query} -> {len(results)} 条结果"
            )


            for row in results:
                all_results.append(
                    {
                        "query": query,
                        "result": row
                    }
                )


        print(
            f"[Scene {scene_id}] 总候选: {len(all_results)}"
        )

        candidates = []


        # 生成候选字幕
        for item_result in all_results:

            row = item_result["result"]
            matched_query = item_result["query"]


            context_rows = client.get_context_transcripts(
                url=row[4],
                text=row[3],
                context=context
            )


            if not context_rows:
                continue



            segments = [
                transcript_to_dict(x)
                for x in context_rows
            ]


            candidate_id = f"{scene_id}_{len(candidates)}"



            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "matched_query": matched_query,
                    "content": [
                        f"[{i}] [{x['speaker'] or '未知'}] {x['text']}"
                        for i, x in enumerate(segments, start=1)
                    ]
                }
            )



            candidate_metadata.append(
                {
                    "scene_id": scene_id,
                    "candidate_id": candidate_id,
                    "url": row[4],
                    "start_time": segments[0]["start_time"],
                    "end_time": segments[-1]["end_time"],
                    "speaker": row[6],
                    "episode": row[5],
                    "segments": segments,
                }
            )



        # 保存候选到 scene
        item["clip"]["candidates"] = candidates



    # 更新 scene 文件
    with open(
        scene_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            scenes,
            f,
            ensure_ascii=False,
            indent=2
        )



    # 保存 metadata
    with open(
        cadidate_metadata_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            candidate_metadata,
            f,
            ensure_ascii=False,
            indent=2
        )


    print(
        f"✅ 候选字幕生成完成: {len(candidate_metadata)} 条"
    )

def generate_final_script(script_path, cadidate_metadata_path, clips_path, s3_client):
    # 读取 script
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)


    # 读取 metadata
    with open(cadidate_metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)


    # 建立索引
    metadata_map = {
        item["candidate_id"]: item
        for item in metadata
    }

    download_dir = clips_path
    os.makedirs(download_dir, exist_ok=True)


    for item in script:

        clip = item.get("clip", {})

        candidate_id = clip.get("candidate_id")
        keep_range = clip.get("keep_range")

        if candidate_id is None or keep_range is None:
            continue

        # 找 metadata
        meta = metadata_map.get(candidate_id)

        if meta is None:
            print(f"找不到 candidate: {candidate_id}")
            continue

        # 根据 keep_range 计算最终片段
        start_idx, end_idx = keep_range

        segments = meta["segments"]

        if (
            start_idx < 1
            or end_idx > len(segments)
            or start_idx > end_idx
        ):
            print(f"keep_range 非法: {candidate_id} {keep_range}")
            continue

        selected_segments = segments[start_idx - 1:end_idx]

        # 下载视频
        s3_url = meta["url"]
        filename = f"{get_filename_from_s3_url(s3_url)}.mp4"

        local_path = os.path.join(
            download_dir,
            filename
        )

        if os.path.exists(local_path):
            print(f"已存在，跳过: {local_path}")
        else:
            s3_client.download_file(
                s3_url,
                local_path
            )

        # 写回 script
        clip["local_path"] = local_path
        clip["start_time"] = selected_segments[0]["start_time"]
        clip["end_time"] = selected_segments[-1]["end_time"]
        clip["speaker"] = meta["speaker"]
        clip["episode"] = meta["episode"]


    # 保存更新后的 script
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(
            script,
            f,
            ensure_ascii=False,
            indent=2
        )    


def transcript_to_dict(row):
    """
    数据库 video_transcripts 查询结果:
    (
        id,
        start_time,
        end_time,
        text,
        url,
        episode,
        speaker
    )
    """
    return {
        "id": row[0],
        "start_time": row[1],
        "end_time": row[2],
        "text": row[3],
        "url": row[4],
        "episode": row[5],
        "speaker": row[6],
    }
def get_filename_from_s3_url(s3_path):
    """
    从 s3 url 提取文件名
    """
    parsed = urlparse(s3_path)
    return os.path.basename(parsed.path)