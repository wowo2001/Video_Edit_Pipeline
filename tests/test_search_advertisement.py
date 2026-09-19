import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.utils import read_json, write_json
from services.chatgpt import ChatGPT
from search import SearchPipeline


class AdvertisementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'scenes.json'
        self.scenes = [{'scene_id': 7, 'title': '测试', 'segments': [
            {'segment_id': 1, 'type': 'with_dialogue', 'purpose': '分析',
             'narration': '原解说', 'subtitles': [{'start_time': 10000}],
             'audience_question': '你怎么看？'}]}]
        write_json(self.scenes, self.path)
        self.ai = ChatGPT.__new__(ChatGPT)
        self.ai._complete = Mock()

    def test_advertisement_is_written_without_changing_structure(self):
        self.ai._complete.return_value = '[{"scene_id":7,"segments":[{"segment_id":1,"narration":"剧情，读书App，回到剧情。"}]}]'
        self.ai.refine_narration(self.path, advertisement='读书App')
        segment = read_json(self.path)[0]['segments'][0]
        self.assertEqual(segment['narration'], '剧情，读书App，回到剧情。')
        self.assertEqual(set(segment), set(self.scenes[0]['segments'][0]))
        self.assertEqual(segment['subtitles'], self.scenes[0]['segments'][0]['subtitles'])
        self.assertEqual(segment['audience_question'], '你怎么看？')
        prompt = self.ai._complete.call_args.args[0]
        self.assertIn('读书App', prompt)
        self.assertNotIn('narration_capacity_seconds', prompt)
        self.ai._complete.assert_called_once()

    def test_no_advertisement_uses_original_prompt(self):
        self.ai._complete.return_value = '[{"scene_id":7,"segments":[{"segment_id":1,"narration":"润色解说"}]}]'
        self.ai.refine_narration(self.path)
        self.assertNotIn('<advertisement>', self.ai._complete.call_args.args[0])
        self.assertNotIn('advertisement_inserted', read_json(self.path)[0]['segments'][0])

    @patch('search.build_hook_segment')
    def test_advertisement_refinement_needs_no_media_capacity(self, _build_hook):
        pipeline = SearchPipeline.__new__(SearchPipeline)
        pipeline.paths = SimpleNamespace(scene_selected_subtitle=self.path, hook='hook.json')
        pipeline.ai = Mock()
        pipeline._generate_hook_and_narration('主题', advertisement='点赞关注赛博导演')
        pipeline.ai.refine_narration.assert_called_once_with(
            self.path, advertisement='点赞关注赛博导演',
        )


if __name__ == '__main__':
    unittest.main()
