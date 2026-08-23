import tempfile
import unittest
from pathlib import Path

from core.utils import write_json
from services.post_cut_service import PostCutService


class FakeEmbeddingService:
    def encode(self, text):
        return [len(text)]


class FakePostgresClient:
    def __init__(self):
        self.source_stories = []
        self.scenes = []
        self.closed = False

    def upsert_source_story(self, **kwargs):
        self.source_stories.append(kwargs)
        return 91

    def insert_scene(self, **kwargs):
        self.scenes.append(kwargs)
        return 300 + len(self.scenes)

    def get_or_create_character(self, **kwargs):
        return 1

    def insert_scene_character(self, **kwargs):
        pass

    def close(self):
        self.closed = True


class SourceStoryStorageTests(unittest.TestCase):
    def test_save_scene_creates_one_source_story_and_links_each_scene(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            story_path = Path(temp_dir) / "story.json"
            write_json(
                {
                    "总故事": "这一集的总故事",
                    "场景": [
                        {"编号": 1, "标题": "场景一", "事件": "事件", "剧情": "剧情"},
                        {"编号": 2, "标题": "场景二", "事件": "事件", "剧情": "剧情二"},
                    ],
                },
                story_path,
            )
            service = PostCutService.__new__(PostCutService)
            service.postgres_client = FakePostgresClient()
            service.text_embedding_service = FakeEmbeddingService()

            mapping = service.save_scene_to_db(
                story_path, "s3://bucket/video.mp4", "测试剧"
            )

            self.assertEqual(mapping, {1: 301, 2: 302})
            self.assertEqual(len(service.postgres_client.source_stories), 1)
            self.assertEqual(
                service.postgres_client.source_stories[0]["summary"], "这一集的总故事"
            )
            self.assertEqual(
                [scene["story_id"] for scene in service.postgres_client.scenes], [91, 91]
            )


if __name__ == "__main__":
    unittest.main()
