import os
import tempfile
import unittest

from bs4 import BeautifulSoup

from wespy.main import ArticleFetcher
from wespy.subscriptions import SubscriptionStore, SubscriptionService


class FakeFetcher:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def fetch_article(self, link, output_dir=None, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        self.calls.append({
            'link': link,
            'output_dir': output_dir,
            'save_html': save_html,
            'save_json': save_json,
            'save_markdown': save_markdown,
            'save_pdf': save_pdf,
        })
        return dict(self.result)


class ArticleNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, 'wespy.db')
        self.output_root = os.path.join(self.tmpdir.name, 'articles')
        self.store = SubscriptionStore(db_path=self.db_path)
        self.service = SubscriptionService(self.store)
        self.account = {
            'fakeid': 'fakeid-1',
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
        self.store.upsert_articles('fakeid-1', [{
            'link': 'https://mp.weixin.qq.com/s/test1',
            'aid': 'aid-1',
            'title': '测试文章',
            'create_time': 1713650000,
            'itemidx': 1,
            'digest': '摘要',
            'cover': '',
        }])

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_profile_aware_cleaning_removes_configured_noise(self):
        fetcher = ArticleFetcher()
        html = '''
        <div id="js_content">
          <p>欢迎关注CHIMA</p>
          <p>这是正文第一段</p>
          <div class="advertisement">广告内容</div>
          <p>这是正文第二段</p>
          <p>免责声明</p>
          <p>尾部推荐内容</p>
        </div>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        profile = self.service.resolve_extraction_profile(self.store.get_account('CHIMA'))
        cleaned = fetcher._clean_content_element(soup.find('div', {'id': 'js_content'}), source='wechat', profile=profile)
        text = cleaned.get_text('\n', strip=True)

        self.assertIn('这是正文第一段', text)
        self.assertIn('这是正文第二段', text)
        self.assertNotIn('欢迎关注CHIMA', text)
        self.assertNotIn('广告内容', text)
        self.assertNotIn('免责声明', text)

    def test_trailing_marker_in_mid_article_does_not_remove_following_real_content(self):
        fetcher = ArticleFetcher()
        html = '''
        <div id="js_content">
          <p>第一段介绍内容，说明本文研究背景与政策上下文。</p>
          <p>第二段继续说明系统建设、标准接口与实施路径。</p>
          <p>第三段补充项目现状、机构协同和试点评估结果。</p>
          <blockquote>免责声明：这里引用的是外部机构的一段原始表述。</blockquote>
          <p>第四段是真实正文，继续分析数据治理、互联互通与支付改革。</p>
          <p>第五段也是真实正文，总结后续落地建议和执行重点。</p>
        </div>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        profile = self.service.resolve_extraction_profile(self.store.get_account('CHIMA'))
        cleaned = fetcher._clean_content_element(soup.find('div', {'id': 'js_content'}), source='wechat', profile=profile)
        text = cleaned.get_text('\n', strip=True)

        self.assertIn('第四段是真实正文', text)
        self.assertIn('第五段也是真实正文', text)

    def test_normalize_account_persists_content(self):
        fetcher = FakeFetcher({
            'url': 'https://mp.weixin.qq.com/s/test1',
            'title': '测试文章',
            'author': 'CHIMA',
            'publish_time': '2026-04-21',
            'content_html': '<div><p>正文</p><p>联系我们</p></div>',
            'content_text': '正文',
            'html_content': '<html></html>',
        })

        result = self.service.normalize_account('CHIMA', fetcher, output_root=self.output_root, limit=1)
        self.assertEqual(result['success'], 1)
        self.assertEqual(result['unavailable'], 0)

        content = self.store.get_article_content('https://mp.weixin.qq.com/s/test1')
        self.assertEqual(content['fetch_status'], 'normalized')
        self.assertEqual(content['title'], '测试文章')
        self.assertEqual(content['author'], 'CHIMA')
        self.assertIn('正文', content['cleaned_text'])
        article = self.store.list_articles('fakeid-1', only_undownloaded=False, limit=1)[0]
        self.assertEqual(article['download_status'], 'normalized')

    def test_normalize_account_persists_profile_metadata(self):
        fetcher = FakeFetcher({
            'url': 'https://mp.weixin.qq.com/s/test1',
            'title': '测试文章',
            'author': 'CHIMA',
            'publish_time': '2026-04-21',
            'content_html': '<div><p>正文</p></div>',
            'content_text': '正文',
            'html_content': '<html></html>',
        })

        self.service.normalize_account('CHIMA', fetcher, output_root=self.output_root, limit=1)
        content = self.store.get_article_content('https://mp.weixin.qq.com/s/test1')

        self.assertEqual(content['extraction_profile'], 'chima')
        self.assertEqual(content['extraction_profile_version'], '2026-04-22')
        self.assertIsNotNone(content['normalization_notes'])

    def test_normalize_account_marks_unavailable(self):
        fetcher = FakeFetcher({
            'url': 'https://mp.weixin.qq.com/s/test1',
            'title': '测试文章',
            'author': 'CHIMA',
            'publish_time': '2026-04-21',
            'fetch_status': 'unavailable',
            'unavailable_reason': '内容已删除',
        })

        result = self.service.normalize_account('CHIMA', fetcher, output_root=self.output_root, limit=1)
        self.assertEqual(result['success'], 0)
        self.assertEqual(result['unavailable'], 1)

        content = self.store.get_article_content('https://mp.weixin.qq.com/s/test1')
        self.assertEqual(content['fetch_status'], 'unavailable')
        self.assertEqual(content['unavailable_reason'], '内容已删除')


if __name__ == '__main__':
    unittest.main()
