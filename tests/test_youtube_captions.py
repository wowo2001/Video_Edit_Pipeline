import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from services.youtube_upload import upload_caption
from experiments.news_commentary.youtube import create_upload_subtitles

class CaptionsTests(unittest.TestCase):
    def test_cover_and_orientation_speed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'final_subtitles.json').write_text(json.dumps({'utterances':[{'start_time':0,'end_time':1800,'text':'中文'}]}))
            portrait=Path(create_upload_subtitles(root,'portrait',{'commentary_portrait_speed':1.6})).read_text()
            landscape=Path(create_upload_subtitles(root,'landscape',{})).read_text()
            self.assertIn('00:00:00,625 --> 00:00:01,750',portrait)
            self.assertIn('00:00:00,714 --> 00:00:02,000',landscape)

    def test_insert_skip_and_recover_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'a.srt';path.write_text('subtitle')
            receipt=Path(folder)/'receipt.json';state={'video_id':'v'};service=MagicMock()
            service.captions.return_value.list.return_value.execute.return_value={'items':[]}
            service.captions.return_value.insert.return_value.execute.side_effect=[RuntimeError('network'),{'id':'c'}]
            with self.assertRaises(RuntimeError):upload_caption(service,state,receipt,path,'zh-Hans','简体中文')
            self.assertNotIn('caption',state)
            upload_caption(service,state,receipt,path,'zh-Hans','简体中文')
            upload_caption(service,state,receipt,path,'zh-Hans','简体中文')
            self.assertEqual(service.captions.return_value.insert.call_count,2)
            service.captions.return_value.list.return_value.execute.return_value={'items':[{'id':'c','snippet':{'language':'zh-Hans','name':'简体中文'}}]}
            service.captions.return_value.update.return_value.execute.return_value={'id':'c'}
            state.pop('caption')
            upload_caption(service,state,receipt,path,'zh-Hans','简体中文')
            service.captions.return_value.update.assert_called_once()
