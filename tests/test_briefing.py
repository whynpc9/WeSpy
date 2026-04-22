import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from wespy.briefing import build_brief_payload, classify_article_title, render_brief_markdown
from wespy.main import _build_brief, _run_subscription_cli
from wespy.subscriptions import SubscriptionService, SubscriptionStore


class FakeFetcher:
    def __init__(self, result):
        self.result = result

    def fetch_article(self, link, output_dir=None, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        return dict(self.result)


class BriefingTests(unittest.TestCase):
    def test_classify_article_title(self):
        self.assertEqual(classify_article_title("国家医保局发布医保支付新规"), "政策规范")
        self.assertEqual(classify_article_title("某医院信息化建设项目招标公告"), "招标采购信息")
        self.assertEqual(classify_article_title("AI医疗研究论文发表于 Nature 子刊"), "研究论文")
        self.assertEqual(classify_article_title("CHIMA 2026 会议讲座报名开启"), "会议讲座")

    def test_build_brief_payload_groups_and_dedupes_articles(self):
        rows = [
            {
                "title": "国家医保局发布医保支付新规",
                "link": "https://mp.weixin.qq.com/s/1",
                "nickname": "国家医保局",
                "create_time": 1713650000,
                "cleaned_text": "聚焦医保支付改革、数据互通与监管要求。",
            },
            {
                "title": "国家医保局发布医保支付新规（解读）",
                "link": "https://mp.weixin.qq.com/s/2",
                "nickname": "中国医疗保障",
                "create_time": 1713651000,
                "cleaned_text": "对医保支付新规进行延伸解读。",
            },
            {
                "title": "CHIMA 2026 会议讲座报名开启",
                "link": "https://mp.weixin.qq.com/s/3",
                "nickname": "CHIMA",
                "create_time": 1713652000,
                "cleaned_text": "介绍会议信息、报名时间与议题设置。",
            },
        ]

        payload = build_brief_payload("医疗信息", "2026-04-21", rows)
        self.assertEqual(payload["domain"], "医疗信息")
        self.assertEqual(payload["brief_date"], "2026-04-21")
        self.assertEqual(payload["total_candidates"], 3)
        self.assertEqual(payload["total_selected"], 2)
        self.assertIn("政策规范", payload["sections"])
        self.assertIn("会议讲座", payload["sections"])
        self.assertEqual(len(payload["sections"]["政策规范"]["items"]), 1)
        self.assertEqual(payload["sections"]["政策规范"]["items"][0]["source_account"], "国家医保局")
        self.assertIn("支付改革", payload["sections"]["政策规范"]["section_summary"])
        self.assertIn("数据互通", payload["sections"]["政策规范"]["section_summary"])
        self.assertNotIn("本栏目共收录", payload["sections"]["政策规范"]["section_summary"])

    def test_build_brief_prefers_normalized_article_bodies(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(tmpdir.name, 'wespy.db')
            store = SubscriptionStore(db_path=db_path)
            service = SubscriptionService(store)
            service.ensure_default_domain()
            store.upsert_account({
                'fakeid': 'fakeid-1',
                'nickname': 'CHIMA',
                'alias': 'chima1995',
                'avatar': '',
                'signature': '',
                'service_type': 1,
                'total_count': 0,
                'latest_article_time': 0,
                'completed': 0,
            })
            store.add_subscription_to_domain('医疗信息', 'fakeid-1')
            store.upsert_articles('fakeid-1', [{
                'link': 'https://mp.weixin.qq.com/s/brief1',
                'aid': 'aid-1',
                'title': '国家医保局发布医保支付新规',
                'create_time': 1713650000,
                'itemidx': 1,
                'digest': '摘要',
                'cover': '',
            }])
            store.upsert_article_content(
                'https://mp.weixin.qq.com/s/brief1',
                'fakeid-1',
                title='国家医保局发布医保支付新规',
                author='CHIMA',
                publish_time_text='2024-04-21',
                fetch_status='normalized',
                cleaned_html='<div><p>正文</p></div>',
                cleaned_text='欢迎关注CHIMA。本文系会议现场报道。国家医保局发布新规，明确支付改革、数据互通与执行路径。后续还说明了医保信息平台建设、标准接口和落地要求。该政策将影响医院信息平台建设与后续执行安排。扫码回复资料。联系我们获取更多信息。',
                html_content='<html></html>',
                extraction_profile='chima',
                extraction_profile_version='2026-04-22',
                normalization_notes='{"actions":["lead_trim"]}',
            )

            payload = _build_brief(service, '医疗信息', date_value='2024-04-21')
            section = payload['sections']['政策规范']
            section_item = section['items'][0]
            self.assertEqual(section_item['source_account'], 'CHIMA')
            self.assertEqual(section_item['fetch_status'], 'normalized')
            self.assertIn('支付改革', section_item['cleaned_text'])
            self.assertEqual(section_item['extraction_profile'], 'chima')
            self.assertIn('支付改革', section_item['summary'])
            self.assertIn('标准接口', section_item['summary'])
            self.assertIn('影响医院信息平台建设与后续执行', section_item['summary'])
            self.assertEqual(section_item['summary'].count('支付改革'), 1)
            self.assertNotIn('欢迎关注', section_item['summary'])
            self.assertNotIn('扫码', section_item['summary'])
            self.assertNotIn('联系我们', section_item['summary'])
            self.assertNotIn('会议现场报道', section_item['summary'])
            self.assertTrue(len(section_item['summary']) >= 40)
            self.assertIn('支付改革', section['section_summary'])
            self.assertIn('值得关注', section_item['why_it_matters'])
        finally:
            tmpdir.cleanup()

    def test_build_brief_payload_ranks_high_value_articles_first_within_section(self):
        rows = [
            {
                "title": "医保支付改革政策地方执行细则",
                "link": "https://mp.weixin.qq.com/s/low",
                "nickname": "地方医信观察",
                "create_time": 1713650001,
                "fetch_status": "pending",
                "cleaned_text": "医保支付改革。",
                "ocr_applied": 0,
            },
            {
                "title": "医保支付改革政策国家解读",
                "link": "https://mp.weixin.qq.com/s/high",
                "nickname": "国家医保局",
                "create_time": 1713650000,
                "fetch_status": "normalized",
                "cleaned_text": "国家医保局详细说明医保支付改革、数据互通、标准接口、平台建设与执行路径，明确后续落地重点。",
                "ocr_applied": 1,
                "ocr_summary": "OCR补全了关键图表说明",
            },
            {
                "title": "医保支付改革政策行业观察",
                "link": "https://mp.weixin.qq.com/s/mid",
                "nickname": "CHIMA",
                "create_time": 1713650002,
                "fetch_status": "normalized",
                "cleaned_text": "文章介绍医保支付改革和平台建设。",
                "ocr_applied": 0,
            },
        ]

        payload = build_brief_payload("医疗信息", "2026-04-21", rows)
        items = payload["sections"]["政策规范"]["items"]

        self.assertEqual(items[0]["title"], "医保支付改革政策国家解读")
        self.assertEqual(items[1]["title"], "医保支付改革政策行业观察")
        self.assertEqual(items[2]["title"], "医保支付改革政策地方执行细则")
        self.assertIn("国家解读", payload["sections"]["政策规范"]["section_summary"])

    def test_explain_why_it_matters_is_specific_by_content_type(self):
        policy_payload = build_brief_payload("医疗信息", "2026-04-21", [{
            "title": "国家医保局发布医保支付新规",
            "nickname": "国家医保局",
            "create_time": 1713650000,
            "cleaned_text": "国家医保局发布新规，明确医保支付改革与执行要求。",
        }])
        policy_text = policy_payload["sections"]["政策规范"]["items"][0]["why_it_matters"]
        self.assertIn("执行口径", policy_text)
        self.assertIn("医院", policy_text)

        meeting_payload = build_brief_payload("医疗信息", "2026-04-21", [{
            "title": "CHIMA 2026 会议讲座报名开启",
            "nickname": "CHIMA",
            "create_time": 1713650001,
            "cleaned_text": "会议报名开启，将发布今年重点议题与日程安排。",
        }])
        meeting_text = meeting_payload["sections"]["会议讲座"]["items"][0]["why_it_matters"]
        self.assertIn("议题", meeting_text)
        self.assertIn("参与", meeting_text)

        research_payload = build_brief_payload("医疗信息", "2026-04-21", [{
            "title": "AI医疗研究论文发表于 Nature 子刊",
            "nickname": "医学前沿",
            "create_time": 1713650002,
            "cleaned_text": "该研究给出新的试验结果，并提供可继续验证的证据线索。",
        }])
        research_text = research_payload["sections"]["研究论文"]["items"][0]["why_it_matters"]
        self.assertIn("证据", research_text)
        self.assertIn("验证", research_text)

    def test_brief_generate_cli_outputs_overview_and_markdown_in_json(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(tmpdir.name, 'wespy.db')
            store = SubscriptionStore(db_path=db_path)
            service = SubscriptionService(store)
            service.ensure_default_domain()
            store.upsert_account({
                'fakeid': 'fakeid-brief-cli',
                'nickname': 'CHIMA',
                'alias': 'chima1995',
                'avatar': '',
                'signature': '',
                'service_type': 1,
                'total_count': 0,
                'latest_article_time': 0,
                'completed': 0,
            })
            store.add_subscription_to_domain('医疗信息', 'fakeid-brief-cli')
            store.upsert_articles('fakeid-brief-cli', [{
                'link': 'https://mp.weixin.qq.com/s/brief-cli-1',
                'aid': 'aid-brief-cli-1',
                'title': '国家医保局发布医保支付新规',
                'create_time': 1776729600,
                'itemidx': 1,
                'digest': '摘要',
                'cover': '',
            }])
            store.upsert_article_content(
                'https://mp.weixin.qq.com/s/brief-cli-1',
                'fakeid-brief-cli',
                title='国家医保局发布医保支付新规',
                author='CHIMA',
                publish_time_text='2026-04-21',
                fetch_status='normalized',
                cleaned_html='<div><p>正文</p></div>',
                cleaned_text='国家医保局发布新规，明确医保支付改革、数据互通与执行路径。',
                html_content='<html></html>',
                extraction_profile='chima',
                extraction_profile_version='2026-04-22',
                normalization_notes='{"actions":["lead_trim"]}',
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                _run_subscription_cli([
                    '--db-path', db_path,
                    'brief', 'generate',
                    '--domain', '医疗信息',
                    '--date', '2026-04-21',
                    '--output-json',
                ])
            payload = json.loads(buf.getvalue())
            self.assertTrue(payload['ok'])
            self.assertEqual(payload['command'], 'brief.generate')
            self.assertIn('今日总览', payload['overview'])
            self.assertIn('# 医疗信息 每日简报', payload['markdown'])
            self.assertIn('政策端重点落在', payload['markdown'])
        finally:
            tmpdir.cleanup()

    def test_normalize_account_then_brief_generate_forms_an_integration_chain(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(tmpdir.name, 'wespy.db')
            output_root = os.path.join(tmpdir.name, 'articles')
            store = SubscriptionStore(db_path=db_path)
            service = SubscriptionService(store)
            service.ensure_default_domain()
            store.upsert_account({
                'fakeid': 'fakeid-integration',
                'nickname': 'CHIMA',
                'alias': 'chima1995',
                'avatar': '',
                'signature': '',
                'service_type': 1,
                'total_count': 0,
                'latest_article_time': 0,
                'completed': 0,
            })
            store.add_subscription_to_domain('医疗信息', 'fakeid-integration')
            store.upsert_articles('fakeid-integration', [{
                'link': 'https://mp.weixin.qq.com/s/integration-1',
                'aid': 'aid-integration-1',
                'title': 'CHIMA 2026 会议讲座报名开启',
                'create_time': 1776729600,
                'itemidx': 1,
                'digest': '摘要',
                'cover': '',
            }])

            fetcher = FakeFetcher({
                'url': 'https://mp.weixin.qq.com/s/integration-1',
                'title': 'CHIMA 2026 会议讲座报名开启',
                'author': 'CHIMA',
                'publish_time': '2026-04-21',
                'content_html': '<div><p>会议报名开启，并公布重点议题与日程安排。</p></div>',
                'content_text': '会议报名开启，并公布重点议题与日程安排。',
                'html_content': '<html></html>',
            })
            with patch('wespy.main._build_fetcher', return_value=fetcher):
                normalize_buf = io.StringIO()
                with redirect_stdout(normalize_buf):
                    _run_subscription_cli([
                        '--db-path', db_path,
                        'normalize-account', 'CHIMA',
                        '--limit', '1',
                        '--output-json',
                        '--output', output_root,
                    ])
                normalize_payload = json.loads(normalize_buf.getvalue())

            self.assertTrue(normalize_payload['ok'])
            self.assertEqual(normalize_payload['command'], 'normalize-account')
            self.assertEqual(normalize_payload['result']['success'], 1)

            buf = io.StringIO()
            with redirect_stdout(buf):
                _run_subscription_cli([
                    '--db-path', db_path,
                    'brief', 'generate',
                    '--domain', '医疗信息',
                    '--date', '2026-04-21',
                    '--output-json',
                ])
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload['total_selected'], 1)
            self.assertIn('今日总览', payload['overview'])
            self.assertIn('会议端关注', payload['overview'])
            self.assertIn('CHIMA 2026 会议讲座报名开启', payload['markdown'])
            self.assertIn('重点议题', payload['markdown'])
            self.assertEqual(payload['sections']['会议讲座']['items'][0]['fetch_status'], 'normalized')
        finally:
            tmpdir.cleanup()

    def test_normalize_domain_then_brief_generate_aggregates_multiple_accounts(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(tmpdir.name, 'wespy.db')
            output_root = os.path.join(tmpdir.name, 'articles')
            store = SubscriptionStore(db_path=db_path)
            service = SubscriptionService(store)
            service.ensure_default_domain()

            accounts = [
                {
                    'fakeid': 'fakeid-policy',
                    'nickname': '国家医保局',
                    'alias': 'nhsa',
                    'avatar': '',
                    'signature': '',
                    'service_type': 1,
                    'total_count': 0,
                    'latest_article_time': 0,
                    'completed': 0,
                },
                {
                    'fakeid': 'fakeid-meeting',
                    'nickname': 'CHIMA',
                    'alias': 'chima1995',
                    'avatar': '',
                    'signature': '',
                    'service_type': 1,
                    'total_count': 0,
                    'latest_article_time': 0,
                    'completed': 0,
                },
            ]
            for account in accounts:
                store.upsert_account(account)
                store.add_subscription_to_domain('医疗信息', account['fakeid'])

            store.upsert_articles('fakeid-policy', [{
                'link': 'https://mp.weixin.qq.com/s/domain-policy-1',
                'aid': 'aid-domain-policy-1',
                'title': '国家医保局发布医保支付新规',
                'create_time': 1776729600,
                'itemidx': 1,
                'digest': '摘要',
                'cover': '',
            }])
            store.upsert_articles('fakeid-meeting', [{
                'link': 'https://mp.weixin.qq.com/s/domain-meeting-1',
                'aid': 'aid-domain-meeting-1',
                'title': 'CHIMA 2026 会议讲座报名开启',
                'create_time': 1776729601,
                'itemidx': 1,
                'digest': '摘要',
                'cover': '',
            }])

            class MultiFetcher:
                def fetch_article(self, link, output_dir=None, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
                    if 'domain-policy-1' in link:
                        return {
                            'url': link,
                            'title': '国家医保局发布医保支付新规',
                            'author': '国家医保局',
                            'publish_time': '2026-04-21',
                            'content_html': '<div><p>国家医保局发布新规，明确医保支付改革、数据互通与执行路径。</p></div>',
                            'content_text': '国家医保局发布新规，明确医保支付改革、数据互通与执行路径。',
                            'html_content': '<html></html>',
                        }
                    return {
                        'url': link,
                        'title': 'CHIMA 2026 会议讲座报名开启',
                        'author': 'CHIMA',
                        'publish_time': '2026-04-21',
                        'content_html': '<div><p>会议报名开启，并公布重点议题与日程安排。</p></div>',
                        'content_text': '会议报名开启，并公布重点议题与日程安排。',
                        'html_content': '<html></html>',
                    }

            with patch('wespy.main._build_fetcher', return_value=MultiFetcher()):
                normalize_buf = io.StringIO()
                with redirect_stdout(normalize_buf):
                    _run_subscription_cli([
                        '--db-path', db_path,
                        'normalize-domain',
                        '--domain', '医疗信息',
                        '--limit', '1',
                        '--output-json',
                        '--output', output_root,
                    ])
                normalize_payload = json.loads(normalize_buf.getvalue())

            self.assertTrue(normalize_payload['ok'])
            self.assertEqual(normalize_payload['command'], 'normalize-domain')
            self.assertEqual(len(normalize_payload['results']), 2)
            self.assertTrue(all(item['success'] == 1 for item in normalize_payload['results']))

            brief_buf = io.StringIO()
            with redirect_stdout(brief_buf):
                _run_subscription_cli([
                    '--db-path', db_path,
                    'brief', 'generate',
                    '--domain', '医疗信息',
                    '--date', '2026-04-21',
                    '--output-json',
                ])
            payload = json.loads(brief_buf.getvalue())
            self.assertEqual(payload['total_selected'], 2)
            self.assertIn('政策端重点落在', payload['overview'])
            self.assertIn('会议端关注', payload['overview'])
            self.assertIn('政策规范', payload['sections'])
            self.assertIn('会议讲座', payload['sections'])
            self.assertEqual(payload['sections']['政策规范']['items'][0]['fetch_status'], 'normalized')
            self.assertEqual(payload['sections']['会议讲座']['items'][0]['fetch_status'], 'normalized')
        finally:
            tmpdir.cleanup()

    def test_render_brief_markdown_includes_section_summary(self):
        payload = {
            'domain': '医疗信息',
            'brief_date': '2026-04-21',
            'total_candidates': 2,
            'total_selected': 2,
            'overview': '今日总览：政策端重点落在医保支付改革与数据互通，会议端关注报名窗口与议题变化。',
            'sections': {
                '政策规范': {
                    'section_summary': '本栏目聚焦医保支付改革与政策落地要求。',
                    'items': [
                        {
                            'title': '国家医保局发布医保支付新规',
                            'source_account': '国家医保局',
                            'summary': '文章重点介绍医保支付改革与执行要求。',
                            'why_it_matters': '值得关注：这会影响医院执行口径、医保支付衔接与后续落地安排。',
                            'link': 'https://mp.weixin.qq.com/s/1',
                        }
                    ],
                }
            },
        }
        markdown = render_brief_markdown(payload)
        self.assertIn('今日总览：政策端重点落在医保支付改革与数据互通，会议端关注报名窗口与议题变化。', markdown)
        self.assertIn('本栏目聚焦医保支付改革与政策落地要求。', markdown)
        self.assertIn('文章重点介绍医保支付改革与执行要求。', markdown)
        self.assertIn('值得关注：这会影响医院执行口径、医保支付衔接与后续落地安排。', markdown)


if __name__ == "__main__":
    unittest.main()
