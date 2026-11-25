import unittest
from datetime import datetime, timezone

from services.guardian import parse_guardian_news, validate_url


class GuardianTests(unittest.TestCase):
    def test_date_filter_dedup_and_special_pages(self):
        def item(path, date):
            return f'<item><title>A &amp; B</title><link>https://www.theguardian.com/{path}</link><pubDate>{date}</pubDate></item>'
        recent = 'Sat, 14 Nov 2026 19:00:00 GMT'
        xml = '<rss><channel>' + ''.join([
            item('business/2026/nov/14/example', recent),
            item('business/2026/nov/14/example', recent),
            item('business/live/2026/nov/14/example', recent),
            item('commentisfree/picture/2026/nov/14/cartoon', recent),
            item('business/2026/nov/01/old', 'Sun, 01 Nov 2026 19:00:00 GMT'),
        ]) + '</channel></rss>'
        rows = parse_guardian_news(xml, 3, now=datetime(2026, 11, 15, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'A & B')
        self.assertEqual(rows[0]['published_at'], '2026-11-14T19:00:00+00:00')
        self.assertEqual(rows[0]['source_type'], 'article')

    def test_invalid_response_is_not_empty_success(self):
        with self.assertRaises(ValueError):
            parse_guardian_news('<html/>')
        with self.assertRaises(ValueError):
            validate_url('https://www.theguardian.com.example.org/business')
