
import json

from services.postgresql import PostgresClient
from services.text_embedding_service import TextEmbeddingService


class PostCutService:
    def __init__(self):
        self.postgres_client = PostgresClient()
        self.text_embedding_service = TextEmbeddingService()

    def save_transcription_to_db(self, subtitles_path, speaker_mapping_path, video_url, episode):
        with open(subtitles_path, "r", encoding="utf-8") as f:
            subtitles = json.load(f)
        with open(speaker_mapping_path, "r", encoding="utf-8") as f:
            speaker_mapping = json.load(f)

        results = []

        for utterance in subtitles.get("utterances", []):

            raw_speaker = (
                utterance
                .get("attribute", {})
                .get("speaker")
            )

            speaker = speaker_mapping.get(
                raw_speaker,
                raw_speaker
            )


            results.append(
                {
                "start_time": utterance["start_time"],
                "end_time": utterance["end_time"],
                "text": utterance["text"],
                "speaker": speaker,
                "url": video_url,
                "episode": episode,
                "text_embedding": self.text_embedding_service.encode(utterance["text"])
                }
            )

        for item in results:
            self.postgres_client.insert_video_transcript(
                start_time=int(item["start_time"]),
                end_time=int(item["end_time"]),
                text=item["text"],
                speaker=item["speaker"],
                url=item["url"],
                episode=item["episode"],
                embedding=item["text_embedding"]
            )
        self.postgres_client.close()

    def save_story_to_db(self, story_path, video_url, episode):
        with open(story_path, "r", encoding="utf-8") as f:
            story = json.load(f)

        results = []

        for item in story.get("人物故事", []):
            person = item.get("人物")
            content = item.get("故事")

            if not person or not content:
                continue

            results.append(
                {
                "story": content,
                "person": person,
                "url": video_url,
                "episode": episode,
                "text_embedding": self.text_embedding_service.encode(content),
                }
         )

        for item in results:
            self.postgres_client.insert_story(
            story=item["story"],
            url=item["url"],
            episode=item["episode"],
            person=item["person"],
            embedding=item["text_embedding"],
            )

        self.postgres_client.close()
    
    def save_scene_to_db(self, story_path, video_url, drama_title):

        with open(story_path, "r", encoding="utf-8") as f:
            story = json.load(f)
        
        scene_mapping = {}

        for scene_item in story.get("场景", []):
            old_scene_no = scene_item.get("编号")

            # 1. 写入 scene
            scene_id = self.postgres_client.insert_scene(
                drama_title=drama_title,
                video_url=video_url,
                title=scene_item.get("标题"),
                event=scene_item.get("事件"),
                summary=scene_item.get("剧情"),
                embedding=self.text_embedding_service.encode(
                    scene_item.get("剧情")
                )
            )

            scene_mapping[old_scene_no] = scene_id


            # 2. 写入人物
            for person in scene_item.get("人物", []):

                name = person.get("姓名")
                summary = person.get("剧情")

                if not name or not summary:
                    continue


                # 先获取 character
                character_id = self.postgres_client.get_or_create_character(
                    drama_title=drama_title,
                    name=name
                )


                # 3. 写入 scene_character
                self.postgres_client.insert_scene_character(
                    drama_title=drama_title,
                    scene_id=scene_id,
                    character_id=character_id,
                    character_summary=summary
                )


        self.postgres_client.close()
        return scene_mapping
    
    def save_subtitle_to_db(
        self,
        subtitle_json_path,
        video_url,
        drama_title
    ):

        with open(
            subtitle_json_path,
            "r",
            encoding="utf-8"
        ) as f:
            subtitles = json.load(f)


        for item in subtitles.get("utterances", []):

            content = item.get("text")

            if not content:
                continue


            self.postgres_client.insert_subtitle(
                drama_title=drama_title,
                video_url=video_url,
                start_time=int(item["start_time"]),
                end_time=int(item["end_time"]),
                content=content,
                speaker=item.get("speaker"),
                scene_id=item.get("scene_id"),
                embedding=self.text_embedding_service.encode(
                    content
                )
        )


        self.postgres_client.close()