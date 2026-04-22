import unittest
from bs4 import BeautifulSoup

from wespy.main import ArticleFetcher


class WechatUnavailableDetectionTests(unittest.TestCase):
    def test_read_original_hint_with_real_content_is_not_unavailable(self):
        html = '''
        <html><body>
          <h1 class="rich_media_title">国家医保局关于公开发布第九批智能监管“两库”规则和知识点的公告</h1>
          <a id="js_name">国家医保局</a>
          <em id="publish_time">2026年4月21日 19:06</em>
          <div id="js_content">
            <p>国家医保局组织编写的《医疗保障基金智能监管规则库、知识库（2025年版）》已于近日出版发行。</p>
            <p>轻触阅读原文</p>
            <p>微信扫一扫可打开此内容</p>
            <p>使用完整服务</p>
          </div>
        </body></html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        fetcher = ArticleFetcher()
        info = fetcher._extract_wechat_info(soup)
        reason = fetcher._detect_wechat_unavailable_reason(soup, info)
        self.assertIsNone(reason)

    def test_hint_phrases_with_real_content_and_ocr_supplement_is_not_unavailable(self):
        html = '''
        <html><body>
          <h1 class="rich_media_title">关于进一步推进医保信息平台建设的通知</h1>
          <a id="js_name">CHIMA</a>
          <em id="publish_time">2026年4月22日</em>
          <div id="js_content">
            <p>正文已经存在，说明平台建设、标准互通与支付改革要求。</p>
            <p>轻触阅读原文</p>
            <p>微信扫一扫可打开此内容</p>
          </div>
        </body></html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        fetcher = ArticleFetcher()
        info = fetcher._extract_wechat_info(soup)
        info['content_text'] = info['content_text'] + '\n表1：医保支付方式改革进展'
        reason = fetcher._detect_wechat_unavailable_reason(soup, info)
        self.assertIsNone(reason)


if __name__ == '__main__':
    unittest.main()
