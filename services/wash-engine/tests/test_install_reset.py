import os
import unittest
from unittest.mock import MagicMock, patch


os.environ.setdefault("WASH_ENGINE_DEFAULT_OWNER_PASSWORD", "test-owner-password")
os.environ.setdefault("WASH_ENGINE_DEFAULT_ADMIN_PASSWORD", "test-admin-password")

from app.main import reset_local_runtime_data  # noqa: E402


class InstallResetTests(unittest.TestCase):
    def test_reset_can_clear_post_identity(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = None
        context = MagicMock()
        context.__enter__.return_value = connection
        context.__exit__.return_value = False
        license_settings = {
            "enabled": True,
            "gateway_url": "https://gateway.test",
            "site_code": "site-a",
            "site_token": "secret",
            "post_no": 3,
        }
        click_settings = {
            "enabled": True,
            "gateway_url": "https://gateway.test",
            "site_code": "site-a",
            "site_token": "secret",
            "post_no": 3,
        }

        with (
            patch("app.main.get_license_settings", return_value=license_settings),
            patch("app.main.get_click_settings", return_value=click_settings),
            patch("app.main.db", return_value=context),
        ):
            license_result, click_result = reset_local_runtime_data(
                {"login": "admin", "role": "admin"},
                clear_identity=True,
            )

        self.assertFalse(license_result["enabled"])
        self.assertEqual(license_result["site_token"], "")
        self.assertFalse(click_result["enabled"])
        self.assertEqual(click_result["site_code"], "")
        connection.commit.assert_called_once()

    def test_shared_wallet_blocks_destructive_install_reset(self):
        from fastapi import HTTPException
        connection=MagicMock();connection.execute.return_value.fetchone.return_value={'setting_value':{'enabled':True}}
        context=MagicMock();context.__enter__.return_value=connection
        with patch('app.main.db',return_value=context),patch('app.main.get_license_settings',return_value={}),patch('app.main.get_click_settings',return_value={}):
            with self.assertRaises(HTTPException) as error:reset_local_runtime_data({'login':'admin','role':'admin'},clear_identity=True)
        self.assertEqual(error.exception.status_code,409)
        self.assertFalse(any('TRUNCATE' in call.args[0] for call in connection.execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
