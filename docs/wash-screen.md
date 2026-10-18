# Screen 2 — LABRIX WASH

## Routes and scope

`/` and `/wash` mount the customer wash screen. `/login`, `/owner/*`, `/admin/*`, `/install` keep their existing flows. `/preview/idle` remains an isolated visual preview; the real customer route integrates IdleScreen and the working screen. The customer page has no management auth token and makes no direct hardware requests.

Target: 1080×1920 portrait, UZ/KZ/KY/RU with UZ default. Reference images `/opt/sammoy/source/page/01_mainPage.png` and `02_mainPage.png` are visual references only, never UI backgrounds. All segments, icons, labels and dialogs are real Vue/CSS/SVG elements.

User clarification overrides the conflicting 7/8-sector requirement: six main modes in the wheel; HAVO and vacuum below. Enabling both gives 8 total selectable programs, one gives 7, neither gives 6. Hidden/disabled main programs are also removed and the ring angles recomputed, rather than leaving empty wedges. The backend can disable any mode; UI never forces a minimum count or changes configuration to match a mockup.

## State and commands

- `/api/wash/state`: credit, active/armed/selected mode, phase, shared pause budget, trigger interlock and tariff configuration.
- `/api/kiosk/settings`: configured labels and `programs[].visible`.
- `/api/kiosk/payment-options`: read-only public Click enablement and min/max amounts; does not expose site tokens or gateway identity.
- `/api/wash/mode`: explicit program selection or `pause`. No UI use of `/wash/stop` (which can burn credit), credit mutation, simulation or output-test APIs.

`wash_logic.snapshot()` adds read-only `remainingSeconds`, `displayTimeKind` and `runtimeAgeSeconds`. Before selecting a program there is no single valid wash duration because tariffs differ: display `—:—`. During a program, available seconds are derived from current credit and that program's tariff. Free pause uses the server's shared remaining free-pause seconds. Paid pause uses the dedicated paid-pause tariff. No browser timer decrements money or estimates a second independent countdown.

Before selection BALANS is primary. Running or paused sessions use VAQT as primary and BALANS as secondary. Armed-but-not-running remains balance-first with a trigger instruction. Free/paid pause labels explicitly distinguish the time shown.

Center action: select a mode directly; no extra START command. While a program is selected, PAUZA sends mode `pause`. During explicit manual pause, Resume selects the stored `armedMode`; it remains disabled while `resumeRequiresTriggerReset` is true. Physical-trigger pauses show the appropriate trigger instruction and do not bypass the engine interlock.

State polling is serialized, every ~500ms, with a 3s timeout. Successful command responses supersede older in-flight poll responses. Missing/stale state, stale engine heartbeat, I/O faults and license locks prevent starting. Pause stays accessible for an existing selected program during an I/O fault. No automatic command retry or output restart.

The three-minute attract timer requires zero credit, no session/output, fresh healthy state and no open modal or pending payment. It accepts backend idle/no_credit/stopped phases. Incoming funds or a fault dismiss the attract screen. A wake touch does not send a program command.

## Programs, payment, language

Enable/disable modes under Owner → Parameters (tariffs); visibility/labels under Owner → Wash screen. Both tariff enablement and UI visibility must allow a program. Existing Owner labels take precedence over design fallback labels.

Cash and PN532 use existing engine event processing. The card method is a **wash card**, not a bank-card acquiring terminal. The card dialog explains existing balance-saving and VIP-session-ending behavior and shows the stable RFID result. Cash receipt closes its instructions on a new bill pulse; this UI does not add credit itself.

QR uses existing Click create/get/cancel endpoints and `qrcode.vue`, the library already used in old-project. A compact touch keypad and configured quick amounts work without an OS keyboard. A pending intent survives dialog close and page reload within the same kiosk session. `paid` is not shown as credited; wait for `credited`. Network ambiguity after creation is persisted and blocks another creation pending operator resolution. Closing a dialog does not cancel payment. Only an explicit Cancel calls the cancellation endpoint. Backend remains responsible for exactly-once financial posting.

UZ/KZ/KY/RU labels are centralized in `wash-texts.js`, reusing IdleScreen's language keys and brand text. Customer language is independent from management's settings. Entering a new idle period returns to UZ.

## Files and appearance

- `apps/kiosk-ui/src/main.js`: route entry and customer-only page styling.
- `src/kiosk/WashScreen.vue`: view composition and server-state mapping.
- `src/kiosk/ProgramWheel.vue`: data-driven rounded SVG sectors and accessible program/pause controls.
- `src/kiosk/WashIcon.vue`: local SVG paths.
- `src/kiosk/useWashState.js`: serialized polling and explicit mode commands.
- `src/kiosk/PaymentSheet.vue`: native modal, existing payment API and touch amount input.
- `src/kiosk/wash-texts.js`: four languages and fallback program names.
- `src/kiosk/wash.css`: palette in `.wash-screen` (`--wash-*`); proportional sizing in `--u = min(100vw/1080,100dvh/1920)` and grid rows. No photographic background or heavy blur.
- `src/kiosk/idle-policy.js`: fresh healthy idle/no_credit/stopped eligibility.
- `services/wash-engine/app/wash_logic.py`: read-only snapshot projection only; billing/pause/trigger branches unchanged by Screen 2.
- `services/wash-engine/app/main.py`: read-only public payment options.
- `package.json` / lock: QR dependency and test scripts.

## Verification and limits

- 48 engine unit tests, including `tests/test_kiosk_presentation.py`.
- `npm run test:wash`: touch mode selection, free-pause interlock/resume, optional visibility, four languages, QR reuse/status and network ambiguity, stale-state disabling.
- `npm run test:wash-idle`: virtual-clock 3-minute threshold, language exception, wake without command, cash arrival, funded-session guard and stale runtime.
- `npm run test:idle`, existing touch/login and Admin suites.
- Portrait screenshots: `ui-wash-balance-1080x1920.png`, `ui-wash-active-1080x1920.png`, `ui-wash-qr-1080x1920.png`. These use test API fixtures, not real money or relay operations.

The USB–RS485 adapter is absent on this Radxa. Physical relay/trigger, NV9/PN532 and real Click settlement acceptance remain required on connected equipment before claiming production commissioning. The live page accurately shows unavailable equipment; tests do not enable simulation on the station.

Deployment verified on Radxa: wash-engine healthy; `/`, `/wash`, `/login` and public payment options reachable. Click is currently disabled by configuration. Live browser verified 6 main + 2 optional controls, Russian/Uzbek switching, Help dialog, no viewport overflow and no outgoing POST requests. Hardware-unavailable state correctly prevents program starts. SHA-256/row counts of all eight financial tables match before/after deployment; protected unclaimed balance remains 1744 sum.

## Payment modal and color refinement (2026-10-06)

Compared old-project's `WashPage.vue` QR create/poll/cancel flows and the new `Balansni to‘ldirish oynasi.png` reference before implementation. The modal is real HTML/SVG: current balance, cash/Click/wash-card choices, method details and close. It keeps the existing engine ledger and API. Opening payment does not send Pause, Stop or Start; active washing continues under engine control.

Cash instructions return to wash on a new bill counter event only while hardware/state are ready and credit is positive. Baselines are reset when entering the cash/card method. Click `prepared`/`paid` remain processing, not success. Cancel is only available for `local_pending`/`pending`; `credited` shows success then returns after 1.4 seconds. Closing or switching methods keeps any unresolved intent. The next opening resumes that QR; terminal intents are cleared on reopening. Poll results started before a create/cancel command cannot overwrite its response. Unknown creation results block repeated payment creation across reloads. No fabricated QR expiry countdown.

Only Click is integrated: the reference's Payme/Uz um and bank-card wording are not advertised. PN532 is labelled wash card and retains its existing save-balance/VIP behavior. All four customer languages are supported.

The working layout and sector geometry are unchanged in this refinement. Colors: water cyan, foam amber, wax violet, osmosis rose, chemistry green, nano orange; selected mode always uses LABRIX cyan/blue. The graphite background has a subtle CSS texture. Program accents/gradients live in `ProgramWheel.vue`, background and modal styles in `wash.css`, translations in `wash-texts.js`, payment transitions in `PaymentSheet.vue`. Updated tests in `tests/wash.mjs` and screenshot `ui-payment-methods-1080x1920.png` cover the redesigned choice window and QR lifecycle.

Refinement deployed to kiosk-ui only. Browser fixtures verified redesigned method selection, cash event return without a credit POST, prepared-state cancellation guard, credited return, pending QR reuse and unknown-result persistence. UI image build succeeded; `/wash` and `/login` returned HTTP 200 after deployment. No engine restart or live payment was required for this visual/payment-dialog refinement.

## Light theme and Owner schedule

Daylight design is recreated from `Светлый интерфейс автомойки LABRIX WASH.png` using the existing UI components. `src/kiosk/light.css` defines the light screen, program, Help and payment palettes; `ProgramWheel.vue` selects light program tones. One DOM/state/command implementation is shared by both themes.

Owner → Wash screen → Station light/dark theme stores `theme.appearance` in the existing `kiosk_settings` database setting. `mode=auto` uses `lightStart` inclusive / `lightEnd` exclusive in Asia/Tashkent, default 08:00–18:00; dark is used outside this window. Overnight windows are supported. `mode=manual` uses `manualTheme=light|dark` permanently, independent of time. The chosen manual theme is retained when toggling Auto. Schedule start/end cannot match in the Owner UI. Hour and minute selectors work on touch without an OS keyboard. Existing installations without these fields default to Auto 08:00–18:00. Configuration persists through restart and is fetched every 15 seconds; automatic boundaries are evaluated using the existing page clock. A transient configuration failure keeps the last received theme.

Customer appearance is independent of the management page's own light/dark toggle. It does not alter programs, payments or the pause budget. Photo-based attract artwork keeps its photograph and readability overlays.

New files: `src/kiosk/appearance.js`, `src/kiosk/light.css`, `src/TimeSelect.vue`, `tests/appearance.mjs`, engine `tests/test_kiosk_appearance.py`. Updated: `WashScreen.vue`, `ProgramWheel.vue`, `useWashState.js`, `OwnerPages.vue`, `kiosk_defaults.py`, `tests/owner.mjs`, package scripts.

Verification: server configuration defaults, normalization and round-trip; manual and automatic boundaries in Tashkent with a browser in another time zone; live theme config changes; crossing midnight; light payment dialog palette; portrait no-overflow; Owner save/reload and touch time selection. Screenshots: `ui-wash-light-1080x1920.png`, `ui-payment-light-1080x1920.png`.

Light/Auto/Manual update deployed after confirming zero credit, no session and no requested output. Both services started successfully with wash-engine healthy. All eight financial-table hashes and row counts matched before/after deployment; unclaimed credit remains 1744 sum. Live browser matched the saved/default schedule and produced no equipment/payment commands. The rebuilt engine image passed all 51 unit tests.

## Simplified appearance selection

Owner now has one selector: Auto / Dark / Light (UZ: Avtomatik / To‘q / Och, “ko‘rinish” terminology). Selecting an option calls the Owner-only `/api/owner/kiosk/appearance` endpoint immediately. It reads the latest stored kiosk config and changes only appearance mode/manual choice; unrelated form drafts are not saved. Auto exposes the time controls; schedule edits still use Save. Dark/Light hide the schedule. Customer config refresh is now about every 1–2 seconds rather than 15 seconds. Older manual/auto stored data remains compatible. Server failures roll the selector back and show an error.

## Service footer and operator entry

Working footer is now two compact rows: configured station number and service phone, then LABRIX WASH / Telegram / Instagram / YouTube / @labrixwash. HOME and YORDAM controls were removed. Holding the header logo steadily for 6 seconds navigates to `/login`; release, leaving/moving >16px, pointer cancellation, losing focus or page visibility cancels the hold. Timers/listeners are removed on unmount. Existing login authentication is retained.

Public kiosk settings now include only `station.postNo` from installation identity (no secret/site token); no configured site means a dash, not an invented station number. Owner → Wash screen → Brand & appearance configures `contacts.supportPhone` and `contacts.socialLinks`. Only HTTPS social URLs enable a button; its native dialog displays a locally generated QR and the destination. No external browser navigation. Exact account URLs are still required from the user: empty links remain disabled instead of creating guessed QR codes.

New: `WashFooter.vue`, `tests/footer.mjs`. Updated: WashScreen, wash CSS/texts, state feed, Owner contact fields and backend public config/default normalization. Verification covers both portrait palettes, station/phone, valid and missing social links, canceled and completed 6-second holds, and absence of equipment/payment commands. Screenshots `ui-footer-dark-1080x1920.png` and `ui-footer-light-1080x1920.png` use fixture social addresses, not production account links.

Production social destinations supplied by the user are now stored in kiosk settings: https://t.me/labrixwash, https://www.instagram.com/labrixwash/, https://www.youtube.com/@labrixwash. All three QR dialogs were verified in the live UI while equipment was unavailable; six program controls remained disabled and no POST requests were sent by the UI. Only social link fields were changed; no rebuild or service restart was needed. External account ownership/content was not independently verified.

## Isolated UI preview

`/preview/wash` mounts the same WashScreen with an explicitly isolated local preview runtime (`useWashPreview.js`). A visible DEMO panel provides funded/no-credit/active/free-pause/paid-pause scenarios, dark/light selection, optional-mode visibility and test credit. Program/pause interactions use local refs; displayed timers are static for visual review. No wash/Click/hardware API is called, no production balance/config is loaded or changed, and no real payment intent sessionStorage is read/written. PaymentSheet preview shows a labelled test QR with a reserved `.invalid` destination and local confirmation/cancellation; cash/card demo credit is local. Operator logo navigation is disabled inside preview. Production `/wash` retains its real state and command feed. Verification in `tests/preview.mjs` asserts zero `/api/` traffic and preservation of a pre-existing real intent storage key, with program/pause/theme/optional/payment interactions.

Active program presentation: each selected sector uses its theme-specific program color, a solid inner outline and a soft glow when running. The status panel names the running program; paused/armed sectors keep a dashed outline without glow. The SVG geometry and real engine state remain shared across both themes. Verified all six sectors in light and dark through the isolated preview, with no API calls.

Distance visibility revision: dark active sectors use saturated fills, 8-unit outer and 5-unit inner borders, larger bold labels, and neutral neighboring sectors. HAVO/PLISOS use distinct cyan/violet filled cards in both palettes, with matching foreground contrast and a selection checkmark. Physical 2–4 m readability still needs confirmation on the installed panel.

Pause presentation: engine `pauseState=free` uses amber center and timer framing, `paid` uses orange and explicit balance-debit copy. Resume remains the action label; physical trigger/reset interlocks retain priority. `pause_free_exhausted` uses a neutral stopped state with no-charge text. Running SVG sectors render last and scale by 1.025 around their own center; other sectors use mild opacity without blur. Paused sectors retain their selection outline but no active fill. Browser verification covers both pause states in both themes and all four languages, plus real API fixture regression and isolated preview with no API requests.
