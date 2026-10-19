import os
import base64
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
from pathlib import Path
import threading
import time as time_module
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb

from .auth import bearer, current_user, public_user, require_role, token_exp_from_payload
from .config import settings
from .commissioning_access import commissioning_access_allowed
from .connectivity import GatewayConnectivity
from .db import close_pool, db, open_pool
from .io_client import io_request
from .install_config import clear_post_identity, resolve_site_token
from .kiosk_defaults import normalize_kiosk_settings
from .reporting import reconcile_session_credit
from .schema import (
    AccountUpdateRequest,
    ClickIntentRequest,
    ClickSettingsRequest,
    CommissioningClaimRequest,
    CommissioningCompleteRequest,
    CommissioningOfflineRequest,
    InstallApplyRequest,
    KioskSettingsRequest,
    LicenseSettingsRequest,
    LoginRequest,
    LoginResponse,
    OfflineLicenseCodeRequest,
    RfidCardRequest,
    UserResponse,
    VipProfilesRequest,
    WashCreditRequest,
    WashModeRequest,
    WashParametersRequest,
    WashSimPulsesRequest,
    WashSimRfidRequest,
    WashSimLicenseRequest,
    WashSimTotalStopRequest,
)
from .security import create_access_token, decode_access_token, hash_password, verify_password
from .wash_logic import wash_runtime


app = FastAPI(title="RTU WASH Engine", version="0.1.0")
REPORT_TIMEZONE = ZoneInfo("Asia/Tashkent")
license_stop_event = threading.Event()
license_thread: threading.Thread | None = None
connectivity_stop_event = threading.Event()
connectivity_thread: threading.Thread | None = None
gateway_connectivity = GatewayConnectivity(offline_threshold=3, online_threshold=2)
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
COMPACT_CODE_LENGTH = 20
COMPACT_CODE_MAX_AGE_DAYS = 7
COMPACT_CODE_EPOCH = date(2020, 1, 1)
COMPACT_ACTIONS = {
    0: ("extend", 1, "time_limited", "online"),
    1: ("extend", 3, "time_limited", "online"),
    2: ("extend", 7, "time_limited", "online"),
    3: ("extend", 30, "time_limited", "online"),
    4: ("activate", 0, "permanent", "offline_cash_only"),
    5: ("disable_enforcement", 0, "permanent", "online"),
    6: ("activate", 0, "permanent", "online"),
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ASSET_ROOT = Path(settings.kiosk_assets_dir)
ASSET_LIMITS = {
    "icon": 300 * 1024,
    "logo": 2 * 1024 * 1024,
    "background": 3 * 1024 * 1024,
}
ASSET_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

ASSET_ROOT.mkdir(parents=True, exist_ok=True)
for asset_kind in ASSET_LIMITS:
    (ASSET_ROOT / asset_kind).mkdir(parents=True, exist_ok=True)
app.mount("/assets/kiosk", StaticFiles(directory=str(ASSET_ROOT)), name="kiosk-assets")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_settings (
  setting_key TEXT PRIMARY KEY,
  setting_value JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_users (
  id BIGSERIAL PRIMARY KEY,
  login TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'admin')),
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
  auth_version INTEGER NOT NULL DEFAULT 1,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE auth_users
ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE auth_users
ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS auth_login_attempts (
  login TEXT PRIMARY KEY,
  failure_count INTEGER NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_revoked_tokens (
  jti TEXT PRIMARY KEY,
  user_id BIGINT REFERENCES auth_users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS settings_history (
  id BIGSERIAL PRIMARY KEY,
  setting_key TEXT NOT NULL,
  old_value JSONB,
  new_value JSONB NOT NULL,
  changed_by_user_id BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
  changed_by_login TEXT,
  change_reason TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS settings_history_key_created_idx
ON settings_history (setting_key, created_at DESC);

CREATE TABLE IF NOT EXISTS vip_profiles (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  grant_seconds INTEGER NOT NULL CHECK (grant_seconds >= 0),
  max_uses_per_day INTEGER,
  valid_from TIMESTAMPTZ,
  valid_until TIMESTAMPTZ,
  allowed_modes JSONB NOT NULL DEFAULT '[]'::jsonb,
  owner_notes TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS vip_profiles_enabled_idx
ON vip_profiles (enabled, code);

CREATE TABLE IF NOT EXISTS rfid_cards (
  uid TEXT PRIMARY KEY,
  card_type TEXT NOT NULL DEFAULT 'customer',
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'blocked', 'lost', 'expired')),
  enabled BOOLEAN NOT NULL DEFAULT true,
  display_name TEXT NOT NULL DEFAULT '',
  balance_sum BIGINT NOT NULL DEFAULT 0 CHECK (balance_sum >= 0),
  vip_profile_id BIGINT REFERENCES vip_profiles(id) ON DELETE SET NULL,
  expires_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE rfid_cards ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE rfid_cards ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '';
ALTER TABLE rfid_cards ADD COLUMN IF NOT EXISTS vip_profile_id BIGINT REFERENCES vip_profiles(id) ON DELETE SET NULL;
ALTER TABLE rfid_cards ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE rfid_cards ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS rfid_cards_type_status_idx
ON rfid_cards (card_type, status, enabled);

CREATE INDEX IF NOT EXISTS rfid_cards_vip_profile_idx
ON rfid_cards (vip_profile_id);

CREATE TABLE IF NOT EXISTS wash_sessions (
  id BIGSERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'running', 'closed', 'cancelled', 'error')),
  source TEXT NOT NULL DEFAULT 'unknown'
    CHECK (source IN ('unknown', 'cash', 'click', 'card', 'vip', 'mixed', 'admin')),
  card_uid TEXT REFERENCES rfid_cards(uid) ON DELETE SET NULL,
  initial_credit_sum BIGINT NOT NULL DEFAULT 0 CHECK (initial_credit_sum >= 0),
  paid_sum BIGINT NOT NULL DEFAULT 0 CHECK (paid_sum >= 0),
  final_credit_sum BIGINT NOT NULL DEFAULT 0 CHECK (final_credit_sum >= 0),
  total_spent_sum BIGINT NOT NULL DEFAULT 0 CHECK (total_spent_sum >= 0),
  close_reason TEXT NOT NULL DEFAULT '',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS card_uid TEXT REFERENCES rfid_cards(uid) ON DELETE SET NULL;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS initial_credit_sum BIGINT NOT NULL DEFAULT 0;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS paid_sum BIGINT NOT NULL DEFAULT 0;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS final_credit_sum BIGINT NOT NULL DEFAULT 0;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS total_spent_sum BIGINT NOT NULL DEFAULT 0;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS close_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS runtime_seen_at TIMESTAMPTZ;

UPDATE wash_sessions
SET runtime_seen_at = COALESCE(runtime_seen_at, started_at)
WHERE runtime_seen_at IS NULL;

DO $$
BEGIN
  ALTER TABLE wash_sessions DROP CONSTRAINT IF EXISTS wash_sessions_status_check;
  ALTER TABLE wash_sessions ADD CONSTRAINT wash_sessions_status_check
    CHECK (status IN ('started', 'running', 'ended', 'cancelled', 'error', 'open', 'closed'));
END $$;

CREATE INDEX IF NOT EXISTS wash_sessions_started_idx
ON wash_sessions (started_at DESC);

CREATE INDEX IF NOT EXISTS wash_sessions_status_started_idx
ON wash_sessions (status, started_at DESC);

CREATE INDEX IF NOT EXISTS wash_sessions_card_started_idx
ON wash_sessions (card_uid, started_at DESC);

CREATE INDEX IF NOT EXISTS wash_sessions_runtime_seen_idx
ON wash_sessions (runtime_seen_at DESC);


CREATE TABLE IF NOT EXISTS recovery_credits (
  id BIGSERIAL PRIMARY KEY,
  wash_session_id BIGINT NOT NULL UNIQUE
    REFERENCES wash_sessions(id) ON DELETE CASCADE,
  amount_sum BIGINT NOT NULL CHECK (amount_sum >= 0),
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unclaimed'
    CHECK (status IN ('unclaimed', 'claimed', 'cancelled')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS recovery_credits_status_created_idx
ON recovery_credits (status, created_at DESC);

CREATE TABLE IF NOT EXISTS payments (
  id BIGSERIAL PRIMARY KEY,
  wash_session_id BIGINT REFERENCES wash_sessions(id) ON DELETE SET NULL,
  provider TEXT NOT NULL
    CHECK (provider IN ('cash', 'click', 'card', 'vip', 'admin', 'manual')),
  status TEXT NOT NULL DEFAULT 'paid'
    CHECK (status IN ('pending', 'paid', 'credited', 'cancelled', 'error')),
  amount_sum BIGINT NOT NULL DEFAULT 0 CHECK (amount_sum >= 0),
  external_id TEXT,
  idempotency_key TEXT UNIQUE,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  credited_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS payments_provider_created_idx
ON payments (provider, created_at DESC);

CREATE INDEX IF NOT EXISTS payments_session_idx
ON payments (wash_session_id);

CREATE TABLE IF NOT EXISTS cash_events (
  id BIGSERIAL PRIMARY KEY,
  wash_session_id BIGINT REFERENCES wash_sessions(id) ON DELETE SET NULL,
  source_input TEXT NOT NULL CHECK (source_input IN ('bill_pulse', 'coin_pulse')),
  pulse_count INTEGER NOT NULL CHECK (pulse_count > 0),
  amount_sum BIGINT NOT NULL CHECK (amount_sum >= 0),
  sum_per_pulse BIGINT NOT NULL CHECK (sum_per_pulse >= 0),
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cash_events_created_idx
ON cash_events (created_at DESC);

CREATE INDEX IF NOT EXISTS cash_events_session_idx
ON cash_events (wash_session_id);

CREATE TABLE IF NOT EXISTS mode_usage (
  id BIGSERIAL PRIMARY KEY,
  wash_session_id BIGINT REFERENCES wash_sessions(id) ON DELETE CASCADE,
  mode TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ,
  duration_ms BIGINT NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  spent_sum BIGINT NOT NULL DEFAULT 0 CHECK (spent_sum >= 0),
  pause_ms BIGINT NOT NULL DEFAULT 0 CHECK (pause_ms >= 0),
  total_stop_wait_ms BIGINT NOT NULL DEFAULT 0 CHECK (total_stop_wait_ms >= 0),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS mode_usage_session_started_idx
ON mode_usage (wash_session_id, started_at);

CREATE INDEX IF NOT EXISTS mode_usage_mode_started_idx
ON mode_usage (mode, started_at DESC);

-- Repair sessions written by versions that truncated every fractional ledger
-- flush. Credit-empty sessions must account for the full credited amount.
WITH ledger_corrections AS (
  SELECT ws.id AS session_id,
         ws.paid_sum - ws.total_spent_sum AS missing_sum,
         (
           SELECT mu.id
           FROM mode_usage AS mu
           WHERE mu.wash_session_id = ws.id
           ORDER BY mu.started_at DESC, mu.id DESC
           LIMIT 1
         ) AS mode_usage_id
  FROM wash_sessions AS ws
  WHERE ws.status = 'ended'
    AND ws.close_reason = 'credit_empty'
    AND ws.final_credit_sum = 0
    AND ws.paid_sum > ws.total_spent_sum
), corrected_usage AS (
  UPDATE mode_usage AS mu
  SET spent_sum = mu.spent_sum + correction.missing_sum
  FROM ledger_corrections AS correction
  WHERE mu.id = correction.mode_usage_id
  RETURNING correction.session_id
)
UPDATE wash_sessions AS ws
SET total_spent_sum = ws.paid_sum
WHERE ws.id IN (SELECT session_id FROM corrected_usage);

CREATE TABLE IF NOT EXISTS rfid_card_ledger (
  id BIGSERIAL PRIMARY KEY,
  card_uid TEXT NOT NULL REFERENCES rfid_cards(uid) ON DELETE CASCADE,
  wash_session_id BIGINT REFERENCES wash_sessions(id) ON DELETE SET NULL,
  direction TEXT NOT NULL CHECK (direction IN ('credit', 'debit', 'grant', 'reversal')),
  reason TEXT NOT NULL
    CHECK (reason IN ('save_remaining', 'use_balance', 'admin_adjustment', 'vip_grant', 'payment_reversal')),
  amount_sum BIGINT NOT NULL DEFAULT 0 CHECK (amount_sum >= 0),
  duration_seconds INTEGER NOT NULL DEFAULT 0 CHECK (duration_seconds >= 0),
  balance_after_sum BIGINT,
  created_by_user_id BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rfid_card_ledger_card_created_idx
ON rfid_card_ledger (card_uid, created_at DESC);

CREATE INDEX IF NOT EXISTS rfid_card_ledger_session_idx
ON rfid_card_ledger (wash_session_id);

CREATE TABLE IF NOT EXISTS click_payment_intents (
  id UUID PRIMARY KEY,
  gateway_intent_id UUID UNIQUE,
  gateway_merchant_trans_id TEXT UNIQUE,
  amount_sum BIGINT NOT NULL CHECK (amount_sum > 0),
  status TEXT NOT NULL DEFAULT 'local_pending'
    CHECK (status IN ('local_pending', 'pending', 'prepared', 'paid', 'credited', 'cancelled', 'expired', 'error')),
  payment_url TEXT NOT NULL DEFAULT '',
  gateway_status TEXT NOT NULL DEFAULT '',
  last_error TEXT NOT NULL DEFAULT '',
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  paid_at TIMESTAMPTZ,
  credited_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS click_payment_intents_status_created_idx
ON click_payment_intents (status, created_at DESC);

CREATE INDEX IF NOT EXISTS click_payment_intents_updated_idx
ON click_payment_intents (updated_at DESC);

CREATE TABLE IF NOT EXISTS license_cache (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  enabled BOOLEAN NOT NULL DEFAULT false,
  locked BOOLEAN NOT NULL DEFAULT false,
  state TEXT NOT NULL DEFAULT 'not_configured',
  reason TEXT NOT NULL DEFAULT 'not_configured',
  site_code TEXT NOT NULL DEFAULT '',
  post_no INTEGER NOT NULL DEFAULT 1,
  machine_id BIGINT,
  valid_until TIMESTAMPTZ,
  days_left INTEGER,
  last_success_at TIMESTAMPTZ,
  last_attempt_at TIMESTAMPTZ,
  next_sync_at TIMESTAMPTZ,
  grace_until TIMESTAMPTZ,
  last_error TEXT NOT NULL DEFAULT '',
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS offline_license_codes (
  nonce TEXT PRIMARY KEY,
  code_sha256 TEXT NOT NULL,
  action TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  gateway_ack_status TEXT NOT NULL DEFAULT 'pending',
  gateway_ack_error TEXT NOT NULL DEFAULT '',
  gateway_ack_attempted_at TIMESTAMPTZ,
  gateway_acked_at TIMESTAMPTZ,
  applied_by_user_id BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
  applied_by_login TEXT,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE offline_license_codes ADD COLUMN IF NOT EXISTS gateway_ack_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE offline_license_codes ADD COLUMN IF NOT EXISTS gateway_ack_error TEXT NOT NULL DEFAULT '';
ALTER TABLE offline_license_codes ADD COLUMN IF NOT EXISTS gateway_ack_attempted_at TIMESTAMPTZ;
ALTER TABLE offline_license_codes ADD COLUMN IF NOT EXISTS gateway_acked_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS offline_license_attempt_state (
  id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  failed_count INTEGER NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system_events (
  id BIGSERIAL PRIMARY KEY,
  level TEXT NOT NULL DEFAULT 'info'
    CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical')),
  event_type TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'wash-engine',
  message TEXT NOT NULL DEFAULT '',
  context JSONB NOT NULL DEFAULT '{}'::jsonb,
  wash_session_id BIGINT REFERENCES wash_sessions(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS system_events_created_idx
ON system_events (created_at DESC);

CREATE INDEX IF NOT EXISTS system_events_type_created_idx
ON system_events (event_type, created_at DESC);
"""


from .financial_ids import FINANCIAL_IDS_SQL
from .bonus import BONUS_SCHEMA_SQL
from .vip_migration import VIP_IMPORT_SCHEMA_SQL
SCHEMA_SQL += VIP_IMPORT_SCHEMA_SQL
SCHEMA_SQL += BONUS_SCHEMA_SQL
SCHEMA_SQL += FINANCIAL_IDS_SQL
from .local_balance_import import IMPORT_SCHEMA_SQL
SCHEMA_SQL += IMPORT_SCHEMA_SQL

def seed_user(login: str, password: str, role: str, display_name: str) -> None:
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM auth_users WHERE role = %s LIMIT 1",
            (role,),
        ).fetchone()
        if existing:
            return

        conn.execute(
            """
            INSERT INTO auth_users (
              login, role, display_name, password_hash, must_change_password
            )
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (login) DO NOTHING
            """,
            (login, role, display_name, hash_password(password)),
        )
        conn.commit()


def default_license_settings() -> dict[str, object]:
    return {
        "enabled": settings.license_enabled,
        "gateway_url": settings.license_gateway_url or settings.click_gateway_url,
        "site_code": settings.license_site_code or settings.click_site_code,
        "site_token": settings.license_site_token or settings.click_site_token,
        "post_no": settings.license_post_no or settings.click_post_no,
        "sync_interval_seconds": settings.license_sync_interval_seconds,
        "grace_seconds": settings.license_grace_seconds,
    }


def normalize_license_settings(value: dict | None, include_secret: bool = True) -> dict[str, object]:
    config = default_license_settings()
    if isinstance(value, dict):
        config.update({key: value[key] for key in config if key in value})
    config["enabled"] = bool(config.get("enabled"))
    config["gateway_url"] = str(config.get("gateway_url") or "").strip().rstrip("/")
    config["site_code"] = str(config.get("site_code") or "").strip()
    config["site_token"] = str(config.get("site_token") or "").strip()
    config["post_no"] = max(1, int(config.get("post_no") or 1))
    config["sync_interval_seconds"] = max(300, int(config.get("sync_interval_seconds") or 43_200))
    config["grace_seconds"] = max(0, int(config.get("grace_seconds") or 604_800))
    if not include_secret:
        token = str(config.get("site_token") or "")
        config["site_token_configured"] = bool(token)
        config["site_token"] = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else ("configured" if token else "")
    return config


def get_license_settings(include_secret: bool = True) -> dict[str, object]:
    with db() as conn:
        row = conn.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'license_settings'").fetchone()
    return normalize_license_settings(row["setting_value"] if row else None, include_secret=include_secret)


def read_first_text_file(paths: list[str]) -> str:
    for path in paths:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def scoped_hardware_hash(config: dict[str, object], kind: str, value: str) -> str:
    site_code = str(config.get("site_code") or "").strip()
    post_no = int(config.get("post_no") or 1)
    normalized = value.strip().lower()
    return hashlib.sha256(f"{site_code}:{post_no}:{kind}:{normalized}".encode("utf-8")).hexdigest()


def read_microsd_cid(sys_roots: list[Path] | None = None) -> str:
    roots = sys_roots or [Path("/host-sys/block"), Path("/sys/block")]
    candidates: list[str] = []
    for root in roots:
        # Board kernels do not assign a stable mmcblk number: Orange Pi uses
        # mmcblk1 here, while Radxa and other images may expose mmcblk0/2.
        candidates.extend(str(path) for path in sorted(root.glob("mmcblk*/device/cid")))
    return read_first_text_file(candidates).lower()


def get_hardware_identity(config: dict[str, object] | None = None) -> dict[str, object]:
    config = config or get_license_settings(include_secret=False)
    wlan0_mac = read_first_text_file([
        "/host-sys/class/net/wlan0/address",
        "/sys/class/net/wlan0/address",
    ]).lower().replace(":", "")
    microsd_cid = read_microsd_cid()
    complete = bool(wlan0_mac and microsd_cid)
    identity: dict[str, object] = {
        "complete": complete,
        "wlan0_mac_present": bool(wlan0_mac),
        "microsd_cid_present": bool(microsd_cid),
        "wlan0_mac_tail": wlan0_mac[-6:] if wlan0_mac else "",
        "microsd_cid_tail": microsd_cid[-8:] if microsd_cid else "",
        "hardware_fingerprint_hash": "",
        "wlan0_mac_hash": "",
        "microsd_cid_hash": "",
    }
    if wlan0_mac:
        identity["wlan0_mac_hash"] = scoped_hardware_hash(config, "wlan0_mac", wlan0_mac)
    if microsd_cid:
        identity["microsd_cid_hash"] = scoped_hardware_hash(config, "microsd_cid", microsd_cid)
    if complete:
        fingerprint_seed = f"{wlan0_mac}:{microsd_cid}"
        identity["hardware_fingerprint_hash"] = scoped_hardware_hash(config, "hardware_fingerprint", fingerprint_seed)
    return identity


def get_host_network_summary() -> dict[str, object]:
    net_root = Path("/host-sys/class/net")
    if not net_root.exists():
        net_root = Path("/sys/class/net")
    interfaces: list[dict[str, object]] = []
    for path in sorted(net_root.glob("*")):
        name = path.name
        if name == "lo" or name.startswith(("docker", "br-", "veth")):
            continue
        address = read_first_text_file([str(path / "address")]).lower()
        interfaces.append(
            {
                "name": name,
                "mac_tail": address.replace(":", "")[-6:] if address else "",
                "operstate": read_first_text_file([str(path / "operstate")]) or "unknown",
            }
        )
    return {
        "hostname": read_first_text_file(["/host-etc/hostname", "/host-sys/kernel/hostname", "/proc/sys/kernel/hostname"]),
        "interfaces": interfaces,
    }


def hardware_sync_payload(config: dict[str, object]) -> dict[str, str]:
    identity = get_hardware_identity(config)
    if not identity.get("complete"):
        return {}
    return {
        "hardware_fingerprint_hash": str(identity["hardware_fingerprint_hash"]),
        "wlan0_mac_hash": str(identity["wlan0_mac_hash"]),
        "microsd_cid_hash": str(identity["microsd_cid_hash"]),
    }


def get_commissioning_state() -> dict[str, object]:
    with db() as conn:
        row = conn.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = 'commissioning_state'"
        ).fetchone()
    if row:
        value = dict(row["setting_value"] or {})
        return {
            "complete": bool(value.get("complete")),
            "completed_at": value.get("completed_at"),
        }
    license_config = get_license_settings()
    inferred = bool(license_config.get("site_code") and license_config.get("site_token"))
    return {"complete": inferred, "completed_at": None}


def protect_shared_wallet_identity(next_config):
    if not wash_runtime.shared_wallet_enabled:
        return
    current=get_license_settings()
    if any(next_config.get(key)!=current.get(key) for key in ('site_code','post_no','site_token')):
        raise HTTPException(409,'Мойку, номер поста и ключ установленного кошелька нельзя менять без финансовой сверки')


def save_commissioning_config(
    site_code: str,
    post_no: int,
    gateway_url: str,
    site_token: str,
    click_enabled: bool,
) -> None:
    protect_shared_wallet_identity({'site_code':site_code,'post_no':post_no,'site_token':site_token})
    license_config = normalize_license_settings(
        {
            "enabled": True,
            "gateway_url": gateway_url.rstrip("/"),
            "site_code": site_code,
            "site_token": site_token,
            "post_no": post_no,
            "sync_interval_seconds": 7200,
            "grace_seconds": 604800,
        }
    )
    click_config = normalize_click_settings(
        {
            "enabled": click_enabled,
            "gateway_url": gateway_url.rstrip("/"),
            "site_code": site_code,
            "site_token": site_token,
            "post_no": post_no,
            "min_amount_sum": 1000,
            "max_amount_sum": 10_000_000,
        }
    )
    with db() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(setting_key, setting_value, updated_at)
            VALUES
              ('license_settings', %s, now()),
              ('click_settings', %s, now()),
              ('commissioning_state', '{"complete": false}'::jsonb, now())
            ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value, updated_at = now()
            """,
            (Jsonb(license_config), Jsonb(click_config)),
        )
        conn.commit()


def apply_offline_commissioning_license(code: str, site_token: str, hardware: dict[str, object]) -> dict[str, object]:
    payload = verify_offline_license_code(code, site_token)
    if payload.get("action") != "activate":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Commissioning response is not an activation")
    for key in ("hardware_fingerprint_hash", "wlan0_mac_hash", "microsd_cid_hash"):
        if payload.get(key) != hardware.get(key):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Commissioning response is for different hardware")
    nonce = str(payload["nonce"])
    code_hash = offline_code_sha256(code)
    with db() as conn:
        if conn.execute("SELECT 1 FROM offline_license_codes WHERE nonce = %s", (nonce,)).fetchone():
            raise HTTPException(status.HTTP_409_CONFLICT, "Commissioning response was already used")
        conn.execute(
            """
            INSERT INTO license_cache(
              id, enabled, locked, state, reason, site_code, post_no,
              valid_until, days_left, grace_until, raw_payload, updated_at
            ) VALUES (1, true, false, 'valid', 'offline permanent activation', %s, %s,
                      NULL, NULL, NULL, %s, now())
            ON CONFLICT (id) DO UPDATE SET
              enabled = true, locked = false, state = 'valid',
              reason = 'offline permanent activation', site_code = EXCLUDED.site_code,
              post_no = EXCLUDED.post_no, valid_until = NULL, days_left = NULL,
              grace_until = NULL, raw_payload = EXCLUDED.raw_payload, updated_at = now()
            """,
            (payload["site"], int(payload["post"]), Jsonb(payload)),
        )
        conn.execute(
            """
            INSERT INTO offline_license_codes(
              nonce, code_sha256, action, payload, applied_by_login, gateway_ack_status
            ) VALUES (%s, %s, 'activate', %s, 'commissioning', 'pending')
            """,
            (nonce, code_hash, Jsonb(payload)),
        )
        conn.commit()
    return payload


def verify_commissioning_response_signature(response: dict[str, object]) -> None:
    encoded_key = settings.commissioning_signing_public_key.strip()
    signature_text = str(response.get("signature") or "")
    if not encoded_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Commissioning public key is not configured")
    if not signature_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Commissioning response signature is missing")
    unsigned = {key: value for key, value in response.items() if key != "signature"}
    canonical = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode("utf-8")
    try:
        raw_key = b64url_decode(encoded_key)
        signature = b64url_decode(signature_text)
        Ed25519PublicKey.from_public_bytes(raw_key).verify(signature, canonical)
    except (ValueError, InvalidSignature) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid commissioning response signature") from exc


def parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def normalize_compact_offline_code(code: str) -> str:
    compact = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    compact = compact.replace("O", "0").replace("I", "1").replace("L", "1")
    if len(compact) != COMPACT_CODE_LENGTH or any(ch not in CROCKFORD_ALPHABET for ch in compact):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Offline code must contain 20 symbols")
    return compact


def canonical_offline_code(code: str) -> str:
    compact = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    if len(compact) == COMPACT_CODE_LENGTH:
        return normalize_compact_offline_code(code)
    return "".join(str(code or "").strip().split())


def offline_code_sha256(code: str) -> str:
    return hashlib.sha256(canonical_offline_code(code).encode("ascii")).hexdigest()


def _compact_code_message(
    metadata: int,
    site_code: str,
    post_no: int,
    hardware: dict[str, object],
) -> bytes:
    identity = "|".join(
        [
            "OC1",
            f"{metadata:09x}",
            site_code,
            str(post_no),
            str(hardware.get("hardware_fingerprint_hash") or ""),
            str(hardware.get("wlan0_mac_hash") or ""),
            str(hardware.get("microsd_cid_hash") or ""),
        ]
    )
    return identity.encode("utf-8")


def decode_compact_offline_code(
    code: str,
    site_token: str,
    site_code: str,
    post_no: int,
    hardware: dict[str, object],
) -> dict[str, object]:
    encoded = 0
    for char in normalize_compact_offline_code(code):
        encoded = (encoded << 5) | CROCKFORD_ALPHABET.index(char)
    metadata = encoded >> 65
    provided_mac = encoded & ((1 << 65) - 1)
    action_id = (metadata >> 30) & 0x7
    issue_day = (metadata >> 15) & 0x7FFF
    nonce_value = metadata & 0x7FFF
    if action_id not in COMPACT_ACTIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported offline code action")
    current_day = (datetime.now(UTC).date() - COMPACT_CODE_EPOCH).days
    if issue_day > current_day + 1 or current_day - issue_day > COMPACT_CODE_MAX_AGE_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Offline code has expired")
    expected_digest = hmac.new(
        site_token.encode("utf-8"),
        _compact_code_message(metadata, site_code, post_no, hardware),
        hashlib.sha256,
    ).digest()
    expected_mac = int.from_bytes(expected_digest[:9], "big") >> 7
    if not hmac.compare_digest(provided_mac.to_bytes(9, "big"), expected_mac.to_bytes(9, "big")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid offline code")
    action, days, duration_type, operation_mode = COMPACT_ACTIONS[action_id]
    return {
        "v": 2,
        "site": site_code,
        "post": post_no,
        "action": action,
        "days": days,
        "operation_mode": operation_mode,
        "license_duration_type": duration_type,
        "issued_day": issue_day,
        "nonce": f"OC1-{action_id}-{issue_day:04x}-{nonce_value:04x}",
        "hardware_fingerprint_hash": hardware.get("hardware_fingerprint_hash"),
        "wlan0_mac_hash": hardware.get("wlan0_mac_hash"),
        "microsd_cid_hash": hardware.get("microsd_cid_hash"),
    }


def verify_offline_license_code(
    code: str,
    site_token: str,
    site_code: str = "",
    post_no: int = 0,
    hardware: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized = "".join(str(code or "").strip().split())
    compact = "".join(ch for ch in normalized.upper() if ch.isalnum())
    if len(compact) == COMPACT_CODE_LENGTH and "." not in normalized:
        if not site_code or post_no < 1 or not hardware:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Compact offline code requires registered post identity")
        return decode_compact_offline_code(code, site_token, site_code, post_no, hardware)
    parts = normalized.split(".")
    if len(parts) != 3 or parts[0] != "OL1":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid offline code format")
    payload_part, signature_part = parts[1], parts[2]
    expected = hmac.new(site_token.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()[:18]
    try:
        provided = b64url_decode(signature_part)
        payload = json.loads(b64url_decode(payload_part).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid offline code payload") from exc
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid offline code signature")
    if payload.get("v") != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported offline code version")
    if not payload.get("nonce"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Offline code nonce is missing")
    return payload


def ensure_offline_code_attempt_allowed() -> None:
    now = datetime.now(UTC)
    with db() as conn:
        row = conn.execute(
            "SELECT failed_count, locked_until FROM offline_license_attempt_state WHERE id = 1",
        ).fetchone()
    if row and row.get("locked_until") and row["locked_until"] > now:
        seconds = max(1, int((row["locked_until"] - now).total_seconds()))
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many invalid codes. Try again in {seconds} seconds")


def record_offline_code_failure() -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO offline_license_attempt_state(id, failed_count, locked_until, updated_at)
            VALUES (1, 1, NULL, now())
            ON CONFLICT (id) DO UPDATE
            SET failed_count = CASE
                  WHEN offline_license_attempt_state.locked_until IS NOT NULL
                   AND offline_license_attempt_state.locked_until <= now() THEN 1
                  ELSE offline_license_attempt_state.failed_count + 1
                END,
                locked_until = CASE
                  WHEN (
                    CASE
                      WHEN offline_license_attempt_state.locked_until IS NOT NULL
                       AND offline_license_attempt_state.locked_until <= now() THEN 1
                      ELSE offline_license_attempt_state.failed_count + 1
                    END
                  ) >= 5 THEN now() + interval '15 minutes'
                  ELSE NULL
                END,
                updated_at = now()
            """,
        )
        conn.commit()


def reset_offline_code_failures() -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO offline_license_attempt_state(id, failed_count, locked_until, updated_at)
            VALUES (1, 0, NULL, now())
            ON CONFLICT (id) DO UPDATE
            SET failed_count = 0, locked_until = NULL, updated_at = now()
            """,
        )
        conn.commit()


def verify_offline_code_for_post(
    code: str,
    site_token: str,
    config: dict[str, object],
) -> dict[str, object]:
    ensure_offline_code_attempt_allowed()
    compact = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    if len(compact) != COMPACT_CODE_LENGTH or "." in str(code or ""):
        record_offline_code_failure()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Offline emergency code must contain 20 symbols")
    expected_site = str(config.get("site_code") or "")
    expected_post = int(config.get("post_no") or 1)
    try:
        payload = verify_offline_license_code(
            code,
            site_token,
            expected_site,
            expected_post,
            get_hardware_identity(config),
        )
        if payload.get("site") != expected_site or int(payload.get("post") or 0) != expected_post:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Offline code is for another site or post")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            record_offline_code_failure()
        raise
    reset_offline_code_failures()
    return payload


class PermanentGatewayAckError(RuntimeError):
    pass


async def acknowledge_offline_license_code_to_gateway(
    config: dict[str, object],
    nonce: str,
    action: str,
    code_hash: str,
    code_payload: dict[str, object],
) -> dict[str, object]:
    missing = [key for key in ("gateway_url", "site_code", "site_token", "post_no") if not config.get(key)]
    if missing:
        raise RuntimeError(f"license settings incomplete: {', '.join(missing)}")
    request_payload = {
        "site_code": config["site_code"],
        "post_no": config["post_no"],
        "action": action,
        "nonce": nonce,
        "code_sha256": code_hash,
        "payload": code_payload,
    }
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.post(
            f"{config['gateway_url']}/api/v1/license/offline-code/applied",
            json=request_payload,
            headers={"X-Site-Token": str(config["site_token"])},
        )
    if 400 <= response.status_code < 500:
        raise PermanentGatewayAckError(response.text[:300])
    if response.status_code >= 500:
        raise RuntimeError(response.text[:300])
    return response.json()


async def sync_pending_offline_license_codes(config: dict[str, object]) -> None:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT nonce, code_sha256, action, payload
            FROM offline_license_codes
            WHERE gateway_ack_status IN ('pending', 'failed')
            ORDER BY applied_at ASC
            LIMIT 10
            """
        ).fetchall()
    for row in rows:
        try:
            await acknowledge_offline_license_code_to_gateway(
                config,
                str(row["nonce"]),
                str(row["action"]),
                str(row["code_sha256"]),
                dict(row["payload"] or {}),
            )
        except Exception as exc:
            ack_status = "rejected" if isinstance(exc, PermanentGatewayAckError) else "failed"
            with db() as conn:
                conn.execute(
                    """
                    UPDATE offline_license_codes
                    SET gateway_ack_status = %s,
                        gateway_ack_error = %s,
                        gateway_ack_attempted_at = now()
                    WHERE nonce = %s
                    """,
                    (ack_status, str(exc)[:300], row["nonce"]),
                )
                conn.commit()
            continue
        with db() as conn:
            conn.execute(
                """
                UPDATE offline_license_codes
                SET gateway_ack_status = 'acked',
                    gateway_ack_error = '',
                    gateway_ack_attempted_at = now(),
                    gateway_acked_at = now()
                WHERE nonce = %s
                """,
                (row["nonce"],),
            )
            conn.commit()


def public_license_row(row: dict | None, config: dict[str, object] | None = None) -> dict[str, object]:
    config = config or get_license_settings(include_secret=False)
    raw_payload = dict(row.get("raw_payload") or {}) if row else {}
    if not config.get("enabled"):
        return {
            "enabled": False,
            "locked": False,
            "state": "enforcement_disabled",
            "reason": "license enforcement disabled",
            "site_code": config.get("site_code") or "",
            "post_no": config.get("post_no") or 1,
            "last_success_at": None,
            "last_attempt_at": None,
            "next_sync_at": None,
            "grace_until": None,
            "valid_until": None,
            "days_left": None,
            "last_error": "",
            "operation_mode": raw_payload.get("operation_mode") or "",
            "license_duration_type": raw_payload.get("license_duration_type") or "",
            "activation_status": raw_payload.get("activation_status") or "",
            "hardware_bound": bool(raw_payload.get("hardware_bound")),
        }
    if not row:
        return {
            "enabled": True,
            "locked": True,
            "state": "not_synced",
            "reason": "license has not synced yet",
            "site_code": config.get("site_code") or "",
            "post_no": config.get("post_no") or 1,
            "last_success_at": None,
            "last_attempt_at": None,
            "next_sync_at": None,
            "grace_until": None,
            "valid_until": None,
            "days_left": None,
            "last_error": "",
            "operation_mode": "",
            "license_duration_type": "",
            "activation_status": "",
            "hardware_bound": False,
        }
    return {
        "enabled": bool(row["enabled"]),
        "locked": bool(row["locked"]),
        "state": row["state"],
        "reason": row["reason"],
        "site_code": row["site_code"],
        "post_no": row["post_no"],
        "machine_id": row["machine_id"],
        "valid_until": row["valid_until"].isoformat() if row.get("valid_until") else None,
        "days_left": row["days_left"],
        "last_success_at": row["last_success_at"].isoformat() if row.get("last_success_at") else None,
        "last_attempt_at": row["last_attempt_at"].isoformat() if row.get("last_attempt_at") else None,
        "next_sync_at": row["next_sync_at"].isoformat() if row.get("next_sync_at") else None,
        "grace_until": row["grace_until"].isoformat() if row.get("grace_until") else None,
        "last_error": row["last_error"],
        "operation_mode": raw_payload.get("operation_mode") or "",
        "license_duration_type": raw_payload.get("license_duration_type") or "",
        "activation_status": raw_payload.get("activation_status") or "",
        "hardware_bound": bool(raw_payload.get("hardware_bound")),
    }


def read_license_cache() -> dict | None:
    with db() as conn:
        return conn.execute("SELECT * FROM license_cache WHERE id = 1").fetchone()


def evaluate_license_lock(row: dict | None, config: dict[str, object] | None = None) -> dict[str, object]:
    config = config or get_license_settings()
    if not config.get("enabled"):
        return public_license_row(row, config)
    now = datetime.now(UTC)
    if not row:
        return public_license_row(None, config)
    valid_until = row.get("valid_until")
    grace_until = row.get("grace_until")
    locked = False
    state = "valid"
    reason = "license valid"
    if not row.get("last_success_at"):
        locked = True
        state = row.get("state") if row.get("state") in {"settings_incomplete", "sync_failed"} else "sync_failed"
        reason = "license requires successful activation"
    elif not row.get("enabled") or (row.get("raw_payload") or {}).get("locked") is True:
        locked = True
        state = "disabled"
        reason = row.get("reason") or "license disabled by gateway"
    elif valid_until and valid_until < now:
        locked = True
        state = "expired"
        reason = "license expired"
    elif row.get("last_error") or (grace_until and grace_until < now):
        state = "grace"
        reason = "using validated cached license; offline operation does not extend license expiry"
    result = dict(row)
    result["locked"] = locked
    result["state"] = state
    result["reason"] = reason
    return public_license_row(result, config)


def apply_license_to_runtime() -> dict[str, object]:
    status_payload = evaluate_license_lock(read_license_cache())
    wash_runtime.set_license_status(
        bool(status_payload["locked"]),
        str(status_payload["reason"]),
        status_payload,
    )
    return status_payload


async def sync_license_once() -> dict[str, object]:
    config = get_license_settings()
    now = datetime.now(UTC)
    if not config.get("enabled"):
        status_payload = apply_license_to_runtime()
        return {"ok": True, "synced": False, "license": status_payload}
    missing = [key for key in ("gateway_url", "site_code", "site_token", "post_no") if not config.get(key)]
    if missing:
        with db() as conn:
            row = conn.execute(
                """
                INSERT INTO license_cache
                  (id, enabled, locked, state, reason, site_code, post_no, last_attempt_at,
                   next_sync_at, last_error, updated_at)
                VALUES (1, false, true, 'settings_incomplete', %s, %s, %s, now(), now() + (%s || ' seconds')::interval, %s, now())
                ON CONFLICT (id) DO UPDATE
                SET locked = true,
                    state = EXCLUDED.state,
                    reason = EXCLUDED.reason,
                    site_code = EXCLUDED.site_code,
                    post_no = EXCLUDED.post_no,
                    last_attempt_at = now(),
                    next_sync_at = EXCLUDED.next_sync_at,
                    last_error = EXCLUDED.last_error,
                    updated_at = now()
                RETURNING *
                """,
                (
                    f"license settings incomplete: {', '.join(missing)}",
                    config.get("site_code") or "",
                    config.get("post_no") or 1,
                    int(config["sync_interval_seconds"]),
                    f"missing {', '.join(missing)}",
                ),
            ).fetchone()
            conn.commit()
        return {"ok": False, "synced": False, "license": apply_license_to_runtime(), "detail": row["last_error"]}

    await sync_pending_offline_license_codes(config)

    try:
        sync_payload = {
            "site_code": config["site_code"],
            "post_no": config["post_no"],
            **hardware_sync_payload(config),
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            sync_response = await client.post(
                f"{config['gateway_url']}/api/v1/license/status",
                json=sync_payload,
                headers={"X-Site-Token": str(config["site_token"])},
            )
            if sync_response.status_code >= 400:
                raise RuntimeError(sync_response.text[:240])
            response = await client.get(
                f"{config['gateway_url']}/api/v1/license/status",
                params={"site_code": config["site_code"], "post_no": config["post_no"]},
                headers={"X-Site-Token": str(config["site_token"])},
            )
        if response.status_code >= 400:
            raise RuntimeError(response.text[:240])
        payload = response.json().get("license") or {}
        license_enabled = bool(payload.get("enabled"))
        valid_until = parse_dt(payload.get("valid_until"))
        last_success = now
        grace_until = now + timedelta(seconds=int(config["grace_seconds"]))
        state = "valid" if license_enabled else "disabled"
        reason = str(payload.get("reason") or ("license valid" if license_enabled else "license disabled by gateway"))
        locked = not license_enabled or bool(payload.get("locked"))
        if valid_until and valid_until < now:
            locked = True
            state = "expired"
            reason = "license expired"
        with db() as conn:
            row = conn.execute(
                """
                INSERT INTO license_cache
                  (id, enabled, locked, state, reason, site_code, post_no, machine_id,
                   valid_until, days_left, last_success_at, last_attempt_at, next_sync_at,
                   grace_until, last_error, raw_payload, updated_at)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s + (%s || ' seconds')::interval, %s, '', %s, now())
                ON CONFLICT (id) DO UPDATE
                SET enabled = EXCLUDED.enabled,
                    locked = EXCLUDED.locked,
                    state = EXCLUDED.state,
                    reason = EXCLUDED.reason,
                    site_code = EXCLUDED.site_code,
                    post_no = EXCLUDED.post_no,
                    machine_id = EXCLUDED.machine_id,
                    valid_until = EXCLUDED.valid_until,
                    days_left = EXCLUDED.days_left,
                    last_success_at = EXCLUDED.last_success_at,
                    last_attempt_at = EXCLUDED.last_attempt_at,
                    next_sync_at = EXCLUDED.next_sync_at,
                    grace_until = EXCLUDED.grace_until,
                    last_error = '',
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = now()
                RETURNING *
                """,
                (
                    license_enabled,
                    locked,
                    state,
                    reason,
                    config["site_code"],
                    config["post_no"],
                    payload.get("machine_id"),
                    valid_until,
                    payload.get("days_left"),
                    last_success,
                    now,
                    now,
                    int(config["sync_interval_seconds"]),
                    grace_until,
                    Jsonb(payload),
                ),
            ).fetchone()
            conn.commit()
    except Exception as exc:
        detail = str(exc)[:300]
        with db() as conn:
            existing = conn.execute("SELECT * FROM license_cache WHERE id = 1").fetchone()
            if existing:
                row = conn.execute(
                    """
                    UPDATE license_cache
                    SET last_attempt_at = now(),
                        next_sync_at = now() + (%s || ' seconds')::interval,
                        last_error = %s,
                        updated_at = now()
                    WHERE id = 1
                    RETURNING *
                    """,
                    (int(config["sync_interval_seconds"]), detail),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    INSERT INTO license_cache
                      (id, enabled, locked, state, reason, site_code, post_no, last_attempt_at,
                       next_sync_at, grace_until, last_error, updated_at)
                    VALUES (1, false, true, 'sync_failed', 'license sync failed', %s, %s,
                            now(), now() + (%s || ' seconds')::interval, now(), %s, now())
                    RETURNING *
                    """,
                    (config["site_code"], config["post_no"], int(config["sync_interval_seconds"]), detail),
                ).fetchone()
            conn.commit()
        status_payload = apply_license_to_runtime()
        return {"ok": False, "synced": False, "license": status_payload, "detail": detail}

    status_payload = apply_license_to_runtime()
    return {"ok": True, "synced": True, "license": status_payload}


def license_sync_loop() -> None:
    while not license_stop_event.wait(2):
        config = get_license_settings()
        if not config.get("enabled"):
            apply_license_to_runtime()
            license_stop_event.wait(60)
            continue
        row = read_license_cache()
        next_sync_at = row.get("next_sync_at") if row else None
        if not next_sync_at or next_sync_at <= datetime.now(UTC):
            try:
                import asyncio

                asyncio.run(sync_license_once())
            except Exception as exc:
                wash_runtime.set_license_status(True, f"license sync crashed: {str(exc)[:160]}", {"state": "sync_crashed"})
        else:
            apply_license_to_runtime()
            wait_seconds = min(300, max(5, int((next_sync_at - datetime.now(UTC)).total_seconds())))
            license_stop_event.wait(wait_seconds)


def configured_gateway_url() -> str:
    config = get_license_settings()
    if not config.get("site_code"):
        return ""
    return str(config.get("gateway_url") or "").strip().rstrip("/")


def check_gateway_connectivity_once() -> None:
    gateway_url = configured_gateway_url()
    success = False
    latency_ms: int | None = None
    error = "gateway is not configured"
    if gateway_url:
        started = time_module.monotonic()
        try:
            response = httpx.get(
                f"{gateway_url}/health",
                timeout=httpx.Timeout(4.0, connect=3.0),
                follow_redirects=True,
            )
            response.raise_for_status()
            success = True
            latency_ms = max(0, round((time_module.monotonic() - started) * 1000))
            error = ""
        except Exception as exc:
            error = str(exc)
    gateway_connectivity.observe(
        gateway_url=gateway_url,
        success=success,
        latency_ms=latency_ms,
        error=error,
    )


def connectivity_check_loop() -> None:
    while not connectivity_stop_event.is_set():
        try:
            check_gateway_connectivity_once()
        except Exception:
            # A failed check must never stop wash operation or the monitor loop.
            pass
        connectivity_stop_event.wait(15)


@app.on_event("startup")
def startup() -> None:
    global connectivity_thread, license_thread
    open_pool()
    with db() as conn:
        conn.execute(SCHEMA_SQL)
        from .wallet_store import WALLET_SCHEMA_SQL
        conn.execute(WALLET_SCHEMA_SQL)
        from .wallet_post import POST_SCHEMA_SQL
        conn.execute(POST_SCHEMA_SQL)
        from .wallet_payments import PAYMENT_SCHEMA_SQL
        conn.execute(PAYMENT_SCHEMA_SQL)
        conn.commit()
    seed_user(settings.default_owner_login, settings.default_owner_password, "owner", "RTU WASH owner")
    seed_user(settings.default_admin_login, settings.default_admin_password, "admin", "RTU WASH admin")
    wash_runtime.start()
    apply_license_to_runtime()
    license_stop_event.clear()
    license_thread = threading.Thread(target=license_sync_loop, name="license-sync", daemon=True)
    license_thread.start()
    connectivity_stop_event.clear()
    connectivity_thread = threading.Thread(target=connectivity_check_loop, name="gateway-connectivity", daemon=True)
    connectivity_thread.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await retention.stop()
    connectivity_stop_event.set()
    if connectivity_thread:
        connectivity_thread.join(timeout=2)
    license_stop_event.set()
    if license_thread:
        license_thread.join(timeout=2)
    wash_runtime.stop()
    close_pool()


@app.get("/health")
def health() -> dict[str, object]:
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"ok": True, "service": "wash-engine", "time": datetime.now(UTC).isoformat()}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> dict[str, object]:
    with db() as conn:
        user = conn.execute(
            """
            SELECT id, login, role, display_name, password_hash, active,
                   must_change_password, auth_version
            FROM auth_users
            WHERE login = %s
            """,
            (payload.login,),
        ).fetchone()

    with db() as conn:
        conn.execute(
            """
            DELETE FROM auth_login_attempts
            WHERE updated_at < now() - interval '1 day'
               OR (login = %s AND locked_until IS NOT NULL AND locked_until <= now())
            """,
            (payload.login,),
        )
        attempt = conn.execute(
            "SELECT failure_count, locked_until FROM auth_login_attempts WHERE login = %s",
            (payload.login,),
        ).fetchone()
        conn.commit()
    if attempt and attempt.get("locked_until") and attempt["locked_until"] > datetime.now(UTC):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts; try again later")

    if not user or not user["active"] or not verify_password(payload.password, user["password_hash"]):
        with db() as conn:
            failed = conn.execute(
                """
                INSERT INTO auth_login_attempts (login, failure_count, locked_until, updated_at)
                VALUES (%s, 1, NULL, now())
                ON CONFLICT (login) DO UPDATE
                SET failure_count = auth_login_attempts.failure_count + 1,
                    locked_until = CASE
                      WHEN auth_login_attempts.failure_count + 1 >= 5
                      THEN now() + interval '5 minutes'
                      ELSE NULL
                    END,
                    updated_at = now()
                RETURNING failure_count, locked_until
                """,
                (payload.login,),
            ).fetchone()
            conn.commit()
        if failed and failed.get("locked_until"):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts; try again later")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login or password")

    with db() as conn:
        conn.execute("DELETE FROM auth_login_attempts WHERE login = %s", (payload.login,))
        conn.commit()

    token, _jti, expires_at = create_access_token(user)
    return {
        "access_token": token,
        "expires_at": expires_at.isoformat(),
        "user": public_user(user),
    }


@app.post("/api/auth/logout")
def logout(
    user: Annotated[dict, Depends(current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> dict[str, bool]:
    expires_at = token_exp_from_payload(credentials)
    token = credentials.credentials
    payload = token.split(".")
    if len(payload) != 3:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    decoded = decode_access_token(token)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO auth_revoked_tokens (jti, user_id, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (jti) DO NOTHING
            """,
            (decoded["jti"], user["id"], expires_at),
        )
        conn.commit()
    return {"ok": True}


@app.get("/api/auth/me", response_model=UserResponse)
def me(user: Annotated[dict, Depends(current_user)]) -> dict:
    return public_user(user)


@app.post("/api/auth/account", response_model=LoginResponse)
def update_account(
    payload: AccountUpdateRequest,
    user: Annotated[dict, Depends(current_user)],
) -> dict:
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid current password")
    if user.get("must_change_password") and not payload.new_password:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "New password is required")
    if payload.new_password and payload.new_password == payload.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be different")

    next_login = payload.login.strip() if payload.login else user["login"]
    next_display_name = payload.display_name.strip() if payload.display_name else user["display_name"]
    next_password_hash = hash_password(payload.new_password) if payload.new_password else user["password_hash"]

    with db() as conn:
        conflict = conn.execute(
            "SELECT id FROM auth_users WHERE login = %s AND id <> %s",
            (next_login, user["id"]),
        ).fetchone()
        if conflict:
            raise HTTPException(status.HTTP_409_CONFLICT, "Login already exists")

        updated = conn.execute(
            """
            UPDATE auth_users
            SET login = %s,
                display_name = %s,
                password_hash = %s,
                must_change_password = CASE WHEN %s THEN FALSE ELSE must_change_password END,
                auth_version = auth_version + CASE WHEN %s THEN 1 ELSE 0 END,
                updated_at = now()
            WHERE id = %s
            RETURNING id, login, role, display_name, must_change_password, auth_version
            """,
            (
                next_login,
                next_display_name,
                next_password_hash,
                bool(payload.new_password),
                bool(payload.new_password),
                user["id"],
            ),
        ).fetchone()
        conn.commit()

    token, _jti, expires_at = create_access_token(updated)
    return {
        "access_token": token,
        "expires_at": expires_at.isoformat(),
        "user": public_user(updated),
    }


@app.get("/api/admin/ping")
def admin_ping(user: Annotated[dict, Depends(require_role("admin"))]) -> dict[str, object]:
    return {"ok": True, "role": user["role"]}


@app.get("/api/owner/ping")
def owner_ping(user: Annotated[dict, Depends(require_role("owner"))]) -> dict[str, object]:
    return {"ok": True, "role": user["role"]}


def report_bounds(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime, date, date]:
    today = datetime.now(REPORT_TIMEZONE).date()
    try:
        start_date = date.fromisoformat(date_from) if date_from else today
        end_date = date.fromisoformat(date_to) if date_to else start_date
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report date format") from exc
    if end_date < start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report date range")
    if (end_date - start_date).days > 92:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Report range cannot exceed 92 days")
    start_at = datetime.combine(start_date, time.min, tzinfo=REPORT_TIMEZONE).astimezone(UTC)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=REPORT_TIMEZONE).astimezone(UTC)
    return start_at, end_at, start_date, end_date


def int_value(row: dict | None, key: str) -> int:
    return int((row or {}).get(key) or 0)


@app.get("/api/owner/reports/summary")
def owner_reports_summary(
    user: Annotated[dict, Depends(require_role("owner"))],
    date_from: str | None = None,
    date_to: str | None = None,
    payment_method: Literal["all", "cash", "click"] = "all",
    sessions_limit: int = 12,
    sessions_offset: int = 0,
) -> dict[str, object]:
    start_at, end_at, start_date, end_date = report_bounds(date_from, date_to)
    sessions_limit = max(1, min(sessions_limit, 50))
    sessions_offset = max(0, sessions_offset)
    with db() as conn:
        sessions = conn.execute(
            """
            SELECT count(*) AS count,
                   count(*) FILTER (WHERE status = 'running') AS running_count,
                   count(*) FILTER (WHERE status IN ('ended', 'closed')) AS closed_count,
                   count(*) FILTER (WHERE status = 'cancelled') AS cancelled_count,
                   COALESCE(sum(paid_sum) FILTER (WHERE source IS DISTINCT FROM 'vip'), 0) AS paid_sum,
                   COALESCE(sum(total_spent_sum) FILTER (WHERE source IS DISTINCT FROM 'vip'), 0) AS spent_sum,
                   COALESCE(sum(bonus_granted_sum),0) AS bonus_granted_sum,
                   COALESCE(sum(bonus_spent_sum),0) AS bonus_spent_sum,
                   COALESCE(sum(total_spent_sum) FILTER (WHERE source = 'vip'), 0) AS vip_virtual_spent_sum,
                   COALESCE(sum(final_credit_sum) FILTER (WHERE source IS DISTINCT FROM 'vip'), 0) AS final_credit_sum
            FROM wash_sessions
            WHERE started_at >= %s AND started_at < %s
              AND (
                %s = 'all'
                OR EXISTS (
                  SELECT 1 FROM payments payment_filter
                  WHERE payment_filter.wash_session_id = wash_sessions.id
                    AND payment_filter.provider = %s
                    AND payment_filter.status IN ('paid', 'credited')
                )
              )
            """,
            (start_at, end_at, payment_method, payment_method),
        ).fetchone()
        payments = conn.execute(
            """
            SELECT provider, count(*) AS count, COALESCE(sum(amount_sum), 0) AS amount_sum, COALESCE(sum(bonus_sum),0) AS bonus_sum
            FROM payments
            WHERE created_at >= %s AND created_at < %s
              AND status IN ('paid', 'credited')
              AND (%s = 'all' OR provider = %s)
            GROUP BY provider
            ORDER BY provider
            """,
            (start_at, end_at, payment_method, payment_method),
        ).fetchall()
        cash = conn.execute(
            """
            SELECT COALESCE(sum(pulse_count), 0) AS pulse_count,
                   COALESCE(sum(amount_sum), 0) AS amount_sum
            FROM cash_events
            WHERE created_at >= %s AND created_at < %s
              AND %s IN ('all', 'cash')
            """,
            (start_at, end_at, payment_method),
        ).fetchone()
        rfid = conn.execute(
            """
            SELECT ledger.reason, count(*) AS count,
                   COALESCE(sum(ledger.amount_sum), 0) AS amount_sum,
                   COALESCE(sum(ledger.duration_seconds), 0) AS duration_seconds
            FROM rfid_card_ledger ledger
            JOIN wash_sessions session ON session.id = ledger.wash_session_id
            WHERE session.started_at >= %s AND session.started_at < %s
              AND (
                %s = 'all'
                OR EXISTS (
                  SELECT 1 FROM payments payment_filter
                  WHERE payment_filter.wash_session_id = session.id
                    AND payment_filter.provider = %s
                    AND payment_filter.status IN ('paid', 'credited')
                )
              )
            GROUP BY ledger.reason
            ORDER BY ledger.reason
            """,
            (start_at, end_at, payment_method, payment_method),
        ).fetchall()
        modes = conn.execute(
            """
            SELECT mode,
                   COALESCE(sum(duration_ms), 0) AS duration_ms,
                   COALESCE(sum(mode_usage.spent_sum-mode_usage.bonus_spent_sum) FILTER (WHERE usage_session.source IS DISTINCT FROM 'vip'), 0) AS spent_sum,
                   COALESCE(sum(mode_usage.bonus_spent_sum),0) AS bonus_spent_sum,
                   COALESCE(sum(spent_sum) FILTER (WHERE usage_session.source = 'vip'), 0) AS vip_virtual_spent_sum,
                   COALESCE(sum(pause_ms), 0) AS pause_ms,
                   COALESCE(sum(total_stop_wait_ms), 0) AS total_stop_wait_ms
            FROM mode_usage
            JOIN wash_sessions usage_session ON usage_session.id = mode_usage.wash_session_id
            WHERE mode_usage.started_at >= %s AND mode_usage.started_at < %s
              AND (
                %s = 'all'
                OR EXISTS (
                  SELECT 1 FROM payments payment_filter
                  WHERE payment_filter.wash_session_id = mode_usage.wash_session_id
                    AND payment_filter.provider = %s
                    AND payment_filter.status IN ('paid', 'credited')
                )
              )
            GROUP BY mode
            ORDER BY spent_sum DESC, duration_ms DESC, mode
            """,
            (start_at, end_at, payment_method, payment_method),
        ).fetchall()
        timeline = conn.execute(
            """
            SELECT (created_at AT TIME ZONE 'Asia/Tashkent')::date AS day,
                   provider,
                   count(*) AS count,
                   COALESCE(sum(amount_sum), 0) AS amount_sum
            FROM payments
            WHERE created_at >= %s AND created_at < %s
              AND status IN ('paid', 'credited')
              AND (%s = 'all' OR provider = %s)
            GROUP BY day, provider
            ORDER BY day, provider
            """,
            (start_at, end_at, payment_method, payment_method),
        ).fetchall()
        recent_sessions = conn.execute(
            """
            SELECT id, started_at, finished_at, status, source, card_uid,
                   paid_sum, final_credit_sum, total_spent_sum, close_reason
            FROM wash_sessions
            WHERE started_at >= %s AND started_at < %s
              AND (
                %s = 'all'
                OR EXISTS (
                  SELECT 1 FROM payments payment_filter
                  WHERE payment_filter.wash_session_id = wash_sessions.id
                    AND payment_filter.provider = %s
                    AND payment_filter.status IN ('paid', 'credited')
                )
              )
            ORDER BY started_at DESC
            LIMIT %s OFFSET %s
            """,
            (start_at, end_at, payment_method, payment_method, sessions_limit, sessions_offset),
        ).fetchall()

    payments_by_provider = {row["provider"]: {"count": int(row["count"]), "amount_sum": int(row["amount_sum"] or 0),"bonus_sum":int(row.get("bonus_sum") or 0)} for row in payments}
    rfid_by_reason = {row["reason"]: row for row in rfid}
    customer_saved = rfid_by_reason.get("save_remaining")
    customer_used = rfid_by_reason.get("use_balance")
    vip_grants = rfid_by_reason.get("vip_grant")
    reconciliation = reconcile_session_credit(
        paid_sum=int_value(sessions, "paid_sum")+int_value(sessions,"bonus_granted_sum"),
        spent_sum=int_value(sessions, "spent_sum"),
        customer_saved_sum=int_value(customer_saved, "amount_sum"),
        final_credit_sum=int_value(sessions, "final_credit_sum"),
    )

    return {
        "ok": True,
        "period": {
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        },
        "payment_method": payment_method,
        "summary": {
            "sessions": int_value(sessions, "count"),
            "running_sessions": int_value(sessions, "running_count"),
            "closed_sessions": int_value(sessions, "closed_count"),
            "cancelled_sessions": int_value(sessions, "cancelled_count"),
            "paid_sum": int_value(sessions, "paid_sum"),
            "spent_sum": int_value(sessions, "spent_sum")-int_value(sessions,"bonus_spent_sum"),
            "bonus_spent_sum": int_value(sessions,"bonus_spent_sum"),
            "bonus_granted_sum": sum(payments_by_provider.get(provider,{}).get("bonus_sum",0) for provider in ("cash","click")),
            "vip_virtual_spent_sum": int_value(sessions, "vip_virtual_spent_sum"),
            "external_revenue_sum": sum(payments_by_provider.get(provider, {}).get("amount_sum", 0) for provider in ("cash", "click")),
            "final_credit_sum": int_value(sessions, "final_credit_sum"),
            "cash_sum": payments_by_provider.get("cash", {}).get("amount_sum", 0),
            "cash_pulses": int_value(cash, "pulse_count"),
            "cash_payment_count": payments_by_provider.get("cash", {}).get("count", 0),
            "click_sum": payments_by_provider.get("click", {}).get("amount_sum", 0),
            "click_count": payments_by_provider.get("click", {}).get("count", 0),
            "customer_saved_sum": int_value(customer_saved, "amount_sum"),
            "customer_saved_count": int_value(customer_saved, "count"),
            "customer_used_sum": int_value(customer_used, "amount_sum"),
            "customer_used_count": int_value(customer_used, "count"),
            "vip_grant_sum": int_value(vip_grants, "amount_sum"),
            "vip_grant_seconds": int_value(vip_grants, "duration_seconds"),
            "vip_grant_count": int_value(vip_grants, "count"),
            **reconciliation,
        },
        "payments": payments_by_provider,
        "rfid": [
            {
                "reason": row["reason"],
                "count": int(row["count"]),
                "amount_sum": int(row["amount_sum"] or 0),
                "duration_seconds": int(row["duration_seconds"] or 0),
            }
            for row in rfid
        ],
        "modes": [
            {
                "mode": row["mode"],
                "duration_ms": int(row["duration_ms"] or 0),
                "spent_sum": int(row["spent_sum"] or 0),
                "vip_virtual_spent_sum": int(row["vip_virtual_spent_sum"] or 0),
                "bonus_spent_sum": int(row.get("bonus_spent_sum") or 0),
                "pause_ms": int(row["pause_ms"] or 0),
                "total_stop_wait_ms": int(row["total_stop_wait_ms"] or 0),
            }
            for row in modes
        ],
        "timeline": [
            {
                "date": row["day"].isoformat(),
                "provider": row["provider"],
                "count": int(row["count"]),
                "amount_sum": int(row["amount_sum"] or 0),
            }
            for row in timeline
        ],
        "sessions": [
            {
                "id": row["id"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                "status": row["status"],
                "source": row["source"],
                "card_uid": row["card_uid"],
                "paid_sum": int(row["paid_sum"] or 0),
                "final_credit_sum": int(row["final_credit_sum"] or 0),
                "total_spent_sum": int(row["total_spent_sum"] or 0),
                "close_reason": row["close_reason"],
            }
            for row in recent_sessions
        ],
    }


@app.get("/api/kiosk/settings")
def get_kiosk_settings() -> dict[str, object]:
    from .contact_api import public_contacts
    with db() as conn:
        row = conn.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = 'kiosk_settings'",
        ).fetchone()
        contacts = public_contacts(conn)
    config = normalize_kiosk_settings(row["setting_value"] if row else None)
    if wash_runtime.device_type=="dry_fog":
        from .device_setup import fog_kiosk_config
        config=fog_kiosk_config(config)
    config["contacts"].update(contacts)
    identity = get_license_settings()
    return {"ok": True, "config": config, "source": "database" if row else "default", "station": {"postNo": identity["post_no"] if identity.get("site_code") else None}}


@app.get("/api/kiosk/payment-options")
def kiosk_payment_options() -> dict[str, object]:
    config = get_click_settings()
    ready = True
    try:
        require_click_ready(config)
    except HTTPException:
        ready = False
    return {"ok": True, "click": {
        "enabled": ready,
        "minAmount": int(config["min_amount_sum"]),
        "maxAmount": int(config["max_amount_sum"]),
    }}


@app.post("/api/kiosk/settings")
def save_kiosk_settings(
    payload: KioskSettingsRequest,
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict[str, object]:
    config = normalize_kiosk_settings(payload.config)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES ('kiosk_settings', %s, now())
            ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value,
                updated_at = now()
            """,
            (Jsonb(config),),
        )
        conn.commit()
    return {"ok": True, "config": config, "source": "database", "updated_by": user["login"]}


@app.post("/api/owner/kiosk/appearance")
def save_kiosk_appearance(payload: KioskSettingsRequest, user: Annotated[dict, Depends(require_role("owner"))]) -> dict[str, object]:
    selection = payload.config.get("mode")
    if selection not in ["auto", "dark", "light"]:
        raise HTTPException(400, "Choose auto, dark or light")
    with db() as conn:
        row = conn.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'kiosk_settings' FOR UPDATE").fetchone()
        config = normalize_kiosk_settings(row["setting_value"] if row else None)
        appearance = config["theme"]["appearance"]
        appearance["mode"] = "auto" if selection == "auto" else "manual"
        if selection != "auto":
            appearance["manualTheme"] = selection
        conn.execute("INSERT INTO app_settings (setting_key, setting_value, updated_at) VALUES ('kiosk_settings', %s, now()) ON CONFLICT (setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value, updated_at=now()", (Jsonb(config),))
        conn.commit()
    return {"ok": True, "appearance": appearance, "updated_by": user["login"]}


@app.post("/api/kiosk/assets/upload")
async def upload_kiosk_asset(
    kind: str,
    user: Annotated[dict, Depends(require_role("owner"))],
    file: UploadFile = File(...),
) -> dict[str, object]:
    normalized_kind = kind.strip().lower()
    if normalized_kind not in ASSET_LIMITS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Asset kind must be icon, logo or background")

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    extension = ASSET_EXTENSIONS.get(content_type)
    if not extension:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PNG, JPG and WEBP images are allowed")

    max_size = ASSET_LIMITS[normalized_kind]
    content = await file.read(max_size + 1)
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if len(content) > max_size:
        max_mb = max_size / 1024 / 1024
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is too large for {normalized_kind}. Maximum size is {max_mb:g} MB",
        )

    digest = hashlib.sha256(content).hexdigest()[:16]
    target_dir = ASSET_ROOT / normalized_kind
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{normalized_kind}-{digest}{extension}"
    target_path = target_dir / target_name
    target_path.write_bytes(content)
    public_url = f"/assets/kiosk/{normalized_kind}/{target_name}"

    with db() as conn:
        conn.execute(
            """
            INSERT INTO system_events (level, event_type, source, message, context)
            VALUES ('info', 'kiosk_asset_uploaded', 'kiosk-ui', %s, %s)
            """,
            (
                f"Kiosk {normalized_kind} asset uploaded",
                Jsonb(
                    {
                        "kind": normalized_kind,
                        "url": public_url,
                        "size": len(content),
                        "content_type": content_type,
                        "uploaded_by": user["login"],
                    }
                ),
            ),
        )
        conn.commit()

    return {
        "ok": True,
        "kind": normalized_kind,
        "url": public_url,
        "content_type": content_type,
        "size": len(content),
    }


@app.get("/api/wash/state")
def wash_state() -> dict[str, object]:
    payload = wash_runtime.snapshot()
    payload["state"].update(gateway_connectivity.snapshot())
    return payload


@app.post("/api/wash/mode")
def wash_select_mode(payload: WashModeRequest) -> dict[str, object]:
    try:
        return wash_runtime.select_mode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@app.post("/api/wash/stop")
def wash_stop(user: Annotated[dict, Depends(require_role("admin"))]) -> dict[str, object]:
    # Financial STOP remains disabled until its remaining-credit policy is agreed.
    # Physical OFF/WEB PAUSE uses the coordinated Admin service and preserves money.
    raise HTTPException(409, "Финансовый STOP отключён. Используйте паузу или Admin all-off: остаток сохраняется.")


@app.post("/api/wash/credit")
def wash_add_credit(
    payload: WashCreditRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    require_simulation_enabled()
    return wash_runtime.add_credit(payload.amount_sum, payload.source)


def default_click_settings() -> dict[str, object]:
    return {
        "enabled": settings.click_enabled,
        "gateway_url": settings.click_gateway_url,
        "site_code": settings.click_site_code,
        "site_token": settings.click_site_token,
        "post_no": settings.click_post_no,
        "min_amount_sum": settings.click_min_amount_sum,
        "max_amount_sum": settings.click_max_amount_sum,
    }


def normalize_click_settings(value: dict | None, include_secret: bool = True) -> dict[str, object]:
    config = default_click_settings()
    if isinstance(value, dict):
        config.update({key: value[key] for key in config if key in value})

    config["enabled"] = bool(config.get("enabled"))
    config["gateway_url"] = str(config.get("gateway_url") or "").strip().rstrip("/")
    config["site_code"] = str(config.get("site_code") or "").strip()
    config["site_token"] = str(config.get("site_token") or "").strip()
    config["post_no"] = max(1, int(config.get("post_no") or 1))
    config["min_amount_sum"] = max(1, int(config.get("min_amount_sum") or 1))
    config["max_amount_sum"] = max(config["min_amount_sum"], int(config.get("max_amount_sum") or config["min_amount_sum"]))

    if not include_secret:
        token = str(config.get("site_token") or "")
        config["site_token_configured"] = bool(token)
        config["site_token"] = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else ("configured" if token else "")
    return config


def get_click_settings(include_secret: bool = True) -> dict[str, object]:
    with db() as conn:
        row = conn.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = 'click_settings'",
        ).fetchone()
    return normalize_click_settings(row["setting_value"] if row else None, include_secret=include_secret)


def require_click_ready(config: dict[str, object]) -> None:
    if not config.get("enabled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Click is disabled")
    license_row = read_license_cache()
    license_payload = dict(license_row.get("raw_payload") or {}) if license_row else {}
    if license_payload.get("operation_mode") == "offline_cash_only":
        raise HTTPException(status.HTTP_409_CONFLICT, "Click is unavailable in permanent offline cash-only mode")
    missing = [key for key in ("gateway_url", "site_code", "site_token", "post_no") if not config.get(key)]
    if missing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Click settings are incomplete: {', '.join(missing)}")


def serialize_click_intent(row: dict) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "gateway_intent_id": str(row["gateway_intent_id"]) if row.get("gateway_intent_id") else None,
        "merchant_trans_id": row.get("gateway_merchant_trans_id"),
        "amount_sum": int(row["amount_sum"] or 0),
        "status": row["status"],
        "credit_destination": row.get("wallet_credit_destination") or "post",
        "gateway_status": row.get("gateway_status") or "",
        "payment_url": row.get("payment_url") or "",
        "last_error": row.get("last_error") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "paid_at": row["paid_at"].isoformat() if row.get("paid_at") else None,
        "credited_at": row["credited_at"].isoformat() if row.get("credited_at") else None,
        "cancelled_at": row["cancelled_at"].isoformat() if row.get("cancelled_at") else None,
    }


def parse_gateway_amount(value: object) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("invalid gateway amount") from exc
    if amount != amount.to_integral_value():
        raise ValueError("gateway amount must be an integer sum")
    return int(amount)


def upsert_gateway_payment(conn, payment: dict[str, object]) -> dict:
    gateway_id = UUID(str(payment["id"]))
    amount_sum = parse_gateway_amount(payment.get("amount_sum"))
    status_value = str(payment.get("status") or "")
    local_status = "credited" if status_value == "paid" and payment.get("credited_at") else status_value
    if local_status not in {"pending", "prepared", "paid", "cancelled", "expired", "error"}:
        local_status = "paid" if status_value == "paid" else "error"
    row = conn.execute(
        """
        INSERT INTO click_payment_intents
          (id, gateway_intent_id, gateway_merchant_trans_id, amount_sum, status,
           payment_url, gateway_status, raw_payload, paid_at, cancelled_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (gateway_intent_id) DO UPDATE
        SET gateway_merchant_trans_id = EXCLUDED.gateway_merchant_trans_id,
            amount_sum = EXCLUDED.amount_sum,
            status = CASE
              WHEN click_payment_intents.credited_at IS NOT NULL THEN 'credited'
              ELSE EXCLUDED.status
            END,
            payment_url = EXCLUDED.payment_url,
            gateway_status = EXCLUDED.gateway_status,
            raw_payload = EXCLUDED.raw_payload,
            paid_at = COALESCE(click_payment_intents.paid_at, EXCLUDED.paid_at),
            cancelled_at = COALESCE(click_payment_intents.cancelled_at, EXCLUDED.cancelled_at),
            updated_at = now()
        RETURNING *
        """,
        (
            uuid4(),
            gateway_id,
            str(payment.get("merchant_trans_id") or ""),
            amount_sum,
            local_status,
            str(payment.get("payment_url") or ""),
            status_value,
            Jsonb(payment),
            payment.get("paid_at"),
            payment.get("cancelled_at"),
        ),
    ).fetchone()
    return row


def apply_click_credit_once(intent_id: UUID) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM click_payment_intents
            WHERE id = %s
            FOR UPDATE
            """,
            (intent_id,),
        ).fetchone()
        if not row or row["status"] not in {"paid", "credited"} or row["credited_at"]:
            conn.commit()
            return row
        from .bonus import award
        if row.get('bonus_sum') is None:
            row=conn.execute('UPDATE click_payment_intents SET bonus_sum=%s WHERE id=%s RETURNING *',(award(int(row['amount_sum']),wash_runtime.params),intent_id)).fetchone()
        amount_sum = int(row["amount_sum"] or 0)
        gateway_id = str(row["gateway_intent_id"] or row["id"])
        raw_payload = dict(row.get("raw_payload") or {})
        conn.commit()

    from .wallet_payments import credit_confirmed
    destination=credit_confirmed(wash_runtime,row) if wash_runtime.shared_wallet_enabled else None
    if destination is None:
        wash_runtime.add_credit(
            amount_sum,
            "click",
            idempotency_key=f"click:{gateway_id}",
            raw_payload={"source": "click", "gateway_intent_id": gateway_id, "intent": raw_payload},
            bonus_sum=int(row.get("bonus_sum") or 0),
        )

    with db() as conn:
        updated = conn.execute(
            """
            UPDATE click_payment_intents
            SET status = 'credited',
                credited_at = COALESCE(credited_at, now()),
                wallet_credit_destination = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (destination or "post",intent_id),
        ).fetchone()
        conn.commit()
    return updated


async def sync_click_payments(config: dict[str, object] | None = None) -> dict[str, object]:
    config = config or get_click_settings()
    require_click_ready(config)
    url = f"{config['gateway_url']}/api/v1/site/payments/export"
    params = {"site_code": config["site_code"], "post_no": config["post_no"]}
    headers = {"X-Site-Token": str(config["site_token"])}
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(url, params=params, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Click gateway sync failed: {response.text[:200]}")
    payload = response.json()
    payments = payload.get("payments") or []
    credited = 0
    imported = 0
    acknowledged_ids: list[str] = []
    with db() as conn:
        for payment in payments:
            row = upsert_gateway_payment(conn, payment)
            imported += 1
            if row["status"] == "paid" and not row["credited_at"]:
                conn.commit()
                credited_row = apply_click_credit_once(row["id"])
                if credited_row and credited_row["credited_at"]:
                    credited += 1
                    acknowledged_ids.append(str(row["gateway_intent_id"]))
            elif row["status"] == "credited" and row["credited_at"]:
                conn.commit()
                acknowledged_ids.append(str(row["gateway_intent_id"]))
            elif row["status"] in {"cancelled", "expired"}:
                conn.commit()
                acknowledged_ids.append(str(row["gateway_intent_id"]))
            else:
                conn.commit()

    acknowledged = 0
    if acknowledged_ids:
        async with httpx.AsyncClient(timeout=8.0) as client:
            ack_response = await client.post(
                f"{config['gateway_url']}/api/v1/site/payments/ack",
                headers=headers,
                json={
                    "site_code": config["site_code"],
                    "post_no": config["post_no"],
                    "payment_ids": list(dict.fromkeys(acknowledged_ids)),
                },
            )
        if ack_response.status_code >= 400:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Click gateway ACK failed: {ack_response.text[:200]}")
        acknowledged = int(ack_response.json().get("acknowledged") or 0)
    return {"ok": True, "imported": imported, "credited": credited, "acknowledged": acknowledged}


@app.get("/api/admin/click/settings")
def admin_click_settings(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    return {"ok": True, "settings": get_click_settings(include_secret=False)}


@app.post("/api/admin/click/settings")
def admin_save_click_settings(
    payload: ClickSettingsRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    current = get_click_settings()
    next_config = normalize_click_settings(payload.model_dump())
    if not payload.site_token.strip() and current.get("site_token"):
        next_config["site_token"] = current["site_token"]
    if next_config["max_amount_sum"] < next_config["min_amount_sum"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Max amount must be greater than min amount")
    with db() as conn:
        before = current
        conn.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES ('click_settings', %s, now())
            ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value,
                updated_at = now()
            """,
            (Jsonb(next_config),),
        )
        conn.execute(
            """
            INSERT INTO settings_history
              (setting_key, old_value, new_value, changed_by_user_id, changed_by_login, change_reason)
            VALUES ('click_settings', %s, %s, %s, %s, 'admin click settings update')
            """,
            (Jsonb({**before, "site_token": "***"}), Jsonb({**next_config, "site_token": "***"}), user["id"], user["login"]),
        )
        conn.commit()
    return {"ok": True, "settings": normalize_click_settings(next_config, include_secret=False)}


@app.post("/api/admin/click/sync")
async def admin_click_sync(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    return await sync_click_payments()


@app.get("/api/admin/click/intents")
def admin_click_intents(
    user: Annotated[dict, Depends(require_role("admin"))],
    limit: int = 50,
) -> dict[str, object]:
    limit = max(1, min(limit, 200))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM click_payment_intents
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return {"ok": True, "intents": [serialize_click_intent(row) for row in rows]}


@app.get("/api/admin/license/status")
def admin_license_status(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    public_settings = get_license_settings(include_secret=False)
    return {
        "ok": True,
        "settings": public_settings,
        "license": apply_license_to_runtime(),
        "hardware": get_hardware_identity(public_settings),
    }


@app.post("/api/admin/license/sync")
async def admin_license_sync(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    return await sync_license_once()


@app.post("/api/wash/license/sync")
async def wash_license_sync() -> dict[str, object]:
    current = apply_license_to_runtime()
    if not current.get("locked"):
        return {"ok": True, "synced": False, "license": current}
    return await sync_license_once()


@app.post("/api/admin/license/offline-code")
async def admin_apply_offline_license_code(
    payload: OfflineLicenseCodeRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    config = get_license_settings()
    site_token = str(config.get("site_token") or "")
    if not site_token:
        raise HTTPException(status.HTTP_409_CONFLICT, "Site token is required before applying offline codes")
    expected_site = str(config.get("site_code") or "")
    expected_post = int(config.get("post_no") or 1)
    code_payload = verify_offline_code_for_post(payload.code, site_token, config)
    action = str(code_payload.get("action") or "")
    if action not in {"activate", "extend", "disable", "disable_enforcement"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported offline code action")
    nonce = str(code_payload["nonce"])
    now = datetime.now(UTC)
    code_hash = offline_code_sha256(payload.code)
    with db() as conn:
        used = conn.execute("SELECT nonce FROM offline_license_codes WHERE nonce = %s", (nonce,)).fetchone()
        if used:
            raise HTTPException(status.HTTP_409_CONFLICT, "Offline code was already used on this post")
        existing = conn.execute("SELECT * FROM license_cache WHERE id = 1").fetchone()
        if action == "activate":
            operation_mode = str(code_payload.get("operation_mode") or "offline_cash_only")
            valid_until = None
            state = "valid"
            reason = (
                "permanent offline cash-only activation"
                if operation_mode == "offline_cash_only"
                else "permanent full license activation"
            )
            enabled = True
            locked = False
            days_left = None
            grace_until = None
        elif action == "extend":
            days = max(1, min(365, int(code_payload.get("days") or 1)))
            base_until = existing.get("valid_until") if existing else None
            base = base_until if base_until and base_until > now else now
            valid_until = base + timedelta(days=days)
            state = "valid"
            reason = f"offline emergency unlock for {days} day(s)"
            enabled = True
            locked = False
            days_left = max(0, int((valid_until - now).total_seconds() // 86400))
            grace_until = valid_until
        elif action == "disable_enforcement":
            valid_until = None
            state = "offline_enforcement_disabled"
            reason = "offline license enforcement disabled by code"
            enabled = True
            locked = False
            days_left = None
            grace_until = None
        else:
            valid_until = now
            state = "disabled"
            reason = "offline emergency disable code applied"
            enabled = False
            locked = True
            days_left = 0
            grace_until = now
        row = conn.execute(
            """
            INSERT INTO license_cache
              (id, enabled, locked, state, reason, site_code, post_no,
               valid_until, days_left, last_success_at, last_attempt_at,
               next_sync_at, grace_until, last_error, raw_payload, updated_at)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(),
                    now() + (%s || ' seconds')::interval, %s, '', %s, now())
            ON CONFLICT (id) DO UPDATE
            SET enabled = EXCLUDED.enabled,
                locked = EXCLUDED.locked,
                state = EXCLUDED.state,
                reason = EXCLUDED.reason,
                site_code = EXCLUDED.site_code,
                post_no = EXCLUDED.post_no,
                valid_until = EXCLUDED.valid_until,
                days_left = EXCLUDED.days_left,
                last_success_at = EXCLUDED.last_success_at,
                last_attempt_at = EXCLUDED.last_attempt_at,
                next_sync_at = EXCLUDED.next_sync_at,
                grace_until = EXCLUDED.grace_until,
                last_error = '',
                raw_payload = EXCLUDED.raw_payload,
                updated_at = now()
            RETURNING *
            """,
            (
                enabled,
                locked,
                state,
                reason,
                expected_site,
                expected_post,
                valid_until,
                days_left,
                int(config["sync_interval_seconds"]),
                grace_until,
                Jsonb({**code_payload, "offline_code": {**code_payload, "code_hash": code_hash}}),
            ),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO offline_license_codes
              (nonce, code_sha256, action, payload, gateway_ack_status, applied_by_user_id, applied_by_login)
            VALUES (%s, %s, %s, %s, 'pending', %s, %s)
            """,
            (nonce, code_hash, action, Jsonb(code_payload), user["id"], user["login"]),
        )
        conn.execute(
            """
            INSERT INTO system_events(level, event_type, source, message, context)
            VALUES ('warning', 'offline_license_code_applied', 'wash-engine', %s, %s)
            """,
            (reason, Jsonb({"site_code": expected_site, "post_no": expected_post, "nonce": nonce, "action": action})),
        )
        conn.commit()
    gateway_ack: dict[str, object] = {"ok": False, "status": "pending"}
    try:
        gateway_ack = await acknowledge_offline_license_code_to_gateway(config, nonce, action, code_hash, code_payload)
    except Exception as exc:
        ack_status = "rejected" if isinstance(exc, PermanentGatewayAckError) else "failed"
        with db() as conn:
            conn.execute(
                """
                UPDATE offline_license_codes
                SET gateway_ack_status = %s,
                    gateway_ack_error = %s,
                    gateway_ack_attempted_at = now()
                WHERE nonce = %s
                """,
                (ack_status, str(exc)[:300], nonce),
            )
            conn.commit()
        gateway_ack = {"ok": False, "status": ack_status, "error": str(exc)[:300]}
    else:
        with db() as conn:
            conn.execute(
                """
                UPDATE offline_license_codes
                SET gateway_ack_status = 'acked',
                    gateway_ack_error = '',
                    gateway_ack_attempted_at = now(),
                    gateway_acked_at = now()
                WHERE nonce = %s
                """,
                (nonce,),
            )
            conn.commit()
    return {
        "ok": True,
        "applied": True,
        "license": apply_license_to_runtime(),
        "offline": public_license_row(row, config),
        "gateway_ack": gateway_ack,
    }


@app.post("/api/wash/license/offline-code")
async def wash_apply_offline_license_code(payload: OfflineLicenseCodeRequest) -> dict[str, object]:
    current = apply_license_to_runtime()
    if not current.get("locked"):
        raise HTTPException(status.HTTP_409_CONFLICT, "License is not locked")
    config = get_license_settings()
    site_token = str(config.get("site_token") or "")
    if not site_token:
        raise HTTPException(status.HTTP_409_CONFLICT, "Site token is required before applying offline codes")
    code_payload = verify_offline_code_for_post(payload.code, site_token, config)
    action = str(code_payload.get("action") or "")
    if action not in {"activate", "extend", "disable_enforcement"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only emergency unlock codes can be applied on wash screen")
    expected_site = str(config.get("site_code") or "")
    expected_post = int(config.get("post_no") or 1)
    nonce = str(code_payload["nonce"])
    now = datetime.now(UTC)
    code_hash = offline_code_sha256(payload.code)
    with db() as conn:
        used = conn.execute("SELECT nonce FROM offline_license_codes WHERE nonce = %s", (nonce,)).fetchone()
        if used:
            raise HTTPException(status.HTTP_409_CONFLICT, "Offline code was already used on this post")
        existing = conn.execute("SELECT * FROM license_cache WHERE id = 1").fetchone()
        if action == "activate":
            operation_mode = str(code_payload.get("operation_mode") or "offline_cash_only")
            valid_until = None
            days_left = None
            reason = (
                "permanent offline cash-only activation"
                if operation_mode == "offline_cash_only"
                else "permanent full license activation"
            )
            state = "valid"
        elif action == "disable_enforcement":
            valid_until = None
            days_left = None
            reason = "offline license enforcement disabled by code"
            state = "offline_enforcement_disabled"
        else:
            days = max(1, min(365, int(code_payload.get("days") or 1)))
            base_until = existing.get("valid_until") if existing else None
            base = base_until if base_until and base_until > now else now
            valid_until = base + timedelta(days=days)
            days_left = max(0, int((valid_until - now).total_seconds() // 86400))
            state = "valid"
            reason = f"offline emergency unlock for {days} day(s)"
        row = conn.execute(
            """
            INSERT INTO license_cache
              (id, enabled, locked, state, reason, site_code, post_no,
               valid_until, days_left, last_success_at, last_attempt_at,
               next_sync_at, grace_until, last_error, raw_payload, updated_at)
            VALUES (1, true, false, %s, %s, %s, %s, %s, %s, now(), now(),
                    now() + (%s || ' seconds')::interval, %s, '', %s, now())
            ON CONFLICT (id) DO UPDATE
            SET enabled = EXCLUDED.enabled,
                locked = EXCLUDED.locked,
                state = EXCLUDED.state,
                reason = EXCLUDED.reason,
                site_code = EXCLUDED.site_code,
                post_no = EXCLUDED.post_no,
                valid_until = EXCLUDED.valid_until,
                days_left = EXCLUDED.days_left,
                last_success_at = EXCLUDED.last_success_at,
                last_attempt_at = EXCLUDED.last_attempt_at,
                next_sync_at = EXCLUDED.next_sync_at,
                grace_until = EXCLUDED.grace_until,
                last_error = '',
                raw_payload = EXCLUDED.raw_payload,
                updated_at = now()
            RETURNING *
            """,
            (
                state,
                reason,
                expected_site,
                expected_post,
                valid_until,
                days_left,
                int(config["sync_interval_seconds"]),
                None if action in {"activate", "disable_enforcement"} else valid_until,
                Jsonb({
                    **code_payload,
                    "offline_code": {**code_payload, "code_hash": code_hash, "applied_from": "wash_screen"},
                }),
            ),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO offline_license_codes
              (nonce, code_sha256, action, payload, gateway_ack_status, applied_by_user_id, applied_by_login)
            VALUES (%s, %s, %s, %s, 'pending', NULL, 'wash-screen')
            """,
            (nonce, code_hash, action, Jsonb(code_payload)),
        )
        conn.execute(
            """
            INSERT INTO system_events(level, event_type, source, message, context)
            VALUES ('warning', 'offline_license_code_applied', 'wash-screen', %s, %s)
            """,
            (reason, Jsonb({"site_code": expected_site, "post_no": expected_post, "nonce": nonce, "action": action})),
        )
        conn.commit()
    gateway_ack: dict[str, object] = {"ok": False, "status": "pending"}
    try:
        gateway_ack = await acknowledge_offline_license_code_to_gateway(config, nonce, action, code_hash, code_payload)
    except Exception as exc:
        ack_status = "rejected" if isinstance(exc, PermanentGatewayAckError) else "failed"
        with db() as conn:
            conn.execute(
                """
                UPDATE offline_license_codes
                SET gateway_ack_status = %s,
                    gateway_ack_error = %s,
                    gateway_ack_attempted_at = now()
                WHERE nonce = %s
                """,
                (ack_status, str(exc)[:300], nonce),
            )
            conn.commit()
        gateway_ack = {"ok": False, "status": ack_status, "error": str(exc)[:300]}
    else:
        with db() as conn:
            conn.execute(
                """
                UPDATE offline_license_codes
                SET gateway_ack_status = 'acked',
                    gateway_ack_error = '',
                    gateway_ack_attempted_at = now(),
                    gateway_acked_at = now()
                WHERE nonce = %s
                """,
                (nonce,),
            )
            conn.commit()
    return {
        "ok": True,
        "applied": True,
        "license": apply_license_to_runtime(),
        "offline": public_license_row(row, config),
        "gateway_ack": gateway_ack,
    }


def reset_local_runtime_data(
    user: dict,
    *,
    clear_identity: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    current_license = get_license_settings()
    current_click = get_click_settings()
    license_config = current_license
    click_config = current_click
    if clear_identity:
        license_config = normalize_license_settings(clear_post_identity(current_license))
        click_config = normalize_click_settings(clear_post_identity(current_click))

    with db() as conn:
        shared=conn.execute("SELECT setting_value FROM app_settings WHERE setting_key='shared_wallet'").fetchone()
    if shared and shared['setting_value'].get('enabled'):
        raise HTTPException(409,"Сброс поста с общим кошельком требует отдельной процедуры сверки и отключения")

    tables = [
        "cash_pulse_batches",
        "wash_payments",
        "click_payment_intents",
        "rfid_cards",
        "rfid_events",
        "wash_sessions",
        "event_log",
        "vip_profiles",
        "payments",
        "cash_events",
        "mode_usage",
        "rfid_card_ledger",
        "system_events",
        "system_state",
        "auth_revoked_tokens",
        "license_cache",
        "offline_license_codes",
    ]
    with db() as conn:
        conn.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
        if clear_identity:
            conn.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value, updated_at)
                VALUES
                  ('license_settings', %s, now()),
                  ('click_settings', %s, now()),
                  ('commissioning_state', '{"complete": false}'::jsonb, now())
                ON CONFLICT (setting_key) DO UPDATE
                SET setting_value = EXCLUDED.setting_value,
                    updated_at = now()
                """,
                (Jsonb(license_config), Jsonb(click_config)),
            )
        conn.execute(
            """
            INSERT INTO system_events(level, event_type, source, message, context)
            VALUES ('warning', 'install_runtime_reset', 'install-page', 'Runtime data reset during provisioning', %s)
            """,
            (
                Jsonb(
                    {
                        "user": user["login"],
                        "role": user["role"],
                        "post_identity_cleared": clear_identity,
                    }
                ),
            ),
        )
        conn.commit()
    return license_config, click_config


@app.get("/api/admin/install/status")
def admin_install_status(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    public_license = get_license_settings(include_secret=False)
    return {
        "ok": True,
        "network": get_host_network_summary(),
        "hardware": get_hardware_identity(public_license),
        "license_settings": public_license,
        "click_settings": get_click_settings(include_secret=False),
        "license": apply_license_to_runtime(),
    }


@app.get("/api/commissioning/status")
async def commissioning_status() -> dict[str, object]:
    public_license = get_license_settings(include_secret=False)
    public_click = get_click_settings(include_secret=False)
    try:
        io_health = await io_request("/health")
        io_ready = io_health.get("modbus_ok") is True
    except HTTPException:
        io_ready = False
    return {
        "ok": True,
        "commissioning": get_commissioning_state(),
        "device": local_status(),
        "network": get_host_network_summary(),
        "hardware": get_hardware_identity(public_license),
        "io_ready": io_ready,
        "license": apply_license_to_runtime(),
        "site": {
            "site_code": public_license.get("site_code") or "",
            "post_no": int(public_license.get("post_no") or 1),
            "gateway_url": public_license.get("gateway_url") or "https://gateway.example.com",
            "click_enabled": bool(public_click.get("enabled")),
        },
    }


@app.get("/api/commissioning/state")
def commissioning_state() -> dict[str, object]:
    state = get_commissioning_state()
    return {"ok": True, "complete": bool(state.get("complete"))}


@app.get("/api/commissioning/access", response_class=Response)
def commissioning_access(
    client_ip: Annotated[str | None, Header(alias="X-Commissioning-Client-IP")] = None,
) -> Response:
    complete = bool(get_commissioning_state().get("complete"))
    if not client_ip or not commissioning_access_allowed(client_ip, complete=complete):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Commissioning access is closed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/commissioning/claim")
async def commissioning_claim(payload: CommissioningClaimRequest) -> dict[str, object]:
    from .admin_service import require_idle
    require_idle(wash_runtime)
    if get_commissioning_state().get("complete"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Post commissioning is already complete")
    gateway_url = payload.gateway_url.strip().rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resolved = await client.post(
                f"{gateway_url}/api/v1/commissioning/resolve",
                json={"activation_code": payload.activation_code.strip().upper()},
            )
            if resolved.status_code >= 400:
                detail = resolved.json().get("detail", "Activation code was rejected") if resolved.content else "Activation code was rejected"
                raise HTTPException(resolved.status_code, str(detail))
            target = resolved.json()
            hardware = hardware_sync_payload({"site_code": target["site_code"], "post_no": target["post_no"]})
            if len(hardware) != 3:
                raise HTTPException(status.HTTP_409_CONFLICT, "Hardware identity is incomplete")
            response = await client.post(
                f"{gateway_url}/api/v1/commissioning/claim",
                json={"activation_code": payload.activation_code.strip().upper(), "hardware": hardware},
            )
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Gateway is not reachable") from exc
    if response.status_code >= 400:
        detail = response.json().get("detail", "Activation code was rejected") if response.content else "Activation code was rejected"
        raise HTTPException(response.status_code, str(detail))
    claim = response.json()
    save_commissioning_config(
        str(claim["site_code"]), int(claim["post_no"]), gateway_url,
        str(claim["site_token"]), payload.click_enabled,
    )
    sync_result = await sync_license_once()
    if apply_license_to_runtime().get("locked"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Post identity saved, but gateway license is locked")
    current = await commissioning_status()
    return {**current, "claimed": True, "sync": sync_result}


@app.post("/api/commissioning/sync")
async def commissioning_sync() -> dict[str, object]:
    config = get_license_settings()
    if not config.get("site_code") or not config.get("site_token"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Activate the post first")
    sync_result = await sync_license_once()
    current = await commissioning_status()
    return {**current, "sync": sync_result}


@app.post("/api/commissioning/offline-request")
def commissioning_offline_request(payload: CommissioningOfflineRequest) -> JSONResponse:
    if get_commissioning_state().get("complete"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Post commissioning is already complete")
    provisional = {"site_code": payload.site_code.strip(), "post_no": payload.post_no}
    hardware = get_hardware_identity(provisional)
    if not hardware.get("complete"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Hardware identity is incomplete")
    request_id = str(uuid4())
    body = {
        "schema": "sammoy.commissioning-request.v1",
        "request_id": request_id,
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": payload.purpose,
        "site_code": payload.site_code.strip(),
        "post_no": payload.post_no,
        "gateway_url": payload.gateway_url.strip().rstrip("/"),
        "click_enabled": payload.click_enabled,
        "hardware": hardware_sync_payload(provisional),
    }
    filename = f"RTU-WASH-{payload.site_code.strip()}-P{payload.post_no}-{request_id[:8]}.request.json"
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/commissioning/offline-response")
async def commissioning_offline_response(file: UploadFile = File(...)) -> dict[str, object]:
    from .admin_service import require_idle
    require_idle(wash_runtime)
    if get_commissioning_state().get("complete"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Post commissioning is already complete")
    content = await file.read(64 * 1024 + 1)
    if len(content) > 64 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Commissioning response is too large")
    try:
        response = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid commissioning response file") from exc
    if response.get("schema") != "sammoy.commissioning-response.v1":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported commissioning response")
    verify_commissioning_response_signature(response)
    site_code = str(response.get("site_code") or "").strip()
    post_no = int(response.get("post_no") or 0)
    site_token = str(response.get("site_token") or "")
    gateway_url = str(response.get("gateway_url") or "").strip().rstrip("/")
    code = str(response.get("offline_code") or "")
    if not all((site_code, post_no > 0, site_token, gateway_url, code)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Commissioning response is incomplete")
    config = {"site_code": site_code, "post_no": post_no}
    hardware = get_hardware_identity(config)
    applied = apply_offline_commissioning_license(code, site_token, hardware)
    if applied.get("site") != site_code or int(applied.get("post") or 0) != post_no:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Commissioning response target does not match")
    save_commissioning_config(
        site_code, post_no, gateway_url, site_token, bool(response.get("click_enabled")),
    )
    current = await commissioning_status()
    return {**current, "imported": True}


@app.post("/api/commissioning/complete")
async def commissioning_complete(payload: CommissioningCompleteRequest) -> dict[str, object]:
    from .admin_service import require_idle
    require_idle(wash_runtime)
    config = get_license_settings()
    hardware = get_hardware_identity(config)
    license_state = apply_license_to_runtime()
    if not hardware.get("complete"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Hardware identity is incomplete")
    try:
        io_health = await io_request("/health")
    except HTTPException as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Modbus I/O helper is not ready") from exc
    if io_health.get("modbus_ok") is not True:
        raise HTTPException(status.HTTP_409_CONFLICT, "Modbus I/O helper is not ready")
    if not config.get("site_code") or not config.get("site_token"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Post identity is not configured")
    if license_state.get("locked"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"License is locked: {license_state.get('reason')}")
    from .device_setup import local_status
    device=local_status()
    if device["active_type"]!=device["requested"]["type"]:raise HTTPException(409,"Примените профиль оборудования перед завершением установки")
    completed_at = datetime.now(UTC).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(setting_key, setting_value, updated_at)
            VALUES ('commissioning_state', %s, now())
            ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value, updated_at = now()
            """,
            (Jsonb({"complete": True, "completed_at": completed_at}),),
        )
        conn.execute(
            """
            INSERT INTO system_events(level, event_type, source, message, context)
            VALUES ('info', 'commissioning_complete', 'installer-wizard', 'Post commissioning completed', %s)
            """,
            (Jsonb({"site_code": config["site_code"], "post_no": config["post_no"]}),),
        )
        conn.commit()
    return await commissioning_status()


@app.post("/api/admin/install/apply")
async def admin_install_apply(
    payload: InstallApplyRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    from .admin_service import require_idle
    require_idle(wash_runtime)
    gateway_url = str(payload.gateway_url or "").strip().rstrip("/")
    site_code = str(payload.site_code or "").strip()
    site_token = str(payload.site_token or "").strip()
    if payload.reset_runtime_data:
        if payload.reset_confirmation.strip().upper() != "RESET":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Type RESET to clean cloned post data")
        license_config, click_config = reset_local_runtime_data(user, clear_identity=True)
        license_stop_event.set()
        license_stop_event.clear()
        public_license = normalize_license_settings(license_config, include_secret=False)
        return {
            "ok": True,
            "applied": True,
            "reset_runtime_data": True,
            "sync": {"ok": True, "synced": False},
            "network": get_host_network_summary(),
            "hardware": get_hardware_identity(public_license),
            "license_settings": public_license,
            "click_settings": normalize_click_settings(click_config, include_secret=False),
            "license": apply_license_to_runtime(),
        }

    if not gateway_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gateway URL is required")
    if not site_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Site code is required")
    if payload.click_max_amount_sum < payload.click_min_amount_sum:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Click max amount must be greater than min amount")

    current_license = get_license_settings()
    current_click = get_click_settings()
    effective_site_token = resolve_site_token(site_token, current_license, current_click)
    protect_shared_wallet_identity({'site_code':site_code,'post_no':payload.post_no,'site_token':effective_site_token})
    if payload.license_enabled and not effective_site_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Site token is required when license is enabled")
    if payload.click_enabled and not effective_site_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Site token is required when Click is enabled")
    license_config = normalize_license_settings(
        {
            "enabled": payload.license_enabled,
            "gateway_url": gateway_url,
            "site_code": site_code,
            "site_token": effective_site_token,
            "post_no": payload.post_no,
            "sync_interval_seconds": payload.sync_interval_seconds,
            "grace_seconds": payload.grace_seconds,
        }
    )
    click_config = normalize_click_settings(
        {
            "enabled": payload.click_enabled,
            "gateway_url": gateway_url,
            "site_code": site_code,
            "site_token": effective_site_token,
            "post_no": payload.post_no,
            "min_amount_sum": payload.click_min_amount_sum,
            "max_amount_sum": payload.click_max_amount_sum,
        }
    )

    with db() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES ('license_settings', %s, now()), ('click_settings', %s, now())
            ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value,
                updated_at = now()
            """,
            (Jsonb(license_config), Jsonb(click_config)),
        )
        conn.execute(
            """
            INSERT INTO settings_history
              (setting_key, old_value, new_value, changed_by_user_id, changed_by_login, change_reason)
            VALUES
              ('license_settings', %s, %s, %s, %s, 'install provisioning update'),
              ('click_settings', %s, %s, %s, %s, 'install provisioning update')
            """,
            (
                Jsonb({**current_license, "site_token": "***"}),
                Jsonb({**license_config, "site_token": "***"}),
                user["id"],
                user["login"],
                Jsonb({**current_click, "site_token": "***"}),
                Jsonb({**click_config, "site_token": "***"}),
                user["id"],
                user["login"],
            ),
        )
        conn.commit()

    license_stop_event.set()
    license_stop_event.clear()
    sync_result = await sync_license_once() if license_config.get("enabled") else {"ok": True, "synced": False}
    public_license = normalize_license_settings(license_config, include_secret=False)
    return {
        "ok": True,
        "applied": True,
        "reset_runtime_data": payload.reset_runtime_data,
        "sync": sync_result,
        "network": get_host_network_summary(),
        "hardware": get_hardware_identity(public_license),
        "license_settings": public_license,
        "click_settings": normalize_click_settings(click_config, include_secret=False),
        "license": apply_license_to_runtime(),
    }


@app.post("/api/admin/license/settings")
def admin_save_license_settings(
    payload: LicenseSettingsRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    current = get_license_settings()
    next_config = normalize_license_settings(payload.model_dump())
    if not payload.site_token.strip() and current.get("site_token"):
        next_config["site_token"] = current["site_token"]
    protect_shared_wallet_identity(next_config)
    if next_config.get("enabled"):
        missing = [key for key in ("gateway_url", "site_code", "site_token", "post_no") if not next_config.get(key)]
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"License settings incomplete: {', '.join(missing)}",
            )
    with db() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES ('license_settings', %s, now())
            ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value,
                updated_at = now()
            """,
            (Jsonb(next_config),),
        )
        conn.execute(
            """
            INSERT INTO settings_history
              (setting_key, old_value, new_value, changed_by_user_id, changed_by_login, change_reason)
            VALUES ('license_settings', %s, %s, %s, %s, 'admin license settings update')
            """,
            (
                Jsonb({**current, "site_token": "***"}),
                Jsonb({**next_config, "site_token": "***"}),
                user["id"],
                user["login"],
            ),
        )
        conn.commit()
    license_stop_event.set()
    license_stop_event.clear()
    return {"ok": True, "settings": normalize_license_settings(next_config, include_secret=False), "license": apply_license_to_runtime()}


@app.post("/api/click/intents")
async def create_click_intent(payload: ClickIntentRequest) -> dict[str, object]:
    license_status = apply_license_to_runtime()
    if license_status.get("locked"):
        raise HTTPException(status.HTTP_423_LOCKED, f"License locked: {license_status.get('reason')}")
    config = get_click_settings()
    require_click_ready(config)
    amount_sum = int(payload.amount_sum)
    if amount_sum < int(config["min_amount_sum"]) or amount_sum > int(config["max_amount_sum"]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Amount must be between {config['min_amount_sum']} and {config['max_amount_sum']} sum",
        )

    local_id = uuid4()
    with db() as conn:
        conn.execute(
            """
            UPDATE click_payment_intents
            SET status = 'expired', updated_at = now()
            WHERE status IN ('local_pending', 'pending', 'prepared')
              AND updated_at < now() - interval '15 minutes'
            """,
        )
        active = conn.execute(
            """
            SELECT *
            FROM click_payment_intents
            WHERE status IN ('local_pending', 'pending', 'prepared')
            ORDER BY updated_at DESC
            LIMIT 1
            FOR UPDATE
            """,
        ).fetchone()
        if active and active["status"] == "prepared":
            raise HTTPException(status.HTTP_409_CONFLICT, "A Click payment is already being processed")
        if active and int(active["amount_sum"] or 0) == amount_sum:
            conn.commit()
            return {"ok": True, "intent": serialize_click_intent(active), "reused": True}
        if active:
            conn.execute(
                """
                UPDATE click_payment_intents
                SET status = 'cancelled', cancelled_at = COALESCE(cancelled_at, now()), updated_at = now()
                WHERE id = %s AND status IN ('local_pending', 'pending')
                """,
                (active["id"],),
            )
        from .wallet_payments import bind_new_intent
        origin_session,origin_uid=bind_new_intent(wash_runtime)
        row = conn.execute(
            """
            INSERT INTO click_payment_intents (id, amount_sum, status,wallet_origin_session_id,wallet_origin_uid)
            VALUES (%s, %s, 'local_pending',%s,%s)
            RETURNING *
            """,
            (local_id, amount_sum,origin_session,origin_uid),
        ).fetchone()
        conn.commit()

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"{config['gateway_url']}/api/v1/intents",
                headers={"X-Site-Token": str(config["site_token"])},
                json={
                    "site_code": config["site_code"],
                    "post_no": config["post_no"],
                    "amount_sum": amount_sum,
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(response.text[:300])
        gateway_intent = response.json().get("intent") or {}
        gateway_intent_id = UUID(str(gateway_intent["id"]))
        gateway_status = str(gateway_intent.get("status") or "pending")
        with db() as conn:
            existing = conn.execute(
                "SELECT * FROM click_payment_intents WHERE gateway_intent_id = %s FOR UPDATE",
                (gateway_intent_id,),
            ).fetchone()
            if existing and existing["id"] != local_id:
                conn.execute("DELETE FROM click_payment_intents WHERE id = %s AND status = 'local_pending'", (local_id,))
                row = conn.execute(
                    """
                    UPDATE click_payment_intents
                    SET gateway_merchant_trans_id = %s,
                        amount_sum = %s,
                        status = %s,
                        gateway_status = %s,
                        payment_url = %s,
                        raw_payload = %s,
                        updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        str(gateway_intent.get("merchant_trans_id") or ""), amount_sum,
                        gateway_status, gateway_status, str(gateway_intent.get("payment_url") or ""),
                        Jsonb(gateway_intent), existing["id"],
                    ),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE click_payment_intents
                    SET gateway_intent_id = %s,
                        gateway_merchant_trans_id = %s,
                        status = %s,
                        gateway_status = %s,
                        payment_url = %s,
                        raw_payload = %s,
                        updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        gateway_intent_id, str(gateway_intent.get("merchant_trans_id") or ""),
                        gateway_status, gateway_status, str(gateway_intent.get("payment_url") or ""),
                        Jsonb(gateway_intent), local_id,
                    ),
                ).fetchone()
            conn.commit()
    except Exception as exc:
        with db() as conn:
            row = conn.execute(
                """
                UPDATE click_payment_intents
                SET status = 'error',
                    last_error = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (str(exc), local_id),
            ).fetchone()
            conn.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Click gateway create intent failed: {str(exc)[:200]}") from exc

    return {"ok": True, "intent": serialize_click_intent(row)}


@app.post("/api/click/intents/{intent_id}/cancel")
async def cancel_click_intent(intent_id: UUID) -> dict[str, object]:
    config = get_click_settings()
    require_click_ready(config)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM click_payment_intents WHERE id = %s FOR UPDATE",
            (intent_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Click intent not found")
        if row["status"] not in {"local_pending", "pending"}:
            conn.commit()
            return {"ok": True, "intent": serialize_click_intent(row)}
        gateway_intent_id = row.get("gateway_intent_id")
        if not gateway_intent_id:
            row = conn.execute(
                """
                UPDATE click_payment_intents
                SET status = 'cancelled', cancelled_at = COALESCE(cancelled_at, now()), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (intent_id,),
            ).fetchone()
            conn.commit()
            return {"ok": True, "intent": serialize_click_intent(row)}

    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.post(
            f"{config['gateway_url']}/api/v1/intents/{gateway_intent_id}/cancel",
            headers={"X-Site-Token": str(config["site_token"])},
        )
    if response.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Click gateway cancel failed: {response.text[:200]}")
    gateway_intent = response.json().get("intent") or {}
    gateway_status = str(gateway_intent.get("status") or "cancelled")
    with db() as conn:
        row = conn.execute(
            """
            UPDATE click_payment_intents
            SET status = %s,
                gateway_status = %s,
                raw_payload = %s,
                cancelled_at = CASE WHEN %s = 'cancelled' THEN COALESCE(cancelled_at, now()) ELSE cancelled_at END,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (gateway_status, gateway_status, Jsonb(gateway_intent), gateway_status, intent_id),
        ).fetchone()
        conn.commit()
    return {"ok": True, "intent": serialize_click_intent(row)}


@app.get("/api/click/intents/{intent_id}")
async def get_click_intent(intent_id: UUID) -> dict[str, object]:
    try:
        await sync_click_payments()
    except HTTPException:
        pass
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM click_payment_intents WHERE id = %s",
            (intent_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Click intent not found")
    return {"ok": True, "intent": serialize_click_intent(row)}


@app.get("/api/owner/wash/parameters")
def owner_wash_parameters(
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict[str, object]:
    snapshot = wash_runtime.snapshot()
    return {"ok": True, "parameters": snapshot["parameters"]}


@app.post("/api/owner/wash/parameters")
def owner_save_wash_parameters(
    payload: WashParametersRequest,
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict[str, object]:
    try:
        result=wash_runtime.save_parameters(payload.parameters)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {"ok": True, "parameters": result, "updated_by": user["login"]}


def serialize_vip_profile(row: dict) -> dict[str, object]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "enabled": row["enabled"],
        "grant_seconds": row["grant_seconds"],
        "max_uses_per_day": row["max_uses_per_day"],
        "owner_notes": row["owner_notes"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


@app.get("/api/owner/vip-profiles")
def owner_vip_profiles(
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict[str, object]:
    if wash_runtime.shared_wallet_enabled:
        from .wallet_registry import read_registry
        from .wallet_api import registry_bridge
        return {'ok':True,'profiles':registry_bridge(read_registry)['profiles']}
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, code, name, enabled, grant_seconds, max_uses_per_day,
                   owner_notes, created_at, updated_at
            FROM vip_profiles
            ORDER BY id
            """,
        ).fetchall()
    return {"ok": True, "profiles": [serialize_vip_profile(row) for row in rows]}


@app.post("/api/owner/vip-profiles")
def owner_save_vip_profiles(
    payload: VipProfilesRequest,
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict[str, object]:
    if wash_runtime.shared_wallet_enabled:
        from .wallet_registry import save_profiles
        from .wallet_api import registry_bridge
        return registry_bridge(save_profiles,payload,user)
    profiles = []
    seen_codes: set[str] = set()
    for item in payload.profiles:
        code = item.code.strip().upper()
        name = item.name.strip()
        if not code or not name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "VIP profile code and name are required")
        if code in seen_codes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Duplicate VIP profile code: {code}")
        seen_codes.add(code)
        profiles.append(
            {
                "id": item.id,
                "code": code,
                "name": name,
                "enabled": item.enabled,
                "grant_seconds": item.grant_seconds,
                "max_uses_per_day": item.max_uses_per_day,
                "owner_notes": item.owner_notes.strip(),
            }
        )

    with db() as conn:
        before = conn.execute(
            """
            SELECT id, code, name, enabled, grant_seconds, max_uses_per_day, owner_notes
            FROM vip_profiles
            ORDER BY id
            """,
        ).fetchall()
        for profile in profiles:
            if profile["id"]:
                conn.execute(
                    """
                    UPDATE vip_profiles
                    SET code = %s,
                        name = %s,
                        enabled = %s,
                        grant_seconds = %s,
                        max_uses_per_day = %s,
                        owner_notes = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        profile["code"],
                        profile["name"],
                        profile["enabled"],
                        profile["grant_seconds"],
                        profile["max_uses_per_day"],
                        profile["owner_notes"],
                        profile["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO vip_profiles
                      (code, name, enabled, grant_seconds, max_uses_per_day, owner_notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE
                    SET name = EXCLUDED.name,
                        enabled = EXCLUDED.enabled,
                        grant_seconds = EXCLUDED.grant_seconds,
                        max_uses_per_day = EXCLUDED.max_uses_per_day,
                        owner_notes = EXCLUDED.owner_notes,
                        updated_at = now()
                    """,
                    (
                        profile["code"],
                        profile["name"],
                        profile["enabled"],
                        profile["grant_seconds"],
                        profile["max_uses_per_day"],
                        profile["owner_notes"],
                    ),
                )

        history_after = conn.execute(
            """
            SELECT id, code, name, enabled, grant_seconds, max_uses_per_day, owner_notes
            FROM vip_profiles
            ORDER BY id
            """,
        ).fetchall()
        rows = conn.execute(
            """
            SELECT id, code, name, enabled, grant_seconds, max_uses_per_day,
                   owner_notes, created_at, updated_at
            FROM vip_profiles
            ORDER BY id
            """,
        ).fetchall()
        conn.execute(
            """
            INSERT INTO settings_history
              (setting_key, old_value, new_value, changed_by_user_id, changed_by_login, change_reason)
            VALUES ('vip_profiles', %s, %s, %s, %s, 'owner parameter update')
            """,
            (Jsonb([dict(row) for row in before]), Jsonb([dict(row) for row in history_after]), user["id"], user["login"]),
        )
        conn.commit()

    return {"ok": True, "profiles": [serialize_vip_profile(row) for row in rows], "updated_by": user["login"]}


def serialize_rfid_card(row: dict) -> dict[str, object]:
    return {
        "uid": row["uid"],
        "card_type": row["card_type"],
        "status": row.get("status") or "active",
        "enabled": row["enabled"],
        "display_name": row.get("display_name") or "",
        "balance_sum": row["balance_sum"],
        "vip_profile_id": row.get("vip_profile_id"),
        "vip_profile_code": row.get("vip_profile_code"),
        "vip_profile_name": row.get("vip_profile_name"),
        "last_seen_at": row["last_seen_at"].isoformat() if row.get("last_seen_at") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "expires_at":row["expires_at"].isoformat() if row.get("expires_at") else None,
    }


@app.get("/api/owner/rfid/latest")
async def owner_rfid_latest(
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict:
    return await io_request("/rfid/latest")


@app.get("/api/owner/rfid/cards")
def owner_rfid_cards(
    user: Annotated[dict, Depends(require_role("owner"))],
    include_inactive: bool = False,
) -> dict[str, object]:
    if wash_runtime.shared_wallet_enabled:
        from .wallet_registry import read_registry
        from .wallet_api import registry_bridge
        rows=registry_bridge(read_registry)['cards']
        return {'ok':True,'cards':[r for r in rows if include_inactive or (r['enabled'] and r['status']=='active')]}
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.uid, c.card_type, c.status, c.enabled, c.display_name,
                   c.balance_sum, c.vip_profile_id, c.last_seen_at,
                   c.created_at, c.updated_at, c.expires_at,
                   p.code AS vip_profile_code,
                   p.name AS vip_profile_name
            FROM rfid_cards c
            LEFT JOIN vip_profiles p ON p.id = c.vip_profile_id
            WHERE c.card_type = 'vip'
              AND (%s OR (c.enabled = true AND COALESCE(c.status, 'active') = 'active'))
            ORDER BY c.updated_at DESC, c.uid
            """,
            (include_inactive,)
        ).fetchall()
    return {"ok": True, "cards": [serialize_rfid_card(row) for row in rows]}


@app.post("/api/owner/rfid/cards")
def owner_save_rfid_card(
    payload: RfidCardRequest,
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict[str, object]:
    if wash_runtime.shared_wallet_enabled:
        from .wallet_registry import save_card
        from .wallet_api import registry_bridge
        return registry_bridge(save_card,payload,user)
    uid = payload.uid.strip().upper()
    if payload.card_type != "vip":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Owner can register only VIP cards")
    if not payload.vip_profile_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "VIP card requires VIP profile")

    expiry=None
    if payload.expires_at:
        try:
            expiry=datetime.fromisoformat(payload.expires_at)
            if expiry.tzinfo is None:raise ValueError()
        except ValueError:raise HTTPException(422,'Укажите срок действия VIP с часовым поясом') from None
    with db() as conn:
        if payload.vip_profile_id:
            profile = conn.execute(
                "SELECT id FROM vip_profiles WHERE id = %s",
                (payload.vip_profile_id,),
            ).fetchone()
            if not profile:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "VIP profile not found")

        frozen=conn.execute("SELECT 1 FROM shared_wallet_vip_imports WHERE uid=%s AND status='pending'",(uid,)).fetchone()
        if frozen:raise HTTPException(409,'VIP-источник заморожен для переноса: завершите установку и перенос в Owner')
        row = conn.execute(
            """
            INSERT INTO rfid_cards
              (uid, card_type, status, enabled, display_name, balance_sum, vip_profile_id, last_seen_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
            ON CONFLICT (uid) DO UPDATE
            SET card_type = EXCLUDED.card_type,
                status = EXCLUDED.status,
                enabled = EXCLUDED.enabled,
                display_name = EXCLUDED.display_name,
                balance_sum = EXCLUDED.balance_sum,
                vip_profile_id = EXCLUDED.vip_profile_id,
                last_seen_at = now(),
                updated_at = now()
            WHERE rfid_cards.balance_sum = 0
            RETURNING uid
            """,
            (
                uid,
                payload.card_type,
                payload.status,
                payload.enabled,
                payload.display_name.strip(),
                0,
                payload.vip_profile_id,
            ),
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "На карте есть деньги. VIP-регистрация не обнуляет средства.")
        conn.execute(
            """
            INSERT INTO system_events (level, event_type, source, message, context)
            VALUES ('info', 'rfid_card_saved', 'owner-ui', %s, %s)
            """,
            (
                f"RFID card {uid} saved",
                Jsonb({"uid": uid, "card_type": payload.card_type, "changed_by": user["login"]}),
            ),
        )
        if 'expires_at' in payload.model_fields_set:
            conn.execute('UPDATE rfid_cards SET expires_at=%s WHERE uid=%s',(expiry,uid))
        saved = conn.execute(
            """
            SELECT c.uid, c.card_type, c.status, c.enabled, c.display_name,
                   c.balance_sum, c.vip_profile_id, c.last_seen_at,
                   c.created_at, c.updated_at, c.expires_at,
                   p.code AS vip_profile_code,
                   p.name AS vip_profile_name
            FROM rfid_cards c
            LEFT JOIN vip_profiles p ON p.id = c.vip_profile_id
            WHERE c.uid = %s
            """,
            (row["uid"],),
        ).fetchone()
        conn.commit()

    return {"ok": True, "card": serialize_rfid_card(saved), "updated_by": user["login"]}


@app.delete("/api/owner/rfid/cards/{uid}")
def owner_delete_rfid_card(
    uid: str,
    user: Annotated[dict, Depends(require_role("owner"))],
) -> dict[str, object]:
    if wash_runtime.shared_wallet_enabled:
        from .wallet_registry import remove_card
        from .wallet_api import registry_bridge
        return registry_bridge(remove_card,uid,user)
    normalized_uid = uid.strip().upper()
    with db() as conn:
        current = conn.execute(
            """
            SELECT uid, card_type, display_name
            FROM rfid_cards
            WHERE uid = %s
            """,
            (normalized_uid,),
        ).fetchone()
        if not current:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "RFID card not found")
        if current["card_type"] != "vip":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Owner can delete only VIP cards")

        conn.execute(
            """
            UPDATE rfid_cards
            SET card_type = 'customer',
                status = 'active',
                enabled = true,
                vip_profile_id = NULL,
                updated_at = now()
            WHERE uid = %s
            """,
            (normalized_uid,),
        )
        conn.execute(
            """
            INSERT INTO system_events (level, event_type, source, message, context)
            VALUES ('info', 'rfid_vip_card_deleted', 'owner-ui', %s, %s)
            """,
            (
                f"VIP RFID card {normalized_uid} deleted",
                Jsonb(
                    {
                        "uid": normalized_uid,
                        "display_name": current.get("display_name") or "",
                        "changed_by": user["login"],
                    }
                ),
            ),
        )
        conn.commit()

    return {"ok": True, "uid": normalized_uid, "deleted_by": user["login"]}


def require_simulation_enabled():
    if not settings.simulation_enabled:
        raise HTTPException(403, "Симуляции отключены в рабочем режиме. Для DEMO используйте /preview/wash.")


@app.get("/api/admin/wash/simulation")
def admin_wash_simulation(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    snapshot = wash_runtime.snapshot()
    return {"ok": True, "simulation": snapshot["simulation"], "state": snapshot["state"]}


@app.post("/api/admin/wash/simulation/total-stop")
def admin_wash_sim_total_stop(
    payload: WashSimTotalStopRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    require_simulation_enabled()
    return wash_runtime.set_simulated_total_stop(payload.active)


@app.post("/api/admin/wash/simulation/coin-pulses")
def admin_wash_sim_coin_pulses(
    payload: WashSimPulsesRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    require_simulation_enabled()
    return wash_runtime.add_simulated_coin_pulses(payload.count)


@app.post("/api/admin/wash/simulation/license")
def admin_wash_sim_license(
    payload: WashSimLicenseRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    require_simulation_enabled()
    wash_runtime.set_simulated_license(payload.mode)
    apply_license_to_runtime()
    return wash_runtime.snapshot()


@app.post("/api/admin/wash/simulation/reset")
def admin_wash_sim_reset(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict[str, object]:
    wash_runtime.reset_simulation()
    apply_license_to_runtime()
    return wash_runtime.snapshot()


@app.post("/api/admin/io/simulate/input/{name}")
async def admin_io_simulate_input(
    name: str,
    payload: WashSimTotalStopRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    require_simulation_enabled()
    if payload.active is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Simulated input state is required")
    return await io_request(
        f"/simulate/input/{name}",
        method="POST",
        json={"active": payload.active},
    )


@app.post("/api/admin/io/simulate/pulses/{name}")
async def admin_io_simulate_pulses(
    name: str,
    payload: WashSimPulsesRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    require_simulation_enabled()
    return await io_request(
        f"/simulate/pulses/{name}",
        method="POST",
        json={"count": payload.count},
    )


@app.post("/api/admin/io/simulate/rfid")
async def admin_io_simulate_rfid(
    payload: WashSimRfidRequest,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    require_simulation_enabled()
    return await io_request("/simulate/rfid", method="POST", json={"uid": payload.uid})


@app.post("/api/admin/io/simulate/reset")
async def admin_io_simulate_reset(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    require_simulation_enabled()
    wash_runtime.reset_simulation()
    return await io_request("/simulate/reset", method="POST")


@app.get("/api/admin/io/health")
async def admin_io_health(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    return await io_request("/health")


@app.get("/api/admin/io/io")
async def admin_io_io(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    return await io_request("/io")


@app.get("/api/admin/io/rfid/latest")
async def admin_io_rfid_latest(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    return await io_request("/rfid/latest")


@app.post("/api/admin/io/do/{name}/{state}")
async def admin_io_set_output(
    name: str,
    state: str,
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    if state not in {"on", "off"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "State must be on or off")
    from .admin_service import all_off
    if state == "on":
        raise HTTPException(409, "Используйте тест на 1 секунду в Admin → Диагностика")
    # OFF is a coordinated WEB PAUSE, not a relay change the next tick can undo.
    return await __import__('asyncio').to_thread(all_off, wash_runtime, settings.io_helper_url)


@app.post("/api/admin/io/do/all-off")
async def admin_io_all_off(
    user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    from .admin_service import all_off
    return await __import__('asyncio').to_thread(all_off, wash_runtime, settings.io_helper_url)


async def telegram_setup_request(action: str, method: str = "GET", payload: dict | None = None) -> dict:
    url = os.environ.get("TELEGRAM_SETUP_URL", "http://telegram-reports:8076").rstrip("/")
    key = os.environ.get("TELEGRAM_SETUP_KEY", "")
    if not key:
        raise HTTPException(503, "Telegram service is not installed")
    try:
        async with httpx.AsyncClient(timeout=55) as client:
            response = await client.request(method, url + "/" + action,
                headers={"Authorization": "Bearer " + key}, json=payload if method != "GET" else None)
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Telegram report service is unavailable") from None
    if response.status_code >= 400:
        raise HTTPException(response.status_code, data.get("detail", "Telegram service error"))
    return data


async def sync_telegram_identity() -> None:
    config = get_license_settings()
    site = str(config.get("site_code") or "").strip()
    secret = str(config.get("site_token") or "")
    if site and secret:
        key = hashlib.sha256(f"rtu-wash-local-reports-v1:{secret}".encode()).hexdigest()
        await telegram_setup_request("identity/sync", "POST", {
            "site_id": site, "post_no": int(config.get("post_no") or 1), "api_key": key})


@app.get("/api/owner/telegram-setup/status")
async def owner_telegram_status(user: Annotated[dict, Depends(require_role("owner"))]) -> dict:
    from .wallet_api import configuration
    cfg=configuration()
    result=await telegram_setup_request("status")
    return {**result,'manage_allowed':not cfg['enabled'] or cfg['local_post']==cfg['primary_post'],'primary_post':cfg['primary_post']}


@app.post("/api/owner/telegram-setup/{action}")
async def owner_telegram_action(action: Literal["configure-auto", "pairing", "disable", "discover"],
    payload: dict, user: Annotated[dict, Depends(require_role("owner"))]) -> dict:
    from .wallet_api import configuration
    cfg=configuration()
    if cfg['enabled'] and cfg['local_post']!=cfg['primary_post']:
        raise HTTPException(409,'Configure Telegram on the current primary controller')
    if action in {"configure-auto", "discover"}:
        await sync_telegram_identity()
    if action == "discover":
        from .admin_api import network_request
        import ipaddress
        try:
            network = await network_request('/status')
            interfaces = network.get('interfaces', [])
            primary = next((i for i in interfaces if i.get('primary') and i.get('address')), None)
            if primary:
                subnet = ipaddress.ip_network(f"{primary['address']}/{primary['prefix']}", strict=False)
                payload = {**payload, 'cidr': str(subnet)}
        except HTTPException:
            pass  # Existing deployments can still use REPORT_LAN_CIDR.
    return await telegram_setup_request(action, "POST", payload)


_telegram_identity_task = None

@app.on_event("startup")
async def start_telegram_identity_sync():
    import asyncio
    global _telegram_identity_task
    if not os.environ.get("TELEGRAM_SETUP_KEY"):
        return
    async def poll():
        while True:
            try:
                await sync_telegram_identity()
                from .wallet_telegram import sync as sync_shared_telegram
                await sync_shared_telegram()
            except Exception:
                # Reporting availability must never interrupt wash operation.
                pass
            await asyncio.sleep(30)
    _telegram_identity_task = asyncio.create_task(poll())

@app.on_event("shutdown")
async def stop_telegram_identity_sync():
    import asyncio
    from contextlib import suppress
    if _telegram_identity_task:
        _telegram_identity_task.cancel()
        with suppress(asyncio.CancelledError):
            await _telegram_identity_task

@app.get('/api/owner/reports/stations')
async def owner_station_reports(
    user: Annotated[dict, Depends(require_role('owner'))],
    period: Literal['daily','weekly','monthly'] = 'daily', value: date | None = None,
) -> dict:
    selected = value or datetime.now(ZoneInfo('Asia/Tashkent')).date()
    return await telegram_setup_request(f'aggregate/{period}?value={selected.isoformat()}')


from .admin_api import router as admin_router
app.include_router(admin_router)
from .owner_site import router as owner_site_router
app.include_router(owner_site_router)

from . import retention
app.add_event_handler("startup", retention.start)

# Shared wallet defaults to disabled until site commissioning.
from .wallet_api import router as wallet_router, SetupRequest as WalletSetupRequest
app.include_router(wallet_router)

@app.get('/api/commissioning/wallet',dependencies=[Depends(commissioning_access)])
def commissioning_wallet_status():
    from .wallet_api import owner_status
    return owner_status({'login':'installer'})

@app.post('/api/commissioning/wallet',dependencies=[Depends(commissioning_access)])
def commissioning_wallet_setup(payload:WalletSetupRequest):
    from .wallet_api import setup
    return setup(payload,{'login':'installer'})


@app.get('/api/commissioning/network/{kind}',dependencies=[Depends(commissioning_access)])
async def commissioning_network_read(kind: str):
    if get_commissioning_state().get('complete') or kind not in ('status','wifi'):
        raise HTTPException(403,'Network commissioning is closed')
    from .admin_api import network_request
    return await network_request('/'+kind)


@app.post('/api/commissioning/network/{action}',dependencies=[Depends(commissioning_access)])
async def commissioning_network_action(action:str,payload:dict):
    if get_commissioning_state().get('complete') or action not in ('apply','confirm','rollback'):
        raise HTTPException(403,'Network commissioning is closed')
    from .admin_api import network_request
    from .admin_service import require_idle
    if action=='apply':require_idle(wash_runtime)
    return await network_request('/'+action,'POST',payload)


@app.get('/api/commissioning/telegram/status', dependencies=[Depends(commissioning_access)])
async def commissioning_telegram_status():
    if get_commissioning_state().get('complete'):
        raise HTTPException(403, 'Post commissioning is already complete')
    from .wallet_api import configuration
    cfg = configuration()
    primary = int(cfg['primary_post']) if cfg['enabled'] else 1
    result = await telegram_setup_request('status')
    return {**result, 'install_manage_allowed': int(get_license_settings().get('post_no') or 1) == primary, 'primary_post': primary}


@app.post('/api/commissioning/telegram/{action}', dependencies=[Depends(commissioning_access)])
async def commissioning_telegram_action(action: Literal['configure-auto', 'pairing', 'discover'], payload: dict):
    from .admin_service import require_idle
    if get_commissioning_state().get('complete'):
        raise HTTPException(403, 'Post commissioning is already complete')
    require_idle(wash_runtime)
    config = get_license_settings()
    if not config.get('site_code') or apply_license_to_runtime().get('locked'):
        raise HTTPException(409, 'Activate the station first')
    from .wallet_api import configuration
    cfg = configuration()
    primary = int(cfg['primary_post']) if cfg['enabled'] else 1
    if int(config.get('post_no') or 1) != primary:
        raise HTTPException(409, 'Telegram is managed on the primary station')
    if action == 'configure-auto':
        current = await telegram_setup_request('status')
        if current.get('owner_paired'):
            raise HTTPException(409, 'Bot replacement requires Owner sign-in')
    if payload.get('reset_owner'):
        raise HTTPException(409, 'Owner replacement requires Owner sign-in')
    return await owner_telegram_action(action, payload, {})

from .contact_api import router as contact_router
app.include_router(contact_router)


@app.get('/api/device/profiles')
def device_profile_catalog():
    from .device_profiles import catalog
    return catalog()


from .device_setup import router as device_router,LocalDevice,DevicePolicy,local_status,request_local
app.include_router(device_router)

@app.get('/api/commissioning/device',dependencies=[Depends(commissioning_access)])
def commissioning_device_read():return local_status()

@app.post('/api/commissioning/device',dependencies=[Depends(commissioning_access)])
def commissioning_device_write(payload:LocalDevice):
    from .wallet_domain import WalletConflict
    try:return request_local(payload)
    except WalletConflict as exc:raise HTTPException(409,str(exc)) from None

@app.get('/api/commissioning/device-policy',dependencies=[Depends(commissioning_access)])
def commissioning_device_policy_read():
    from .device_setup import read_policy
    return read_policy({'login':'installer'})

@app.post('/api/commissioning/device-policy',dependencies=[Depends(commissioning_access)])
def commissioning_device_policy_write(payload:DevicePolicy):
    from .device_setup import save_policy
    return save_policy(payload,{'login':'installer'})

# Stop runtime/background workers before closing their reusable transports.
from .http_pool import close_all as close_sync_http_clients
app.add_event_handler("shutdown", close_sync_http_clients)
