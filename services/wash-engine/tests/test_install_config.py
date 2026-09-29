import unittest

from app.install_config import clear_post_identity, resolve_site_token


class InstallConfigTests(unittest.TestCase):
    def test_fresh_clone_clears_identity_and_disables_service(self):
        source = {
            "enabled": True,
            "gateway_url": "https://gateway.test",
            "site_code": "site-a",
            "site_token": "secret",
            "post_no": 8,
            "sync_interval_seconds": 7200,
        }

        result = clear_post_identity(source)

        self.assertFalse(result["enabled"])
        self.assertEqual(result["site_code"], "")
        self.assertEqual(result["site_token"], "")
        self.assertEqual(result["post_no"], 1)
        self.assertEqual(result["gateway_url"], "https://gateway.test")
        self.assertEqual(result["sync_interval_seconds"], 7200)

    def test_existing_secret_is_reused_when_form_token_is_blank(self):
        result = resolve_site_token(
            "",
            {"site_token": "existing-license-token"},
            {"site_token": "existing-click-token"},
        )

        self.assertEqual(result, "existing-license-token")

    def test_new_secret_replaces_existing_secret(self):
        result = resolve_site_token(
            "new-token",
            {"site_token": "existing-license-token"},
            {},
        )

        self.assertEqual(result, "new-token")


if __name__ == "__main__":
    unittest.main()
