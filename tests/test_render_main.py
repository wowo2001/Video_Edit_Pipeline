import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import render_main
from core.path import ProjectPaths
from pipeline.source_preprocess import default_profile, load_json, save_json


class RenderMainTests(unittest.TestCase):
    def test_metadata_is_used_for_title_popup_and_speed_settings(self):
        from pipeline.main_metadata import load_metadata, save_metadata
        with tempfile.TemporaryDirectory() as directory:
            paths = ProjectPaths(Path(directory))
            save_json(paths.media, {'main': {'drama_title': '测试剧', 'episode': 8}})
            paths.final_video.write_bytes(b'finished-video')
            metadata = load_metadata(paths)
            metadata['render'].update(title='metadata 标题', subtitle='metadata 副标题', speed=1.1)
            metadata['render']['overlay_layout']['popup']['y'] = 500
            save_metadata(paths, metadata)
            with patch('render_main.MainPostProcessor') as processor, patch('builtins.print'):
                processor.return_value.run.return_value = paths.final_video
                render_main.main(['--work', str(paths.root), '--use-existing-subtitles'])
            args, kwargs = processor.return_value.run.call_args
            self.assertEqual(args, ('metadata 标题', None))
            self.assertEqual(kwargs['text_layout']['popup']['y'], 500)
            self.assertIsNone(kwargs['speed'], '默认应保留 metadata 中的速度')

    def test_display_title_override_keeps_the_original_drama_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = ProjectPaths(root)
            profile = root/'profile.json'
            save_json(profile, default_profile(dict(width=1280,height=720,fps='25/1'), '原剧名'))
            save_json(paths.media, {'main': {'task_title':'原剧名','task_subtitle':'原选题',
                                            'source_master':{'profile':{'drama_title':'原剧名'}}}})
            paths.final_video.write_bytes(b'finished-video')
            with patch('render_main.MainPostProcessor') as processor, patch('builtins.print'):
                processor.return_value.run.return_value = paths.final_video
                result = render_main.main(['--work',str(root),'--profile',str(profile),
                    '--title','新展示标题','--subtitle','新选题','--use-existing-subtitles'])
            self.assertEqual(result,0)
            self.assertEqual(processor.return_value.run.call_args.args,('新展示标题','新选题'))
            self.assertEqual(load_json(paths.media)['main']['drama_title'],'原剧名')
            self.assertEqual((root/'新选题.mp4').read_bytes(),b'finished-video')


if __name__=='__main__':
    unittest.main()
