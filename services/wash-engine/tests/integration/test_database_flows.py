from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb


os.environ.setdefault("WASH_ENGINE_DEFAULT_OWNER_PASSWORD", "test-owner-password")
os.environ.setdefault("WASH_ENGINE_DEFAULT_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("WASH_ENGINE_JWT_SECRET", "integration-test-jwt-secret")

from app.db import close_pool, db, open_pool  # noqa: E402
from app.main import (  # noqa: E402
    SCHEMA_SQL,
    app,
    apply_click_credit_once,
    apply_offline_commissioning_license,
    evaluate_license_lock,
    read_license_cache,
    seed_user,
)
from app.wash_logic import WashRuntime  # noqa: E402


def encode_offline_code(payload: dict[str, object], site_token: str) -> str:
    raw_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = base64.urlsafe_b64encode(raw_payload).rstrip(b"=").decode("ascii")
    signature = hmac.new(site_token.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()[:18]
    signature_part = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"OL1.{payload_part}.{signature_part}"


class DatabaseFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        open_pool()
        with db() as conn:
            conn.execute(SCHEMA_SQL)
            conn.commit()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        close_pool()

    def setUp(self) -> None:
        with db() as conn:
            table_names = [
                row["tablename"]
                for row in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                ).fetchall()
            ]
            if table_names:
                statement = sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(name) for name in table_names)
                )
                conn.execute(statement)
            conn.commit()
        seed_user("owner", "test-owner-password", "owner", "Test owner")
        seed_user("admin", "test-admin-password", "admin", "Test admin")

    def test_click_credit_is_idempotent_and_restart_closes_session(self) -> None:
        runtime = WashRuntime()
        intent_id = uuid4()
        gateway_id = uuid4()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO click_payment_intents
                  (id, gateway_intent_id, amount_sum, status, raw_payload, paid_at)
                VALUES (%s, %s, 5000, 'paid', %s, now())
                """,
                (intent_id, gateway_id, Jsonb({"status": "paid"})),
            )
            conn.commit()

        import app.main as main_module

        original_runtime = main_module.wash_runtime
        main_module.wash_runtime = runtime
        try:
            apply_click_credit_once(intent_id)
            apply_click_credit_once(intent_id)
        finally:
            main_module.wash_runtime = original_runtime

        self.assertEqual(runtime.state["creditSum"], 5000)
        with db() as conn:
            payment_count = conn.execute(
                "SELECT count(*) AS count FROM payments WHERE idempotency_key = %s",
                (f"click:{gateway_id}",),
            ).fetchone()["count"]
            session = conn.execute("SELECT * FROM wash_sessions").fetchone()
        self.assertEqual(payment_count, 1)
        self.assertEqual(session["paid_sum"], 5000)
        self.assertEqual(session["final_credit_sum"], 5000)

        runtime.state["creditSum"] = 4560
        runtime.state["_creditFloat"] = 4560.0
        runtime._track_usage_locked("water", "active", 2.0, 440.0)
        runtime._flush_usage_locked()

        recovered = WashRuntime()._close_interrupted_sessions_sync()
        self.assertEqual(recovered, 1)
        with db() as conn:
            session = conn.execute("SELECT * FROM wash_sessions").fetchone()
            event = conn.execute(
                "SELECT * FROM system_events WHERE event_type = 'wash_session_power_interrupted'"
            ).fetchone()
        self.assertEqual(session["status"], "ended")
        self.assertEqual(session["close_reason"], "power_interrupted")
        self.assertEqual(session["total_spent_sum"], 440)
        self.assertEqual(session["final_credit_sum"], 4560)
        self.assertIsNotNone(session["finished_at"])
        self.assertIsNotNone(event)

    def test_customer_and_vip_card_cycles(self) -> None:
        runtime = WashRuntime()
        runtime.add_credit(5000, "bill_pulse", raw_payload={"pulse_count": 5})
        runtime._apply_rfid_card_locked("CUSTOMER01", {"seq": 1})
        self.assertEqual(runtime.state["creditSum"], 0)
        with db() as conn:
            card = conn.execute("SELECT * FROM rfid_cards WHERE uid = 'CUSTOMER01'").fetchone()
        self.assertEqual(card["balance_sum"], 5000)

        runtime._apply_rfid_card_locked("CUSTOMER01", {"seq": 2})
        self.assertEqual(runtime.state["creditSum"], 5000)
        with db() as conn:
            card = conn.execute("SELECT * FROM rfid_cards WHERE uid = 'CUSTOMER01'").fetchone()
            reasons = [
                row["reason"]
                for row in conn.execute(
                    "SELECT reason FROM rfid_card_ledger WHERE card_uid = 'CUSTOMER01' ORDER BY id"
                ).fetchall()
            ]
        self.assertEqual(card["balance_sum"], 0)
        self.assertEqual(reasons, ["save_remaining", "use_balance"])

        runtime._burn_remaining_locked("test_customer_session_end")
        with db() as conn:
            profile_id = conn.execute(
                """
                INSERT INTO vip_profiles(code, name, grant_seconds)
                VALUES ('VIP45', 'VIP 45 minutes', 2700)
                RETURNING id
                """
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO rfid_cards(uid, card_type, vip_profile_id)
                VALUES ('VIP01', 'vip', %s)
                """,
                (profile_id,),
            )
            conn.commit()

        runtime._apply_rfid_card_locked("VIP01", {"seq": 3})
        self.assertGreater(runtime.state["creditSum"], 0)
        first_grant = runtime.state["creditSum"]
        runtime._apply_rfid_card_locked("VIP01", {"seq": 4})
        self.assertEqual(runtime.state["creditSum"], 0)
        with db() as conn:
            grants = conn.execute(
                "SELECT count(*) AS count FROM rfid_card_ledger WHERE card_uid = 'VIP01' AND reason = 'vip_grant'"
            ).fetchone()["count"]
        self.assertEqual(grants, 1)
        self.assertGreater(first_grant, 0)

    def test_license_grace_permanent_activation_signature_and_hardware_binding(self) -> None:
        config = {
            "enabled": True,
            "gateway_url": "https://gateway.invalid",
            "site_code": "site-a",
            "site_token": "site-secret",
            "post_no": 1,
            "sync_interval_seconds": 7200,
            "grace_seconds": 604800,
        }
        now = datetime.now(UTC)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO license_cache
                  (id, enabled, locked, state, reason, site_code, post_no,
                   last_success_at, grace_until, last_error)
                VALUES (1, true, false, 'valid', 'license valid', 'site-a', 1,
                        %s, %s, 'gateway unavailable')
                """,
                (now - timedelta(hours=1), now + timedelta(days=6)),
            )
            conn.commit()
        decision = evaluate_license_lock(read_license_cache(), config)
        self.assertFalse(decision["locked"])
        self.assertEqual(decision["state"], "grace")

        with db() as conn:
            conn.execute("UPDATE license_cache SET grace_until = %s WHERE id = 1", (now - timedelta(seconds=1),))
            conn.commit()
        decision = evaluate_license_lock(read_license_cache(), config)
        self.assertTrue(decision["locked"])
        self.assertEqual(decision["state"], "grace_expired")

        hardware = {
            "hardware_fingerprint_hash": "fingerprint-a",
            "wlan0_mac_hash": "mac-a",
            "microsd_cid_hash": "cid-a",
        }
        payload = {
            "v": 1,
            "nonce": "activation-1",
            "action": "activate",
            "site": "site-a",
            "post": 1,
            **hardware,
        }
        code = encode_offline_code(payload, "site-secret")
        with self.assertRaisesRegex(HTTPException, "different hardware"):
            apply_offline_commissioning_license(code, "site-secret", {**hardware, "microsd_cid_hash": "cid-b"})

        applied = apply_offline_commissioning_license(code, "site-secret", hardware)
        self.assertEqual(applied["nonce"], "activation-1")
        with db() as conn:
            license_row = conn.execute("SELECT * FROM license_cache WHERE id = 1").fetchone()
        self.assertTrue(license_row["enabled"])
        self.assertFalse(license_row["locked"])
        self.assertIsNone(license_row["valid_until"])
        self.assertEqual(license_row["reason"], "offline permanent activation")

        bad_code = code[:-1] + ("A" if code[-1] != "A" else "B")
        with self.assertRaisesRegex(HTTPException, "signature"):
            apply_offline_commissioning_license(bad_code, "site-secret", hardware)

    def test_jwt_login_role_authorization_and_logout(self) -> None:
        owner_login = self.client.post(
            "/api/auth/login", json={"login": "owner", "password": "test-owner-password"}
        )
        self.assertEqual(owner_login.status_code, 200)
        self.assertTrue(owner_login.json()["user"]["must_change_password"])
        owner_token = owner_login.json()["access_token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        self.assertEqual(self.client.get("/api/owner/ping", headers=owner_headers).status_code, 428)

        owner_change = self.client.post(
            "/api/auth/account",
            headers=owner_headers,
            json={
                "current_password": "test-owner-password",
                "new_password": "new-owner-password",
            },
        )
        self.assertEqual(owner_change.status_code, 200)
        self.assertFalse(owner_change.json()["user"]["must_change_password"])
        self.assertEqual(self.client.get("/api/auth/me", headers=owner_headers).status_code, 401)
        owner_headers = {"Authorization": f"Bearer {owner_change.json()['access_token']}"}
        self.assertEqual(self.client.get("/api/owner/ping", headers=owner_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/ping", headers=owner_headers).status_code, 403)

        admin_login = self.client.post(
            "/api/auth/login", json={"login": "admin", "password": "test-admin-password"}
        )
        self.assertEqual(admin_login.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
        self.assertEqual(self.client.get("/api/admin/ping", headers=admin_headers).status_code, 428)
        admin_change = self.client.post(
            "/api/auth/account",
            headers=admin_headers,
            json={
                "current_password": "test-admin-password",
                "new_password": "new-admin-password",
            },
        )
        self.assertEqual(admin_change.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {admin_change.json()['access_token']}"}
        self.assertEqual(self.client.get("/api/admin/ping", headers=admin_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/owner/ping", headers=admin_headers).status_code, 200)

        self.assertEqual(self.client.post("/api/auth/logout", headers=owner_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=owner_headers).status_code, 401)

    def test_login_is_locked_after_five_failed_attempts(self) -> None:
        for _ in range(4):
            response = self.client.post(
                "/api/auth/login", json={"login": "owner", "password": "wrong-password"}
            )
            self.assertEqual(response.status_code, 401)
        fifth = self.client.post(
            "/api/auth/login", json={"login": "owner", "password": "wrong-password"}
        )
        self.assertEqual(fifth.status_code, 429)
        blocked_correct_password = self.client.post(
            "/api/auth/login", json={"login": "owner", "password": "test-owner-password"}
        )
        self.assertEqual(blocked_correct_password.status_code, 429)

        with db() as conn:
            conn.execute(
                "UPDATE auth_login_attempts SET locked_until = now() - interval '1 second' WHERE login = 'owner'"
            )
            conn.commit()
        after_expiry = self.client.post(
            "/api/auth/login", json={"login": "owner", "password": "test-owner-password"}
        )
        self.assertEqual(after_expiry.status_code, 200)

    def test_retention_removes_old_ledger_and_keeps_recent_records(self) -> None:
        old_time = datetime.now(UTC) - timedelta(days=91)
        with db() as conn:
            old_session = conn.execute(
                """
                INSERT INTO wash_sessions(started_at, status, source, paid_sum, final_credit_sum)
                VALUES (%s, 'ended', 'cash', 1000, 1000)
                RETURNING id
                """,
                (old_time,),
            ).fetchone()["id"]
            recent_session = conn.execute(
                """
                INSERT INTO wash_sessions(status, source, paid_sum, final_credit_sum)
                VALUES ('ended', 'cash', 2000, 2000)
                RETURNING id
                """
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO payments(wash_session_id, provider, amount_sum, idempotency_key, created_at) VALUES (%s, 'cash', 1000, 'old', %s)",
                (old_session, old_time),
            )
            conn.execute(
                "INSERT INTO payments(wash_session_id, provider, amount_sum, idempotency_key) VALUES (%s, 'cash', 2000, 'recent')",
                (recent_session,),
            )
            conn.execute(
                "INSERT INTO mode_usage(wash_session_id, mode, started_at) VALUES (%s, 'water', %s)",
                (old_session, old_time),
            )
            conn.execute(
                "INSERT INTO system_events(event_type, created_at) VALUES ('old-event', %s), ('recent-event', now())",
                (old_time,),
            )
            conn.commit()

        WashRuntime()._cleanup_retention_sync()
        with db() as conn:
            old_count = conn.execute(
                "SELECT count(*) AS count FROM wash_sessions WHERE id = %s", (old_session,)
            ).fetchone()["count"]
            recent_count = conn.execute(
                "SELECT count(*) AS count FROM wash_sessions WHERE id = %s", (recent_session,)
            ).fetchone()["count"]
            old_event_count = conn.execute(
                "SELECT count(*) AS count FROM system_events WHERE event_type = 'old-event'"
            ).fetchone()["count"]
        self.assertEqual(old_count, 0)
        self.assertEqual(recent_count, 1)
        self.assertEqual(old_event_count, 0)


if __name__ == "__main__":
    unittest.main()
