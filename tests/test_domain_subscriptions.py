import os
import tempfile
import unittest

from wespy.subscriptions import SubscriptionService, SubscriptionStore


class DomainSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "wespy.db")
        self.store = SubscriptionStore(db_path=self.db_path)
        self.service = SubscriptionService(self.store)
        self.account = {
            "fakeid": "fakeid-1",
            "nickname": "CHIMA",
            "alias": "chima1995",
            "avatar": "",
            "signature": "中国医院协会信息专业委员会",
            "service_type": 1,
            "total_count": 0,
            "latest_article_time": 0,
            "completed": 0,
        }
        self.store.upsert_account(self.account)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_create_domain_and_bind_subscription(self):
        domain = self.store.create_domain("医疗信息", description="医疗信息化领域")
        self.store.add_subscription_to_domain(domain["id"], self.account["fakeid"], source_type="manual")

        domains = self.store.list_domains()
        self.assertEqual([item["name"] for item in domains], ["医疗信息"])

        accounts = self.store.list_accounts(domain="医疗信息")
        self.assertEqual([item["nickname"] for item in accounts], ["CHIMA"])
        self.assertEqual(accounts[0]["domain_subscription_enabled"], 1)

    def test_unsubscribe_only_disables_domain_binding(self):
        domain = self.store.create_domain("医疗信息")
        self.store.add_subscription_to_domain(domain["id"], self.account["fakeid"])
        self.store.remove_subscription_from_domain(domain["id"], self.account["fakeid"])

        accounts = self.store.list_accounts(domain="医疗信息")
        self.assertEqual(accounts, [])

        persisted = self.store.get_account("CHIMA")
        self.assertEqual(persisted["nickname"], "CHIMA")

    def test_upsert_article_content_persists_phase1_fields(self):
        self.store.upsert_account(
            {
                **self.account,
                "extraction_profile": "chima",
                "extraction_profile_version": "2026-04-22",
            }
        )

        row = self.store.upsert_article_content(
            "https://mp.weixin.qq.com/s/example",
            self.account["fakeid"],
            title="标题",
            author="作者",
            publish_time_text="2026-04-22",
            fetch_status="normalized",
            cleaned_html="<p>正文</p>",
            cleaned_text="正文",
            html_content="<div>原始正文</div>",
            extraction_profile="chima",
            extraction_profile_version="2026-04-22",
            normalization_notes='{"actions":["lead_trim"]}',
            ocr_applied=1,
            ocr_summary="表格OCR已合并",
        )

        persisted_account = self.store.get_account("CHIMA")
        self.assertEqual(persisted_account["extraction_profile"], "chima")
        self.assertEqual(persisted_account["extraction_profile_version"], "2026-04-22")

        self.assertEqual(row["extraction_profile"], "chima")
        self.assertEqual(row["extraction_profile_version"], "2026-04-22")
        self.assertEqual(row["normalization_notes"], '{"actions":["lead_trim"]}')
        self.assertEqual(row["ocr_applied"], 1)
        self.assertEqual(row["ocr_summary"], "表格OCR已合并")

    def test_ensure_default_domain_is_idempotent(self):
        first = self.service.ensure_default_domain()
        second = self.service.ensure_default_domain()

        self.assertEqual(first["name"], "医疗信息")
        self.assertEqual(second["name"], "医疗信息")
        self.assertEqual(first["id"], second["id"])

        domains = self.store.list_domains()
        self.assertEqual([item["name"] for item in domains], ["医疗信息"])


if __name__ == "__main__":
    unittest.main()
