import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from services.cis import validate_url, parse_listing, fetch_cis_news, TZ, DEFAULT_URL


class CISTests(unittest.TestCase):
    def test_url_validation(self):
        validate_url(DEFAULT_URL)
        validate_url('https://www.cis.org.au/commentary/opinion/test/', article=True)
        for url in ['https://example.com/commentary/opinions/', 'http://www.cis.org.au/commentary/opinions/', 'https://www.cis.org.au/research/']:
            with self.assertRaises(ValueError): validate_url(url)

    def test_listing_contract(self):
        page=MagicMock()
        page.locator.return_value.evaluate_all.return_value=[dict(title='Title',date='November 8, 2026',url='/commentary/opinion/test/',image='/image.png')]
        page.locator.return_value.count.return_value=0
        rows,next_url=parse_listing(page, DEFAULT_URL)
        self.assertIsNone(next_url)
        page.locator.return_value.count.return_value=1
        page.locator.return_value.first.get_attribute.return_value=DEFAULT_URL+'?e-page-0b1537f=2'
        _, next_url=parse_listing(page,DEFAULT_URL)
        self.assertIn('paged=2',next_url)
        self.assertEqual(rows[0]['source_type'],'article')
        self.assertTrue(rows[0]['video_id'].startswith('cis_'))
        self.assertEqual(rows[0]['published_at'],'2026-11-08T00:00:00+11:00')
        self.assertEqual(rows[0]['thumbnail_url'],'https://www.cis.org.au/image.png')

    @patch('services.cis.sync_playwright')
    @patch('services.cis.load')
    @patch('services.cis.parse_listing')
    def test_date_boundaries_dedup_and_pagination(self,parse,load,browser):
        def row(day):return dict(url=f'https://www.cis.org.au/commentary/opinion/{day}/',published_at=f'2026-11-{day:02d}T00:00:00+11:00')
        parse.side_effect=[([row(9),row(8),row(7)],DEFAULT_URL+'?page=2'),
                           ([row(7),row(6)],DEFAULT_URL+'?page=3'),
                           ([row(5)],DEFAULT_URL+'?page=4')]
        rows=fetch_cis_news(days=3,now=datetime(2026,11,8,tzinfo=TZ),log=lambda _:None)
        self.assertEqual([r['published_at'][8:10] for r in rows],['08','07','06'])
        self.assertEqual(load.call_count,3)

if __name__=='__main__':unittest.main()
