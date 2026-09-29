from __future__ import annotations

import json

import qrcode
import typer

from app.common.config import load_hub_config, settings
from app.telegram_bot.store import PairingStore

cli = typer.Typer(no_args_is_help=True)
pairing_cli = typer.Typer()
owner_cli = typer.Typer()
cli.add_typer(pairing_cli, name="pairing")
cli.add_typer(owner_cli, name="owner")


@cli.command()
def status() -> None:
    config = load_hub_config(settings.posts_config)
    owner = PairingStore(settings.hub_database_path).owner()
    typer.echo(
        json.dumps(
            {
                "site": config.site.id,
                "configured_posts": len([post for post in config.posts if post.enabled]),
                "owner_paired": bool(owner),
            },
            indent=2,
        )
    )


@pairing_cli.command("create")
def pairing_create() -> None:
    if not settings.telegram_bot_username:
        raise typer.BadParameter("TELEGRAM_BOT_USERNAME is required")
    token, expires = PairingStore(settings.hub_database_path).create_token(settings.pairing_token_ttl_minutes)
    link = f"https://t.me/{settings.telegram_bot_username}?start={token}"
    target = settings.hub_database_path.parent / "owner-pairing.png"
    qrcode.make(link).save(target)
    typer.echo(f"Link: {link}\nExpires: {expires.isoformat()}\nQR: {target}")


@owner_cli.command("show")
def owner_show() -> None:
    row = PairingStore(settings.hub_database_path).owner()
    typer.echo("not paired" if row is None else f"Telegram user: {row['telegram_user_id']}")


@owner_cli.command("reset")
def owner_reset() -> None:
    changed = PairingStore(settings.hub_database_path).reset_owner()
    typer.echo("Owner reset" if changed else "Owner is not paired")


def main() -> None:
    cli()
