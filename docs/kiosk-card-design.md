# Второй дизайн киоска: карточки

Owner → Экран мойки → Дизайн экрана → Карточки → Сохранить.
Круговой дизайн остаётся доступен. Выбор дизайна независим от Auto / Dark / Light;
при Auto меняется только цветовая версия по установленным часам Ташкента.
Установки без нового параметра продолжают использовать круговой экран.

Основной экран карточек построен из Vue/HTML/CSS/SVG. Макеты из source/newTheme
использованы как визуальные ориентиры, не как фон или слой с кликабельными зонами.
Порядок: вода/пена, воск/химия, осмос/нано; отдельно пауза и HAVO/PLISOS.
Скрытые или выключенные программы не отображаются. Цвета программ одинаковы
в светлой/тёмной версии; работающая программа выделена полной цветной заливкой,
подписью состояния и повторяется в верхнем блоке. Во время паузы карточка
не показывает работу оборудования. Бесплатная пауза показывает время,
платная — настроенный тариф; VIP-пауза не выдаётся за денежный расход.

Логика действий остаётся общей через useWashState/select. NFC, VIP, перевод
баланса, блокировки, Click и окно оплаты используют прежние обработчики.
Окно оплаты адаптировано под палитру карточек. Приветственный экран прежний.
В футере сохранены сервисный телефон, номер поста и соцсети; доступ к login
остаётся удержанием логотипа 6 секунд. Языки киоска UZ/KZ/KY/RU.

Без оборудования можно посмотреть изолированную демонстрацию:
`/preview/wash?design=cards&theme=light` и `?design=cards&theme=dark`.
Демонстрация не обращается к API мойки и не создаёт реальные платежи.

Проверки: cards.mjs — обе палитры, восемь программ, обе паузы, VIP, четыре
языка, оплата, отсутствие переполнения 1080×1920, возврат на круговой экран
и отсутствие API в demo. Owner проверяет сохранение/повторное открытие выбора
дизайна независимо от appearance. Python проверяет нормализацию нового поля
и сохранение совместимости существующих настроек.


## Theme 2 media pack — 2026-10-17
Installed eight supplied WebP mode photographs as independent card layers and the supplied LABRIX mark. Active status panel uses the solid mode color across its whole surface, including HAVO and PLISOS in light/dark themes. Customer text, icons and actions remain live HTML/SVG. References are not used as full-screen backgrounds. Owner custom branding is retained; the LABRIX cards brand uses the provided mark. Browser checks cover loaded artwork, whole-panel colors, all programs, pauses, VIP, languages and portrait bounds without equipment/API commands.


Temporary bench refresh: build the UI with `VITE_KIOSK_DEV_TOOLS=true` to show the `↻ DEV` footer button. It only reloads the page, retaining sessionStorage/payment tracking and leaving engine/services untouched. Default builds omit it; never set this flag for the golden image. Keyboard alternative in kiosk: Ctrl+R (Ctrl+F5 for a full refresh).


## Full-photo cards and transport icons — 2026-10-17
Mode photographs now cover the full card with a dark readability overlay in both themes. Inactive cards use neutral borders; selection has a mode-colored outline and trigger guidance, actual running adds a color wash and a labeled dot. Removed navigation chevrons and icon tiles. Optional air/vacuum cards use the same photo treatment and distinguish waiting from running. Pause/play/stop are filled SVG geometry; stop is a distinct square icon, not a new equipment action. Pause/free/paid/stopped colors retain existing business states and the pause/resume interlock is unchanged. Browser checks cover full-width media, no chevrons, both themes/all modes, filled pause and play icons, pauses/VIP/languages/viewport.


## Unified status panel — 2026-10-17
Replaced the saturated program tile with one shared status surface: large time/balance on the left, program title/icon and short localized running label on the right. Mode color appears only in the icon, dot and slender divider accent. Waiting has trigger guidance without a running dot; free/paid pauses show their state and remaining timer or configured price, with separate amber accents. Card, recovery and safety messages keep priority. Cards and isolated status-panel browser tests passed for light/dark, optional programs, waiting, both pauses, conflict and hardware-fault states without financial/equipment commands.


## Media pack v2 — 2026-10-17
Replaced the eight reference crops with supplied horizontal WebP renders: six main programs at 1600×700 and air/vacuum at 1600×500. Assets use a new `modes-v2` path to avoid stale browser caching. Original files are copied without recompression; full-card cover, shading, live labels and icons remain CSS/SVG. Browser checks require all eight images to load at their native dimensions in both themes.


## Status background scene — 2026-10-17
The status panel uses a full-width photo of the selected/armed program. While idle, a clean-car detail from the supplied nano render provides a neutral welcome image without indicating program selection. A dark horizontal scrim protects left-side monetary/time data and fades to transparent at 72% width; the right side keeps the unfiltered photo. Small caption backplates preserve text contrast without shading the whole right half. Both palettes keep white status data on the dark left. Free/paid pauses retain the armed mode photo; hardware/card alerts retain priority.


## Wheel status color gradient — 2026-10-17
The circular design uses the selected mode color, without photography, for its upper status surface. The left scrim is white with dark numerals in the light theme and dark with white numerals in the dark theme; it fades to the unobscured mode color before right-side labels. Right-side foreground is selected by contrast against the actual mode color. Both themes retain the wheel mode palette; no selection/fault uses a neutral tone. Armed program color is retained during free/paid pauses, with a pause icon and the existing status/alerts. Cards retain their photographic status scene. Isolated browser verification covers all eight colors in both themes, neutral state, pause states, portrait bounds and absence of images/equipment commands.


### Softer wheel gradient
Expanded the transition from the narrow 46–58% band to eased stops across the full width (0/20/35/50/65/82/100%). Light still begins with a white surface and dark numerals; dark begins with a dark surface and white numerals. Foreground on the right now considers both the blended background at the start of the copy and the final program color.
