import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.path import ProjectPaths
from core.utils import write_json
from services.post_cut_service import PostCutService


class EpisodeStorageTests(unittest.TestCase):
    def service(self, exists):
        service = PostCutService.__new__(PostCutService)
        service.postgres_client = Mock()
        service.postgres_client.has_episode.return_value = exists
        service._text_embedding_service = Mock()
        service._text_embedding_service.encode.return_value = [0.1]
        return service

    def test_existing_episode_skips_every_write_and_embedding(self):
        service = self.service(True)
        result = service.save_episode_to_db(None, 'different-new-video-url', '测试剧', 1)
        self.assertEqual(result['status'], 'skipped')
        service.postgres_client.has_episode.assert_called_once_with('测试剧', 1)
        service.postgres_client.upsert_source_story.assert_not_called()
        service.postgres_client.insert_scene.assert_not_called()
        service.postgres_client.insert_subtitle.assert_not_called()
        service._text_embedding_service.encode.assert_not_called()
        service.postgres_client.close.assert_called_once()

    def test_new_episode_keeps_write_sequence_and_passes_episode_to_all_records(self):
        service = self.service(False)
        service.postgres_client.upsert_source_story.return_value = 123
        service.postgres_client.insert_scene.return_value = 777
        with tempfile.TemporaryDirectory() as directory:
            paths = ProjectPaths(Path(directory))
            write_json({'总故事': '一个完整故事', '场景': [
                {'编号': 1, '开始SRT': 0, '结束SRT': 0, '标题': '对峙', '事件': '交锋',
                 '剧情': '人物当面对峙', '人物': [{'姓名': '甲', '剧情': '参与交锋'}]}]}, paths.story)
            write_json({'utterances': [{'text': '原剧对白', 'start_time': 0, 'end_time': 1000,
                                       'attribute': {'speaker': '0'}}]}, paths.subtitles['json'])
            write_json({'0': '甲'}, paths.speaker_mapping)
            result = service.save_episode_to_db(paths, 's3://master', '测试剧', 8)
        self.assertEqual(result['status'], 'completed')
        for method in ('upsert_source_story', 'insert_scene', 'insert_subtitle'):
            self.assertEqual(getattr(service.postgres_client, method).call_args.kwargs['episode'], 8)
        self.assertEqual(service.postgres_client.insert_subtitle.call_args.kwargs['scene_id'], 777)
        self.assertEqual(service.postgres_client.insert_subtitle.call_args.kwargs['speaker'], '甲')
        service.postgres_client.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
