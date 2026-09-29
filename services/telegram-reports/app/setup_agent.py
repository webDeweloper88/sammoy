from __future__ import annotations

import asyncio
import base64
import grp
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx
import psycopg
import qrcode
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.telegram_bot.store import PairingStore

ENV_PATH = Path(os.getenv("RTU_WASH_REPORTS_ENV", "/opt/rtu-wash/secrets/reports.env"))
APP_DIR = Path(os.getenv("RTU_WASH_REPORTS_DIR", "/opt/rtu-wash/reports"))
POSTS_PATH = APP_DIR / "config/posts.yaml"
DATA_PATH = APP_DIR / "data/hub.sqlite3"
ORANGE_ENV_PATH = Path(os.getenv("RTU_WASH_ENV", "/opt/rtu-wash/.env"))
SERVICES = ("rtu-wash-local-hub.service", "rtu-wash-telegram-bot.service")
SERVICE_GROUP = "rtu-wash-reports"
BOT_TOKEN_PATTERN = re.compile(r"^[0-9]{6,12}:[A-Za-z0-9_-]{30,100}$")

app = FastAPI(title="RTU WASH Telegram setup", docs_url=None, redoc_url=None)


class ConfigureRequest(BaseModel):
    enabled: bool = True
    post_no: int = Field(ge=1, le=999)
    site_id: str = Field(min_length=1, max_length=80)
    site_name: str = Field(min_length=1, max_length=120)
    token: str = Field(default="", max_length=256)


class PairingRequest(BaseModel):
    reset_owner: bool = False


class IdentityRequest(BaseModel):
    site_id: str = Field(min_length=1, max_length=80)
    post_no: int = Field(ge=1, le=999)


class MobileTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


MOBILE_SESSION_MINUTES = 10
MOBILE_SESSION_MAX_ATTEMPTS = 5
mobile_sessions: dict[str, dict[str, object]] = {}
mobile_session_lock = asyncio.Lock()


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed = shlex.split(value, comments=False, posix=True)
        values[key] = parsed[0] if parsed else ""
    return values


def read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        parsed = shlex.split(value, comments=False, posix=True)
        values[key.strip()] = parsed[0] if parsed else ""
    return values


def write_env(updates: dict[str, str]) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pending = dict(updates)
    rendered: list[str] = []
    for raw in current:
        if "=" not in raw or raw.lstrip().startswith("#"):
            rendered.append(raw)
            continue
        key = raw.split("=", 1)[0]
        if key in pending:
            rendered.append(f"{key}={shlex.quote(pending.pop(key))}")
        else:
            rendered.append(raw)
    rendered.extend(f"{key}={shlex.quote(value)}" for key, value in pending.items())
    with NamedTemporaryFile("w", dir=ENV_PATH.parent, delete=False, encoding="utf-8") as handle:
        handle.write("\n".join(rendered).rstrip() + "\n")
        temporary = Path(handle.name)
    temporary.chmod(0o640)
    os.chown(temporary, 0, grp.getgrnam(SERVICE_GROUP).gr_gid)
    temporary.replace(ENV_PATH)


def pairing_store() -> PairingStore:
    store = PairingStore(DATA_PATH)
    group_id = grp.getgrnam(SERVICE_GROUP).gr_gid
    os.chown(DATA_PATH.parent, 0, group_id)
    os.chown(DATA_PATH, 0, group_id)
    DATA_PATH.parent.chmod(0o770)
    DATA_PATH.chmod(0o660)
    return store


def service_active(name: str) -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", name], check=False, timeout=5
    ).returncode == 0


def set_services(enabled: bool) -> None:
    action = "enable" if enabled else "disable"
    subprocess.run(["systemctl", action, *SERVICES], check=True, timeout=15)
    if enabled:
        subprocess.run(["systemctl", "restart", *SERVICES], check=True, timeout=20)
    else:
        subprocess.run(["systemctl", "stop", *SERVICES], check=False, timeout=15)


def restart_services(*services: str) -> None:
    subprocess.run(["systemctl", "restart", *services], check=True, timeout=20)


def orange_identity() -> tuple[str, int, str]:
    values = read_key_values(ORANGE_ENV_PATH)
    user = values.get("POSTGRES_USER", "rtu_wash")
    password = values.get("POSTGRES_PASSWORD", "")
    database = values.get("POSTGRES_DB", "rtu_wash")
    port = values.get("POSTGRES_PORT", "5432")
    if not password:
        raise HTTPException(503, "Orange database credentials are unavailable")
    try:
        with psycopg.connect(
            host="127.0.0.1", port=port, user=user, password=password, dbname=database, connect_timeout=5
        ) as conn:
            row = conn.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = 'license_settings'"
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(503, "Orange identity is unavailable") from exc
    payload = row[0] if row else {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    site_id = str(payload.get("site_code") or "").strip()
    post_no = int(payload.get("post_no") or 0)
    site_token = str(payload.get("site_token") or "")
    if not site_id or post_no < 1 or not site_token:
        raise HTTPException(409, "Activate the Orange post before enabling reports")
    return site_id, post_no, site_token


def report_key(site_token: str) -> str:
    return hashlib.sha256(f"rtu-wash-local-reports-v1:{site_token}".encode()).hexdigest()


def write_posts(site_id: str, posts: list[dict[str, object]]) -> None:
    POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTS_PATH.write_text(
        yaml.safe_dump(
            {
                "site": {"id": site_id, "name": site_id, "timezone": "Asia/Tashkent"},
                "posts": posts,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def sync_identity(expected_site: str, expected_post: int) -> dict[str, object]:
    site_id, post_no, site_token = orange_identity()
    if site_id != expected_site or post_no != expected_post:
        raise HTTPException(409, "Orange post identity changed; refresh commissioning status")
    key = report_key(site_token)
    post_id = f"POST-{post_no:02d}"
    write_env(
        {
            "SITE_ID": site_id,
            "SITE_NAME": site_id,
            "POST_ID": post_id,
            "POST_NAME": f"Post {post_no}",
            "LOCAL_REPORT_API_KEY": key,
            "SITE_REPORT_API_KEY": key,
        }
    )
    if post_no == 1:
        write_posts(
            site_id,
            [
                {
                    "id": post_id,
                    "name": "Post 1",
                    "host": "127.0.0.1",
                    "port": 8091,
                    "api_key_env": "SITE_REPORT_API_KEY",
                    "enabled": True,
                }
            ],
        )
    subprocess.run(
        ["chown", "-R", "rtu-wash-reports:rtu-wash-reports", str(APP_DIR / "config"), str(APP_DIR / "data")],
        check=True,
        timeout=10,
    )
    restart_services("rtu-wash-report-api.service")
    return {"site_id": site_id, "post_id": post_id}


def local_network() -> ipaddress.IPv4Network:
    result = subprocess.run(
        ["ip", "-j", "route", "get", "1.1.1.1"], check=True, capture_output=True, text=True, timeout=5
    )
    route = json.loads(result.stdout)[0]
    source = str(route.get("prefsrc") or route.get("src") or "")
    device = str(route.get("dev") or "")
    addresses = subprocess.run(
        ["ip", "-j", "address", "show", "dev", device], check=True, capture_output=True, text=True, timeout=5
    )
    for item in json.loads(addresses.stdout)[0].get("addr_info", []):
        if item.get("family") == "inet" and item.get("local") == source:
            network = ipaddress.ip_network(f"{source}/{item['prefixlen']}", strict=False)
            if network.num_addresses > 256:
                raise HTTPException(409, "Automatic discovery supports /24 or smaller LANs")
            return network
    raise HTTPException(503, "LAN address is unavailable")


def local_ipv4_address() -> str:
    result = subprocess.run(
        ["ip", "-j", "route", "get", "1.1.1.1"], check=True, capture_output=True, text=True, timeout=5
    )
    route = json.loads(result.stdout)[0]
    source = str(route.get("prefsrc") or route.get("src") or "")
    try:
        return str(ipaddress.ip_address(source))
    except ValueError as exc:
        raise HTTPException(503, "LAN address is unavailable") from exc


async def telegram_identity(token: str) -> dict[str, object]:
    if not BOT_TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(400, "Telegram bot token has an invalid format")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Telegram is not reachable") from exc
    if response.status_code != 200:
        raise HTTPException(400, "Telegram bot token is invalid")
    payload = response.json()
    result = payload.get("result") or {}
    if not payload.get("ok") or not result.get("username"):
        raise HTTPException(400, "Telegram bot token is invalid")
    return result


def public_status() -> dict[str, object]:
    env = read_env()
    owner = pairing_store().owner()
    configured = bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_BOT_USERNAME"))
    return {
        "ok": True,
        "available": True,
        "configured": configured,
        "enabled": configured and service_active("rtu-wash-telegram-bot.service"),
        "hub_active": service_active("rtu-wash-local-hub.service"),
        "bot_username": env.get("TELEGRAM_BOT_USERNAME", ""),
        "owner_paired": owner is not None,
        "owner_name": (owner["telegram_first_name"] or owner["telegram_username"] or "") if owner else "",
        "site_id": env.get("SITE_ID", ""),
        "post_id": env.get("POST_ID", ""),
        "token_saved": bool(env.get("TELEGRAM_BOT_TOKEN")),
        "configured_posts": len(load_posts()),
    }


def load_posts() -> list[dict[str, object]]:
    if not POSTS_PATH.exists():
        return []
    payload = yaml.safe_load(POSTS_PATH.read_text(encoding="utf-8")) or {}
    return list(payload.get("posts") or [])


def qr_data_url(value: str) -> str:
    image = qrcode.make(value)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def prune_mobile_sessions(now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    expired = [
        key
        for key, value in mobile_sessions.items()
        if value.get("used") or value.get("expires_at", current) <= current
    ]
    for key in expired:
        mobile_sessions.pop(key, None)


def mobile_session(raw: str) -> dict[str, object]:
    prune_mobile_sessions()
    session = mobile_sessions.get(raw)
    if not session:
        raise HTTPException(410, "This setup link has expired")
    if session.get("busy"):
        raise HTTPException(409, "Token verification is already in progress")
    if int(session.get("attempts") or 0) >= MOBILE_SESSION_MAX_ATTEMPTS:
        mobile_sessions.pop(raw, None)
        raise HTTPException(410, "Too many failed attempts; create a new QR code")
    return session


def mobile_setup_page(raw: str, nonce: str) -> str:
    endpoint = f"/api/telegram-setup/mobile/{raw}/configure"
    return f"""<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>RTU WASH Telegram setup</title>
  <style nonce="{nonce}">
    :root{{color-scheme:dark;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#061219;color:#edf9fc}}
    *{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:#061219}}
    main{{width:min(520px,100%);border:1px solid #28515d;background:#0a2029;padding:24px;display:grid;gap:20px}}
    header{{display:flex;align-items:center;gap:14px}}.mark{{width:48px;height:48px;border:1px solid #15c9e8;color:#15c9e8;display:grid;place-items:center;font-weight:900;font-size:22px}}
    h1{{font-size:25px;margin:0 0 5px}}p{{margin:0;color:#9bbcc5;line-height:1.45}}label{{display:grid;gap:8px;color:#a8c7ce;font-weight:700}}
    .field{{display:grid;grid-template-columns:1fr auto;border:1px solid #315964;background:#07171e}}input{{min-width:0;height:58px;border:0;background:transparent;color:#fff;padding:0 14px;font:18px "DejaVu Sans Mono","Liberation Mono",monospace;outline:0}}.field:focus-within{{border-color:#15c9e8}}
    .reveal{{width:58px;border:0;border-left:1px solid #315964;background:#102b35;color:#dff8fc;font-weight:800}}button.submit{{height:56px;border:1px solid #15c9e8;background:#19bad9;color:#031419;font:inherit;font-weight:900}}button:disabled{{opacity:.5}}
    .note{{border:1px solid #28515d;padding:12px;color:#9fc2ca;font-size:14px}}.status{{min-height:48px;padding:12px;border:1px solid #315964;display:none;align-items:center}}.status.show{{display:flex}}.status.ok{{border-color:#24794c;color:#54df91}}.status.error{{border-color:#983b48;color:#ff8490}}
  </style>
</head>
<body>
  <main>
    <header><div class="mark">M</div><div><h1>Telegram botni ulash</h1><p>Post 1 uchun xavfsiz sozlash</p></div></header>
    <p>BotFather bergan tokenni telefonda nusxalang va quyidagi maydonga qo‘ying. Token faqat Orange Pi ga yuboriladi.</p>
    <label>BotFather tokeni<div class="field"><input id="token" type="password" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="Tokenni joylashtiring"><button id="reveal" class="reveal" type="button" aria-label="Tokenni ko‘rsatish">Ko‘r</button></div></label>
    <button id="submit" class="submit" type="button">Tekshirish va saqlash</button>
    <div id="status" class="status" role="status"></div>
    <div class="note">Havola bir marta ishlaydi va {MOBILE_SESSION_MINUTES} daqiqadan keyin yopiladi. Token muvaffaqiyatli saqlangach telefonda qolmaydi.</div>
  </main>
  <script nonce="{nonce}">
    const input=document.getElementById('token');const submit=document.getElementById('submit');const status=document.getElementById('status');const reveal=document.getElementById('reveal');
    reveal.addEventListener('click',()=>{{const visible=input.type==='text';input.type=visible?'password':'text';reveal.textContent=visible?'Ko‘r':'Yop';}});
    submit.addEventListener('click',async()=>{{const token=input.value.trim();if(!token){{show('Tokenni kiriting','error');return}}submit.disabled=true;show('Telegram orqali tekshirilmoqda...','');try{{const response=await fetch('{endpoint}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{token}})}});const payload=await response.json();if(!response.ok)throw new Error(payload.detail||'Token qabul qilinmadi');input.value='';show('Bot muvaffaqiyatli ulandi: @'+payload.bot_username,'ok');submit.textContent='Tayyor';}}catch(error){{show(error.message,'error');submit.disabled=false;}}}});
    function show(message,kind){{status.textContent=message;status.className='status show '+kind}}
  </script>
</body>
</html>"""


@app.get("/status")
def status() -> dict[str, object]:
    return public_status()


@app.post("/mobile/session")
async def create_mobile_session(request: Request) -> dict[str, object]:
    site_id, post_no, _ = await asyncio.to_thread(orange_identity)
    if post_no != 1:
        raise HTTPException(409, "Telegram Hub can only be configured on Post 1")
    raw = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + timedelta(minutes=MOBILE_SESSION_MINUTES)
    async with mobile_session_lock:
        prune_mobile_sessions()
        mobile_sessions[raw] = {
            "site_id": site_id,
            "post_no": post_no,
            "expires_at": expires_at,
            "attempts": 0,
            "busy": False,
            "used": False,
        }
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    request_host = request.headers.get("host", request.url.netloc).split(":", 1)[0]
    public_host = await asyncio.to_thread(local_ipv4_address) if request_host in {"127.0.0.1", "localhost"} else request_host
    mobile_url = f"{scheme}://{public_host}/api/telegram-setup/mobile/{raw}"
    return {
        "ok": True,
        "mobile_url": mobile_url,
        "qr_data_url": qr_data_url(mobile_url),
        "expires_at": expires_at.isoformat(),
    }


@app.get("/mobile/{raw}", response_class=HTMLResponse)
async def get_mobile_setup(raw: str) -> HTMLResponse:
    async with mobile_session_lock:
        mobile_session(raw)
    nonce = secrets.token_urlsafe(16)
    return HTMLResponse(
        mobile_setup_page(raw, nonce),
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Content-Security-Policy": (
                "default-src 'none'; "
                f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
                "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/mobile/{raw}/configure")
async def configure_from_mobile(raw: str, payload: MobileTokenRequest) -> dict[str, object]:
    async with mobile_session_lock:
        session = mobile_session(raw)
        session["busy"] = True
        session["attempts"] = int(session.get("attempts") or 0) + 1
        site_id = str(session["site_id"])
        post_no = int(session["post_no"])
    try:
        result = await configure(
            ConfigureRequest(
                enabled=True,
                post_no=post_no,
                site_id=site_id,
                site_name=site_id,
                token=payload.token.strip(),
            )
        )
    except Exception:
        async with mobile_session_lock:
            if raw in mobile_sessions:
                mobile_sessions[raw]["busy"] = False
        raise
    async with mobile_session_lock:
        if raw in mobile_sessions:
            mobile_sessions[raw]["used"] = True
            mobile_sessions[raw]["busy"] = False
    return {"ok": True, "bot_username": result.get("bot_username", "")}


@app.post("/configure")
async def configure(payload: ConfigureRequest) -> dict[str, object]:
    if payload.enabled and payload.post_no != 1:
        raise HTTPException(409, "Telegram Hub can only be enabled on Post 1")
    env = read_env()
    token = payload.token.strip() or env.get("TELEGRAM_BOT_TOKEN", "")
    if payload.enabled and not token:
        raise HTTPException(400, "Telegram bot token is required")
    username = ""
    if payload.enabled:
        identity = await telegram_identity(token)
        username = str(identity["username"])
    await asyncio.to_thread(sync_identity, payload.site_id.strip(), payload.post_no)
    post_id = f"POST-{payload.post_no:02d}"
    write_env(
        {
            "SITE_ID": payload.site_id.strip(),
            "SITE_NAME": payload.site_name.strip(),
            "POST_ID": post_id,
            "POST_NAME": f"Post {payload.post_no}",
            "TELEGRAM_BOT_TOKEN": token if payload.enabled else "",
            "TELEGRAM_BOT_USERNAME": username,
        }
    )
    await asyncio.to_thread(
        subprocess.run,
        [
            "chown",
            "-R",
            "rtu-wash-reports:rtu-wash-reports",
            str(APP_DIR / "config"),
            str(APP_DIR / "data"),
        ],
        check=True,
        timeout=10,
    )
    await asyncio.to_thread(set_services, payload.enabled)
    return public_status()


@app.post("/configure-auto")
async def configure_auto(payload: MobileTokenRequest) -> dict[str, object]:
    """Configure Post 1 from the protected owner API using local post identity."""
    site_id, post_no, _ = await asyncio.to_thread(orange_identity)
    return await configure(
        ConfigureRequest(
            enabled=True,
            post_no=post_no,
            site_id=site_id,
            site_name=site_id,
            token=payload.token.strip(),
        )
    )


@app.post("/identity/sync")
async def identity_sync(payload: IdentityRequest) -> dict[str, object]:
    identity = await asyncio.to_thread(sync_identity, payload.site_id.strip(), payload.post_no)
    return {"ok": True, **identity}


@app.post("/discover")
async def discover() -> dict[str, object]:
    env = read_env()
    if env.get("POST_ID") != "POST-01" or not env.get("SITE_REPORT_API_KEY"):
        raise HTTPException(409, "Post 1 report identity is not configured")
    network = await asyncio.to_thread(local_network)
    key = env["SITE_REPORT_API_KEY"]
    site_id = env.get("SITE_ID", "")
    semaphore = asyncio.Semaphore(64)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=0.7, read=1.5, write=1.0, pool=1.0),
        limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
    )

    async def probe(host: str) -> dict[str, object] | None:
        async with semaphore:
            try:
                response = await client.get(
                    f"http://{host}:8091/api/v1/health",
                    headers={"Authorization": f"Bearer {key}"},
                )
                payload = response.json() if response.status_code == 200 else {}
                if payload.get("site_id") != site_id:
                    return None
                post_id = str(payload.get("post_id") or "")
                if not re.fullmatch(r"POST-[0-9]{2,3}", post_id):
                    return None
                return {
                    "id": post_id,
                    "name": f"Post {int(post_id.split('-', 1)[1])}",
                    "host": host,
                    "port": 8091,
                    "api_key_env": "SITE_REPORT_API_KEY",
                    "enabled": True,
                    "_node_id": str(payload.get("node_id") or host),
                }
            except (httpx.HTTPError, ValueError):
                return None

    try:
        found = await asyncio.gather(*(probe(str(host)) for host in network.hosts()))
    finally:
        await client.aclose()
    local_post = {
        "id": "POST-01",
        "name": "Post 1",
        "host": "127.0.0.1",
        "port": 8091,
        "api_key_env": "SITE_REPORT_API_KEY",
        "enabled": True,
    }
    posts_by_id: dict[str, dict[str, object]] = {"POST-01": local_post}
    duplicate_ids: set[str] = set()
    for item in (candidate for candidate in found if candidate):
        post_id = str(item["id"])
        if post_id == "POST-01":
            continue
        existing = posts_by_id.get(post_id)
        if existing:
            if existing.get("_node_id") != item.get("_node_id"):
                duplicate_ids.add(post_id)
            continue
        posts_by_id[post_id] = item
    if duplicate_ids:
        raise HTTPException(409, f"Duplicate post identity detected: {', '.join(sorted(duplicate_ids))}")
    posts = sorted(posts_by_id.values(), key=lambda item: str(item["id"]))
    for item in posts:
        item.pop("_node_id", None)
    await asyncio.to_thread(write_posts, site_id, posts)
    await asyncio.to_thread(
        subprocess.run,
        ["chown", "rtu-wash-reports:rtu-wash-reports", str(POSTS_PATH)],
        check=True,
        timeout=5,
    )
    await asyncio.to_thread(restart_services, "rtu-wash-local-hub.service")
    return {"ok": True, "posts": posts, "count": len(posts)}


@app.post("/pairing")
def create_pairing(payload: PairingRequest) -> dict[str, object]:
    env = read_env()
    username = env.get("TELEGRAM_BOT_USERNAME", "")
    if not username or not service_active("rtu-wash-telegram-bot.service"):
        raise HTTPException(409, "Configure and start the Telegram bot first")
    store = pairing_store()
    if payload.reset_owner:
        store.reset_owner()
    elif store.owner() is not None:
        raise HTTPException(409, "Telegram owner is already paired")
    raw, expires = store.create_token(10, created_by="commissioning")
    link = f"https://t.me/{username}?start={raw}"
    return {
        "ok": True,
        "pairing_url": link,
        "qr_data_url": qr_data_url(link),
        "expires_at": expires.isoformat(),
    }


@app.post("/owner/reset")
def reset_owner() -> dict[str, object]:
    pairing_store().reset_owner()
    return public_status()
