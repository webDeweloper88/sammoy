# Customer kiosk design audit — 2026-10-17

Reviewed the supplied light/dark screenshots and the running post states.

| Finding | Result |
| --- | --- |
| A disabled, nearly white play button appears when no program is selected | Replaced with readable informational guidance. Pause/resume controls render only for a selected program. No new start command or interlock change. |
| Empty status panel lacks hierarchy | Added a localized next-step heading, wallet icon and start guidance. Active, waiting, pause and fault states retain their own messages. |
| Photos are dark even away from text | Reduced upper-image shading while retaining the lower readability overlay. Original v2 WebP assets unchanged. |
| Small descriptions and long optional names | Increased description sizes; long optional labels have a dedicated smaller heading size. Owner names/program labels preserved. |
| Slanted branding differs from the rest of the interface | Unified upright uppercase heading styling for cards. |
| VIP daily allowance rejection shown as card-service outage | Observed `VIP daily limit reached` on both live posts. Mapped daily-limit, inactive and expired VIP errors to explicit messages in UZ/KZ/KY/RU. Unknown/network errors retain generic fallback. Limits and financial history unchanged. |

Validation: card-feedback checks in four languages; browser cards suite in both themes/all programs/pauses/VIP/languages; isolated status-panel suite covering zero balance, waiting, running, both pauses, card-in-use, exhausted VIP day limit and equipment fault. No equipment or financial commands in browser checks. Portrait screenshots: `ui-audit-light-empty.png`, `ui-audit-dark-empty.png`.

The temporary DEV refresh control remains enabled only in the current bench build; default release builds omit it. Physical readability at 2–4 m remains a panel-side acceptance check.
