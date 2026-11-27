from core.utils import read_json
from services.postgresql import PostgresClient
from services.text_embedding_service import TextEmbeddingService


class PostCutService:
    def __init__(self):
        self.postgres_client = PostgresClient()
        self._text_embedding_service = None

    @property
    def text_embedding_service(self):
        if self._text_embedding_service is None:
            self._text_embedding_service = TextEmbeddingService()
        return self._text_embedding_service

    def save_episode_to_db(self, paths, video_url, drama_title, episode):
        """Skip an existing drama/episode; otherwise keep the original write sequence."""
        from pipeline.subtitles import apply_character_scene_mapping
        if type(episode) is not int or episode < 1:
            raise ValueError('episode 必须是正整数')
        try:
            if self.postgres_client.has_episode(drama_title, episode):
                print(f'跳过数据库写入：{drama_title} 第{episode}集已存在', flush=True)
                return {'status': 'skipped', 'episode': episode, 'reason': 'already_exists'}
            mapping = self.save_scene_to_db(paths.story, video_url, drama_title, episode, close=False)
            apply_character_scene_mapping(paths.subtitles['json'], paths.speaker_mapping,
                                          paths.story, mapping, paths.subtitles_to_db)
            self.save_subtitle_to_db(paths.subtitles_to_db, video_url, drama_title, episode, close=False)
            return {'status': 'completed', 'episode': episode, 'scene_mapping': mapping}
        finally:
            self.postgres_client.close()

    def save_scene_to_db(self, story_path, video_url, drama_title, episode=None, *, close=True):
        with open(story_path, "r", encoding="utf-8") as file:
            story = read_json(file)

        overall_story = story.get("总故事")
        if not isinstance(overall_story, str) or not overall_story.strip():
            raise ValueError("story.json 缺少非空的 总故事，无法写入 source_story")
        story_id = self.postgres_client.upsert_source_story(
            drama_title=drama_title,
            video_url=video_url,
            summary=overall_story,
            embedding=self.text_embedding_service.encode(overall_story),
            episode=episode,
        )

        scene_mapping = {}
        for scene in story.get("场景", []):
            scene_id = self.postgres_client.insert_scene(
                drama_title=drama_title,
                video_url=video_url,
                title=scene.get("标题"),
                event=scene.get("事件"),
                summary=scene.get("剧情"),
                embedding=self.text_embedding_service.encode(scene.get("剧情")),
                story_id=story_id,
                episode=episode,
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

        if close:
            self.postgres_client.close()
        return scene_mapping

    def save_subtitle_to_db(self, subtitle_json_path, video_url, drama_title, episode=None, *, close=True):
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
                episode=episode,
            )

        if close:
            self.postgres_client.close()
