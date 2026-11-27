import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.path import ProjectPaths
from core.utils import read_json, write_json
from pipeline.pipeline import AutoVideoPipeline


class MainScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = ProjectPaths(Path(self.directory.name))
        self.pipeline = AutoVideoPipeline(self.paths)
        self.script = {
            'hook': {'clip': [{'start': 50000, 'end': 52000}], 'narrative': {'length': 1000}},
            'clips': [
                {'place': 1, 'type': 'narration_only', 'clip': [{'start': 20000, 'end': 21000}],
                 'visual_bounds': {'start': 10000, 'end': 22000}, 'narrative': {'length': 3000}},
                {'place': 2, 'type': 'with_dialogue', 'clip': [{'start': 30000, 'end': 31000}],
                 'narrative': {'length': 2000}},
                {'place': 3, 'clip': [{'start': 40000, 'end': 41000}],
                 'narrative': {'length': 2000}}]}
        write_json(self.script, self.paths.script)
        write_json({'main': {'source_video_path': 'master.mp4',
            'hook': {'narration_audio_path': 'hook.mp3', 'video_path': 'hook.mp4'},
            'clips': {str(i): {'narration_audio_path': f'{i}.mp3', 'video_path': f'{i}.mp4'}
                      for i in range(1, 4)}}}, self.paths.media)

    @patch('pipeline.pipeline.probe_source', return_value={'duration': 60})
    @patch('pipeline.pipeline.cut_video_range', return_value='pure.mp4')
    @patch('pipeline.pipeline.cut_video', return_value='dialogue.mp4')
    def test_cut_dispatch_and_scene_boundary(self, dialogue, pure, probe):
        self.pipeline._cut_script_videos()
        self.assertEqual(pure.call_count, 1)
        # Shift back within the same scene instead of showing the next scene.
        self.assertEqual(pure.call_args.args[2:], (19, 22))
        self.assertEqual(dialogue.call_count, 3)
        self.assertEqual(dialogue.call_args_list[0].kwargs['narration_position'], 'after')
        self.assertTrue(dialogue.call_args_list[1].kwargs['keep_gaps'])

    @patch('pipeline.pipeline.mix_background_narration_audio')
    @patch('pipeline.pipeline.mix_narration_audio')
    def test_mixing_dispatch_and_legacy_script(self, dialogue, pure):
        self.pipeline._mix_script_audio()
        self.assertEqual(pure.call_count, 1)
        self.assertEqual(dialogue.call_count, 3)
        self.assertEqual(dialogue.call_args_list[0].kwargs, {'alignment': 'end'})
        media = read_json(self.paths.media)['main']
        self.assertIn('final_video_path', media['clips']['1'])

    @patch('pipeline.pipeline.mix_background_narration_audio')
    @patch('pipeline.pipeline.mix_narration_audio')
    def test_metadata_is_the_script_source(self, dialogue, pure):
        from pipeline.main_metadata import load_metadata, save_metadata
        metadata = load_metadata(self.paths)
        metadata['script']['clips'][0]['type'] = 'with_dialogue'
        save_metadata(self.paths, metadata)
        self.pipeline._mix_script_audio()
        pure.assert_not_called()
        self.assertEqual(dialogue.call_count, 4)

    @patch('pipeline.pipeline.probe_source', return_value={'duration': 60})
    @patch('pipeline.pipeline.cut_video_range')
    @patch('pipeline.pipeline.cut_video', return_value='hook.mp4')
    def test_narration_longer_than_scene_is_rejected(self, dialogue, pure, probe):
        self.script['clips'][0]['narrative']['length'] = 13000
        write_json(self.script, self.paths.script)
        with self.assertRaisesRegex(ValueError, '无法承载'):
            self.pipeline._cut_script_videos()
        pure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
