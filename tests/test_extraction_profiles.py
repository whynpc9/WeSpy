import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from wespy.extraction_profiles import ProfileResolver, load_profiles
from wespy.main import _run_subscription_cli
from wespy.subscriptions import SubscriptionService, SubscriptionStore


class ExtractionProfileTests(unittest.TestCase):
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

    def test_load_profiles_includes_default_and_chima(self):
        profiles = load_profiles()
        self.assertIn("default", profiles)
        self.assertIn("chima", profiles)
        self.assertEqual(profiles["default"]["name"], "default")
        self.assertEqual(profiles["chima"]["name"], "chima")

    def test_resolver_matches_profile_by_account_alias(self):
        resolver = ProfileResolver()
        profile = resolver.resolve_for_account(self.store.get_account("CHIMA"))
        self.assertEqual(profile["name"], "chima")
        self.assertEqual(profile["version"], "2026-04-22")

    def test_service_binding_overrides_auto_match(self):
        self.service.bind_extraction_profile("CHIMA", "default")
        profile = self.service.resolve_extraction_profile(self.store.get_account("CHIMA"))
        self.assertEqual(profile["name"], "default")

        updated = self.store.get_account("CHIMA")
        self.assertEqual(updated["extraction_profile"], "default")
        self.assertEqual(updated["extraction_profile_version"], "2026-04-22")

    def test_unknown_account_falls_back_to_default(self):
        other = {
            "fakeid": "fakeid-2",
            "nickname": "未知公众号",
            "alias": "unknown-account",
            "avatar": "",
            "signature": "",
            "service_type": 1,
            "total_count": 0,
            "latest_article_time": 0,
            "completed": 0,
        }
        self.store.upsert_account(other)
        profile = self.service.resolve_extraction_profile(self.store.get_account("未知公众号"))
        self.assertEqual(profile["name"], "default")

    def test_profile_list_cli_outputs_seed_profiles(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _run_subscription_cli(["--db-path", self.db_path, "profile", "list", "--output-json"])
        payload = json.loads(buf.getvalue())
        names = [item["name"] for item in payload["profiles"]]
        self.assertIn("default", names)
        self.assertIn("chima", names)

    def test_profile_show_cli_resolves_current_account_profile(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _run_subscription_cli(["--db-path", self.db_path, "profile", "show", "CHIMA", "--output-json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["profile"]["name"], "chima")
        self.assertEqual(payload["account"]["nickname"], "CHIMA")

    def test_profile_bind_cli_persists_binding(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _run_subscription_cli(["--db-path", self.db_path, "profile", "bind", "CHIMA", "--profile", "default", "--output-json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["profile"]["name"], "default")

        updated = self.store.get_account("CHIMA")
        self.assertEqual(updated["extraction_profile"], "default")
        self.assertEqual(updated["extraction_profile_version"], "2026-04-22")


if __name__ == "__main__":
    unittest.main()
