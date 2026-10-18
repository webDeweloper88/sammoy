# LABRIX WASH: Screen 1

Target: portrait 1080×1920. Languages: UZ (default), KZ, KY, RU.

Current implementation is a design preview at `/preview/idle`. It does not replace `/login`, management pages, or operate hardware. Waking the preview shows an explicitly labelled preview exit, not a functioning wash screen.

Original images were copied unchanged from `/opt/sammoy/source` into `apps/kiosk-ui/public/branding/labrixwash-logo.png` and `labrixwash_idle_hero_1080.webp`. The logo preserves its proportions; the hero uses a centred cover crop with a soft gradient. Both images are served locally.

Components:
- `src/kiosk/IdleScreen.vue`: portrait presentation, touch wake, four language buttons, bounded wake-gesture click suppression.
- `src/kiosk/idle-texts.js`: customer-facing translations.
- `src/kiosk/idle-policy.js`: `IDLE_TIMEOUT_MS = 180000`, fresh-state eligibility.
- `src/kiosk/useIdleScreen.js`: lifecycle-managed timer. To integrate with the future customer wash screen, supply reactive state, the time of its last successful receipt, and payment-pending state. Render IdleScreen when `visible`, connect its wake event to `wake`, and share the customer language. No extra hardware API or financial calculation belongs in this component.
- `src/kiosk/IdlePreview.vue`: isolated design review route; intentionally bypasses the inactivity timer and equipment availability for review.

The production timer requires a fresh idle state, zero credit, working I/O, no active session/output, no license lock, no pending payment or recovery. Credit changes and stale state dismiss the screen. Global listeners and timer are removed on unmount. Existing pause logic is unchanged.

Validation: `node tests/idle.mjs` with CHROMIUM_EXECUTABLE pointing to Chromium; `npm run build`. Screenshot `ui-idle-layout-1080x1920.png` documents the branded portrait layout using the supplied original images.

Pending: user visual review and customer wash-screen integration. The preview is independently deployable. Management portrait review is a separate outstanding task.

Updated composition: compact horizontal HTML wordmark replaces the square logo; the photograph occupies 51% of the portrait height. CTA has restrained cyan edging and a separated touch icon; footer has a quiet divider. The new reference photograph with the large physical overhead sign has not yet been supplied as a local file, so the original hero remains in use. Once that source is provided, remove the separate wordmark region to avoid duplicating the sign.

Visual revision: flat graphite background, uncropped-in-color photograph without gradient overlays, off-white CTA with dark lettering, 10px corners, no glow or pulsing. Cyan is limited to branding/language accents. This supersedes the earlier gradient and cyan-border CTA treatment. Portrait/touch tests repeated for this revision.

Latest visual adjustment: the photograph blends into the same graphite background at both vertical edges using a local CSS gradient overlay. Removed the header divider. The central car/terminal remain unobscured; the flat light CTA is unchanged. This supersedes the hard photo edges from the previous revision.

CTA refinement: transparent surface continuous with the graphite background, restrained grey outline, 16px corners, white title, muted subtitle and cyan touch icon. A filled pressed state provides touch feedback. No glow/pulse. This supersedes the light CTA.

Full-viewport portrait layout prepared: images with natural height/width >=1.5 activate a grid-overlapped full-screen photograph, transparent header and local top/bottom shading. Text starts at 73% of viewport height to preserve the car in the proposed reference. A geometric portrait fixture verifies full-viewport geometry and language controls; the actual white-car portrait file is still missing from `/opt/sammoy/source`. Changes are built locally, not deployed pending the real asset and visual review. Expected source filename: `labrixwash_idle_portrait.webp`; copy into public branding and update the component/preload URL when available.

Portrait source received as `/opt/sammoy/source/abrixwash_idle_portrait.webp` (1080×1920). Copied unchanged to `public/branding/labrixwash_idle_portrait.webp`; component and preload now reference it. Full-screen composition visually reviewed with actual white-car photograph; portrait touch/language/geometry tests passed. This supersedes the missing-source limitation above.
