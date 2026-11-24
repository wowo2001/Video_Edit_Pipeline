import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from experiments.news_commentary.youtube import upload_news_videos


class NewsYouTubeTests(unittest.TestCase):
    @patch('experiments.news_commentary.youtube.subprocess.check_output', return_value='180.0')
    def test_two_public_uploads_and_progress_on_failure(self, probe):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            files={k:str(root/(k+'.mp4' if 'video' in k else k+'.png')) for k in (
                'commentary_news_video_path','commentary_landscape_video_path',
                'commentary_cover_path','commentary_cover_landscape_path')}
            for path in files.values(): Path(path).write_bytes(b'test')
            (root/'media.json').write_text(json.dumps({'main':{**files, 'commentary_portrait_speed':1.4}}))
            (root/'final_subtitles.json').write_text(json.dumps({'utterances':[{'start_time':0,'end_time':1800,'text':'测试字幕'}]}))
            (root/'commentary_plan.json').write_text(json.dumps({'title':'标题','summary':'简介','tags':['澳洲','新闻']}))
            (root/'source_catalog.json').write_text(json.dumps([{'source_id':'s1','publisher':'ABC','url':'https://example.com'}]))
            ok={'video_id':'id1','url':'https://www.youtube.com/watch?v=id1'}
            with patch('services.youtube_upload.upload_video', side_effect=[ok,RuntimeError('network')]) as upload:
                with self.assertRaises(RuntimeError): upload_news_videos(root)
                for call in upload.call_args_list:
                    self.assertEqual(call.kwargs['privacy'],'public')
                    self.assertIsNone(call.kwargs['publish_at'])
                    self.assertEqual(call.kwargs['tags'],['澳洲','新闻'])
                    self.assertTrue(call.kwargs['contains_synthetic_media'])
            state=json.loads((root/'media.json').read_text())['main']['youtube']
            self.assertEqual(state['portrait']['status'],'completed')
            self.assertEqual(state['landscape']['status'],'failed')
            with patch('services.youtube_upload.upload_video',return_value=ok):
                result=upload_news_videos(root)
            self.assertEqual(set(result),{'portrait','landscape'})
            for duration in ['179.9', '180.0', '180.001', '206.5']:
                probe.return_value = duration
                with patch('services.youtube_upload.upload_video', return_value=ok) as upload:
                    result = upload_news_videos(root)
                    self.assertEqual(upload.call_count, 1 if float(duration) > 180 else 2)
                    if float(duration) > 180:
                        self.assertEqual(result['portrait']['status'], 'skipped')
                        self.assertEqual(upload.call_args.kwargs['video_path'], files['commentary_landscape_video_path'])
                        state = json.loads((root/'media.json').read_text())['main']['youtube']
                        self.assertEqual(state['portrait']['duration_seconds'], float(duration))
            Path(files['commentary_cover_landscape_path']).unlink()
            with patch('services.youtube_upload.upload_video') as upload:
                with self.assertRaises(ValueError): upload_news_videos(root)
                upload.assert_not_called()

if __name__=='__main__': unittest.main()
