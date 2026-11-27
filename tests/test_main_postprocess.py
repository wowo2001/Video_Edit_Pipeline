import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.captions import DEFAULT_CAPTION_LAYOUT
from core.path import ProjectPaths
from pipeline.main_postprocess import MainPostProcessor
from pipeline.source_preprocess import load_json, save_json

SRT = "1\n00:00:00,100 --> 00:00:01,000\n为什么他又回来了？\n\n"


class MainPostprocessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = ProjectPaths(Path(self.directory.name))
        self.paths.concatenated_video.write_bytes(b"source-video-v1")
        save_json(self.paths.media, {"main": {
            "concatenated_video_path": str(self.paths.concatenated_video),
            "source_video_path": "untouched-source-master.mp4",
            "speed_up_video_path": "obsolete.mp4", "masked_video_path": "obsolete2.mp4"}})
        self.asr = Mock(side_effect=self.transcribe)
        self.fix = Mock(side_effect=self.correct)
        self.processor = MainPostProcessor(self.paths, self.asr, self.fix)
        self.audio_patch = patch('pipeline.main_postprocess.export_recognition_audio', side_effect=self.audio)
        self.render_patch = patch('pipeline.main_postprocess.render_final_video', side_effect=self.render)
        self.audio_call = self.audio_patch.start()
        self.render_call = self.render_patch.start()
        self.addCleanup(self.audio_patch.stop)
        self.addCleanup(self.render_patch.stop)

    def audio(self, source, destination, speed):
        Path(destination).write_bytes(b'clean-audio-'+Path(source).read_bytes()+str(speed).encode())

    def transcribe(self, audio, output):
        Path(output['srt']).write_text(SRT, encoding='utf-8')
        save_json(output['json'], {'utterances': []})

    def correct(self, source, destination):
        Path(destination).write_text(Path(source).read_text(encoding='utf-8'), encoding='utf-8')
        return [{'start_time': .2, 'text': '这次他想干什么？'}], 'unused model title'

    def render(self, source, destination, *_args, **kwargs):
        Path(destination).write_bytes(b'final')
        return {'path': str(destination), 'speed': kwargs['speed'], 'video_encode_passes': 1}

    def test_layout_title_and_music_changes_reuse_asr_and_ai(self):
        self.processor.run('剧名', '旧标题')
        changed = {**DEFAULT_CAPTION_LAYOUT, 'width': 680}
        music_path = self.paths.root/'music.mp3'
        music_path.write_bytes(b'music')
        self.processor.run('剧名', "新标题's 100%", caption_layout=changed,
                           text_layout={'title': {'y': 300}, 'popup': {'font_size': 60}},
                           background_music={'path': music_path, 'volume': .06})
        self.assertEqual(self.audio_call.call_count, 1)
        self.assertEqual(self.asr.call_count, 1)
        self.assertEqual(self.fix.call_count, 1)
        self.assertEqual(self.render_call.call_count, 2)
        args, kwargs = self.render_call.call_args
        self.assertEqual(args[0], self.paths.concatenated_video)
        self.assertEqual(args[5]['width'], 680)
        self.assertEqual(kwargs['speed'], 1.2)
        self.assertEqual(kwargs['music_volume'], .06)
        self.assertEqual(kwargs['text_layout']['title']['y'], 300)
        self.assertEqual(kwargs['text_layout']['popup']['font_size'], 60)
        media = load_json(self.paths.media)['main']
        self.assertEqual(media['source_video_path'], 'untouched-source-master.mp4')
        self.assertNotIn('speed_up_video_path', media)
        self.assertNotIn('masked_video_path', media)

    def test_ai_title_and_metadata_edits_survive_cached_rerender(self):
        from pipeline.main_metadata import load_metadata, save_metadata
        self.processor.run('剧名')
        metadata = load_metadata(self.paths)
        self.assertEqual(metadata['render']['subtitle'], 'unused model title')
        self.assertEqual(metadata['render']['generated_subtitle'], 'unused model title')
        metadata['render'].update(title='自定义标题', subtitle='自定义副标题',
                                  popup_comments=[{'start_time': .4, 'text': '编辑后的弹幕'}])
        metadata['render']['overlay_layout']['popup']['y'] = 500
        metadata['render']['background_opacity'] = .25
        save_metadata(self.paths, metadata)
        self.processor.run()
        args, kwargs = self.render_call.call_args
        self.assertEqual(args[3:5], ('自定义标题', '自定义副标题'))
        self.assertEqual(args[6], metadata['render']['popup_comments'])
        self.assertEqual(kwargs['text_layout']['popup']['y'], 500)
        self.assertEqual(kwargs['background_opacity'], .25)
        self.assertEqual(self.fix.call_count, 1)
        self.assertEqual(self.asr.call_count, 1)

    def test_speed_or_source_changes_invalidate_recognition(self):
        self.processor.run('剧名', '标题')
        self.processor.run('剧名', '标题', speed=1.4)
        self.paths.concatenated_video.write_bytes(b'different-footage')
        self.processor.run('剧名', '标题', speed=1.4)
        self.assertEqual(self.asr.call_count, 3)
        self.assertEqual(self.fix.call_count, 3)

    def test_old_correction_cache_is_replaced_without_repeating_asr(self):
        from pipeline.main_postprocess import signature
        from prompts.fix_subtitles import FIX_SUBTITLE_PROMPT
        from prompts.fix_subtitles_input import FIX_SUBTITLES_INPUT_PROMPT

        self.processor.run('剧名', '标题')
        state_path = self.paths.root/'main_postprocess.json'
        state = load_json(state_path)
        state['fix_key'] = signature({
            'asr': state['asr_key'], 'raw': state['raw_hash'], 'version': 1,
            'prompt': FIX_SUBTITLE_PROMPT+FIX_SUBTITLES_INPUT_PROMPT})
        state.pop('fix_provider', None)
        state.pop('fix_model', None)
        save_json(state_path, state)

        self.processor.run('剧名', '标题')
        self.assertEqual(self.asr.call_count, 1)
        self.assertEqual(self.fix.call_count, 2)
        state = load_json(state_path)
        self.assertEqual(state['fix_provider'], 'openai')
        self.assertEqual(state['fix_model'], 'gpt-6-luna')

    def test_failed_ai_keeps_raw_recognition_for_retry(self):
        self.fix.side_effect = RuntimeError('bad JSON')
        with self.assertRaisesRegex(RuntimeError, 'bad JSON'):
            self.processor.run('剧名', '标题')
        self.assertEqual(self.render_call.call_count, 0)
        self.fix.side_effect = self.correct
        self.processor.run('剧名', '标题')
        self.assertEqual(self.asr.call_count, 1)
        self.assertEqual(self.fix.call_count, 2)

    def test_manual_corrected_srt_is_kept_on_render_only_changes(self):
        self.processor.run('剧名', '标题')
        edited = SRT.replace('为什么他又回来了？', '手动修正后的字幕')
        self.paths.final_subtitles['srt'].write_text(edited, encoding='utf-8')
        self.processor.run('剧名', '新标题')
        self.assertEqual(self.fix.call_count, 1)
        self.assertEqual(self.paths.final_subtitles['srt'].read_text(encoding='utf-8'), edited)

    def test_refresh_forces_asr_but_not_clean_audio_export(self):
        self.processor.run('剧名', '标题')
        self.processor.run('剧名', '标题', refresh_subtitles=True)
        self.assertEqual(self.asr.call_count, 2)
        self.assertEqual(self.fix.call_count, 2)
        self.assertEqual(self.audio_call.call_count, 1)

    def test_legacy_existing_subtitles_do_not_call_cloud_services(self):
        self.paths.final_subtitles['srt'].write_text(SRT, encoding='utf-8')
        self.processor.run('剧名', '标题', use_existing_subtitles=True)
        self.asr.assert_not_called()
        self.fix.assert_not_called()
        self.audio_call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
