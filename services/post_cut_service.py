from core.utils import read_json
from services.postgresql import PostgresClient
from services.text_embedding_service import TextEmbeddingService


class PostCutService:
    def __init__(self):
        self.postgres_client = PostgresClient()
        self.text_embedding_service = TextEmbeddingService()

    def save_scene_to_db(self, story_path, video_url, drama_title):
        with open(story_path, "r", encoding="utf-8") as file:
            story = read_json(file)

        scene_mapping = {}
        for scene in story.get("场景", []):
            scene_id = self.postgres_client.insert_scene(
                drama_title=drama_title,
                video_url=video_url,
                title=scene.get("标题"),
                event=scene.get("事件"),
                summary=scene.get("剧情"),
                embedding=self.text_embedding_service.encode(scene.get("剧情")),
            )
            scene_mapping[scene.get("编号")] = scene_id

            for person in scene.get("人物", []):
                name = person.get("姓名")
                summary = person.get("剧情")
                if not name or not summary:
                    continue

                character_id = self.postgres_client.get_or_create_character(
                    drama_title=drama_title,
                    name=name,
                )
                self.postgres_client.insert_scene_character(
                    drama_title=drama_title,
                    scene_id=scene_id,
                    character_id=character_id,
                    character_summary=summary,
                )

        self.postgres_client.close()
        return scene_mapping

    def save_subtitle_to_db(self, subtitle_json_path, video_url, drama_title):
        with open(subtitle_json_path, "r", encoding="utf-8") as file:
            subtitles = read_json(file)

        for subtitle in subtitles.get("utterances", []):
            content = subtitle.get("text")
            if not content:
                continue

            self.postgres_client.insert_subtitle(
                drama_title=drama_title,
                video_url=video_url,
                start_time=int(subtitle["start_time"]),
                end_time=int(subtitle["end_time"]),
                content=content,
                speaker=subtitle.get("speaker"),
                scene_id=subtitle.get("scene_id"),
                embedding=self.text_embedding_service.encode(content),
            )

        self.postgres_client.close()
