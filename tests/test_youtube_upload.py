import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from services.youtube_upload import metadata, upload_video, wait_processed


class YouTubeUploadTests(unittest.TestCase):
    def test_metadata_and_schedule_validation(self):
        self.assertEqual(metadata('测试')['status']['privacyStatus'], 'private')
        for kwargs in [dict(title=''), dict(title='x', description='中'*1700),
                       dict(title='x', privacy='public', publish_at='2099-01-01T00:00:00Z'),
                       dict(title='x', publish_at='2099-01-01T00:00:00')]:
            with self.assertRaises(ValueError):
                metadata(**kwargs)
        self.assertIn('publishAt', metadata('x', publish_at='2099-01-01T00:00:00+11:00')['status'])

    def test_upload_receipt_and_thumbnail_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp)/'video.mp4'; video.write_bytes(b'test video')
            cover = Path(tmp)/'cover.png'; cover.write_bytes(b'test cover')
            service = MagicMock()
            service.channels.return_value.list.return_value.execute.return_value = {'items': [{'id': 'channel'}]}
            service.videos.return_value.insert.return_value.next_chunk.return_value = (None, {'id': 'video-id'})
            service.videos.return_value.list.return_value.execute.return_value = {'items': [
                {'processingDetails': {'processingStatus': 'succeeded'}}]}
            service.thumbnails.return_value.set.return_value.execute.side_effect = [RuntimeError('temporary'), {}]
            args = dict(video_path=video, title='标题', channel_id='channel', thumbnail_path=cover, service=service)
            with self.assertRaises(RuntimeError):
                upload_video(**args)
            self.assertEqual(json.loads(video.with_suffix('.youtube.json').read_text())['video_id'], 'video-id')
            result = upload_video(**args)
            self.assertIn('thumbnail_sha256', result)
            upload_video(**args)
            self.assertEqual(service.videos.return_value.insert.call_count, 1)
            self.assertEqual(service.thumbnails.return_value.set.call_count, 2)
            with self.assertRaises(ValueError):
                upload_video(**{**args, 'title': 'different'})

    def test_wrong_channel_never_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'v.mp4';video.write_bytes(b'test')
            service=MagicMock()
            service.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'other'}]}
            with self.assertRaises(ValueError):
                upload_video(video_path=video, title='x', channel_id='wanted', service=service)
            service.videos.return_value.insert.assert_not_called()

    def test_processing_failure_and_timeout(self):
        service=MagicMock()
        service.videos.return_value.list.return_value.execute.return_value={'items':[{'processingDetails':{'processingStatus':'failed'}}]}
        with self.assertRaises(RuntimeError):
            wait_processed(service, 'id')
        service.videos.return_value.list.return_value.execute.return_value={'items':[]}
        with self.assertRaises(TimeoutError):
            wait_processed(service, 'id', timeout=0)


if __name__ == '__main__':
    unittest.main()
