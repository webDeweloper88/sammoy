def clear_post_identity(config: dict[str, object]) -> dict[str, object]:
    return {
        **config,
        "enabled": False,
        "site_code": "",
        "site_token": "",
        "post_no": 1,
    }


def resolve_site_token(
    provided: str,
    license_config: dict[str, object],
    click_config: dict[str, object],
) -> str:
    return (
        provided.strip()
        or str(license_config.get("site_token") or "")
        or str(click_config.get("site_token") or "")
    )
