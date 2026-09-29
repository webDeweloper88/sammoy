# Labrixwash owner UI — first stage

This page edits live wash parameters through the existing wash-engine API.
The installed panel is a 27-inch touchscreen in landscape, 1920 × 1080.
The visual layout follows the [Carbon form patterns](https://carbondesignsystem.com/patterns/forms-pattern/):
top-aligned field labels, a single-column account form, neutral surfaces,
and a consistent primary action. The touch keyboard is placed beside the
form at the panel's native resolution. Styles and fonts work offline.
It supports owner/admin sign-in, the required first-login password change,
three languages, all eight tariffs, free/paid pause, trigger timing and
power recovery. The page loads current values before editing and sends the
full parameter object back to the server to preserve fields not shown here.

Open `/login`, sign in with a web owner/admin account, and complete the
mandatory password change if requested. Successful sign-in opens
`/owner/parameters`. These are application accounts, separate from Linux.
Tap a text field for the on-screen keyboard (Shift, symbols, EN/RU, delete,
clear and Next); number fields have a decimal keypad. Password replacement
also requires confirmation. Physical keyboards remain supported.

The old-project customer screen used an eight-second logo hold to open
`/login`. That belongs to the customer-screen stage; the current page is
the management entry page.

Build locally with Node 22:

```sh
npm ci
npm run build
```

Touch regression checks use intercepted API responses and do not send
commands or parameter changes to a live wash:

```sh
CHROMIUM_EXECUTABLE=/usr/local/chromium/bin/chrome npm run test:touch
```

Preview on the Radxa without restarting wash-engine:

```sh
sudo docker compose build kiosk-ui
sudo docker compose up -d --no-deps kiosk-ui
curl http://127.0.0.1:8081/
```

The UI listens only on `127.0.0.1:8081` until a kiosk access method is chosen.
Saving parameters applies them immediately. Use an idle wash for the first
UI-driven check. The customer wash screen is a separate next stage.

## Owner console and installation (2026-09-29)

Owner sections: parameters, local and multi-station reports, VIP profiles/cards,
customer screen configuration, Telegram, account. All management pages support
RU/UZ/EN and persistent light/dark appearance. The management theme is local to
the browser; it does not overwrite the customer screen configuration.

The customer-screen editor preserves the complete server configuration while
editing brand, uploads, languages, program labels/visibility/colors, theme,
payment amounts and text. The customer wash screen itself is the next UI stage;
this editor is not a live preview of that unfinished screen. Its existing content
languages are RU/UZ/KZ/KY, independently of the console language.

`/install` transfers the activation-code and signed-file commissioning flows.
It uses existing commissioning APIs, requires an actual activation server/code
or signed response, and refuses activation while client credit remains. It does
not generate licences or clear balances. Nginx applies the existing commissioning
access check before forwarding these APIs. The login page links to installation.
Telegram configuration remains inside authenticated Owner/Admin access.

Validation:
- `npm run test:touch`: touch login, first-password change, decimals, 1920×1080
  and 1080×1920 compatibility.
- `npm run test:owner`: theme persistence and rendered dark color, local and
  partial multi-station reports, blocked VIP visibility, profile editing, PN532
  UID selection, unsaved navigation, settings preservation, token rotation/logout.
- `npm run test:install`: activation prevented with remaining credit, touch code
  entry and explicit installation completion confirmation.

These browser tests intercept mutation requests; they do not change real tariffs,
accounts, licences or cards. `docs/ui-owner-reports-dark-1920.png` is a fixture-data
screenshot, not a financial report from the installation.
