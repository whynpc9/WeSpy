import os
import tempfile
import unittest

from wespy.subscriptions import SubscriptionService, SubscriptionStore


class FakeFetcher:
    def __init__(self, result):
        self.result = result

    def fetch_article(self, link, output_dir=None, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        return dict(self.result)


class OCRMergePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, 'wespy.db')
        self.output_root = os.path.join(self.tmpdir.name, 'articles')
        self.store = SubscriptionStore(db_path=self.db_path)
        self.service = SubscriptionService(self.store)
        self.account = {
            'fakeid': 'fakeid-ocr',
            'nickname': 'CHIMA',
            'alias': 'chima1995',
            'avatar': '',
            'signature': '',
            'service_type': 1,
            'total_count': 0,
            'latest_article_time': 0,
            'completed': 0,
        }
        self.store.upsert_account(self.account)
        self.store.upsert_articles('fakeid-ocr', [{
            'link': 'https://mp.weixin.qq.com/s/ocr-test',
            'aid': 'aid-ocr',
            'title': 'OCR测试文章',
            'create_time': 1713650001,
            'itemidx': 1,
            'digest': '摘要',
            'cover': '',
        }])

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_normalize_account_persists_ocr_fields_and_merges_text(self):
        fetcher = FakeFetcher({
            'url': 'https://mp.weixin.qq.com/s/ocr-test',
            'title': 'OCR测试文章',
            'author': 'CHIMA',
            'publish_time': '2026-04-22',
            'content_html': '<div><p>正文第一段</p><img src="https://example.com/1.png"/><p>正文第二段</p></div>',
            'content_text': '正文第一段\n正文第二段',
            'html_content': '<html></html>',
            'ocr_applied': True,
            'ocr_fragments': [
                {
                    'image_src': 'https://example.com/1.png',
                    'char_count': 18,
                    'text': '表1：医保支付方式改革进展',
                    'preview': '表1：医保支付方式改革进展',
                }
            ],
        })

        result = self.service.normalize_account('CHIMA', fetcher, output_root=self.output_root, limit=1)
        self.assertEqual(result['success'], 1)

        content = self.store.get_article_content('https://mp.weixin.qq.com/s/ocr-test')
        self.assertEqual(content['ocr_applied'], 1)
        self.assertIn('医保支付方式改革进展', content['cleaned_text'])
        self.assertIn('医保支付方式改革进展', content['ocr_summary'])

    def test_normalize_account_without_ocr_keeps_ocr_fields_empty(self):
        fetcher = FakeFetcher({
            'url': 'https://mp.weixin.qq.com/s/ocr-test',
            'title': 'OCR测试文章',
            'author': 'CHIMA',
            'publish_time': '2026-04-22',
            'content_html': '<div><p>普通正文</p></div>',
            'content_text': '普通正文',
            'html_content': '<html></html>',
        })

        result = self.service.normalize_account('CHIMA', fetcher, output_root=self.output_root, limit=1)
        self.assertEqual(result['success'], 1)

        content = self.store.get_article_content('https://mp.weixin.qq.com/s/ocr-test')
        self.assertEqual(content['ocr_applied'], 0)
        self.assertIn(content['ocr_summary'] or '', ['',])
        self.assertEqual(content['cleaned_text'], '普通正文')


if __name__ == '__main__':
    unittest.main()
