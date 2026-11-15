import unittest
from services.domain import parse_listing, validate_url


class DomainTests(unittest.TestCase):
    def test_published_date_not_modified_date(self):
        rows = parse_listing({'data': {'articles': [{
            'canonicalUrl': 'https://www.domain.com.au/research/example-123/',
            'title': 'Example', 'publishedDate': '2026-11-14T00:29:00+1100',
            'modifiedDate': '2026-11-15T10:00:00+1100',
            'featuredImage': {'sizes': {'full': {'url': 'https://res.domain.com.au/a.jpg'}}}
        }]}})
        self.assertEqual(rows[0]['published_at'], '2026-11-14T00:29:00+11:00')
        self.assertEqual(rows[0]['publisher'], 'Domain')
        self.assertEqual(rows[0]['source_type'], 'article')
        self.assertEqual(rows[0]['thumbnail_url'], 'https://res.domain.com.au/a.jpg')

    def test_reject_other_hosts(self):
        for url in ['https://www.domain.com.au.example.com/news/test/']:
            with self.assertRaises(ValueError):
                validate_url(url, article=True)
        validate_url('https://www.domain.com.au/topics/owners/page/2/')

    def test_news_listing_and_partner_links(self):
        validate_url('https://www.domain.com.au/news/')
        validate_url('https://www.domain.com.au/news/page/2/')
        validate_url('https://www.domain.com.au/news/example-123/')
        validate_url('https://www.domain.com.au/any/new/section/')
        with self.assertRaisesRegex(ValueError, '没有文章列表'):
            parse_listing({'articleData': {}})
        self.assertEqual(parse_listing({'data': {'articles': [{
            'canonicalUrl': 'https://www.allhomes.com.au/news/example-123/'
        }]}}), [])
