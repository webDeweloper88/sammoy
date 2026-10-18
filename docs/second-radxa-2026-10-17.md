# Вторая Radxa — развёртывание 17.10.2026

## Подтверждено на плате

- Ethernet `10.10.10.7`, Wi-Fi `10.10.10.117`: один узел.
- Cubie A7A, Debian 11, kernel 5.15.147-21-a733, Docker 29.8.0 / Compose 5.5.1.
- Чистое приложение `/opt/sammoy/sammoy2`, ARM64 Docker images перенесены с первого узла.
- PostgreSQL, wash-engine, Telegram Reports и kiosk-ui healthy.
- Отдельные новые секреты приложения; `.env` root:root 0600.
- Ноль payments, rfid_cards, wash_sessions. Мойка/активация/Telegram token первой платы не переносились.
- NetworkManager adapter установлен; профили Ethernet/Wi-Fi не изменялись.
- Chromium уже находился в `/usr/local/chromium/bin/chrome`, версия 120.0.6099.224;
  пакет APT chromium отсутствует. Chromium запущен от kiosk, без `--no-sandbox`.
- Сервисы `sammoy2-post.service` и `sammoy2-kiosk.service` включены.
- Проверен автоматический рестарт Chromium после TERM, затем реальная перезагрузка
  второй платы: оба сервиса и контейнеры поднялись, `/install` доступен.
- `/launch` отправляет новый пост на `/install`, установленный на `/wash`;
  при недоступности API повторяет проверку. Browser test проверяет три случая.
- Отдельный browser-клиент проверил второй `/install` в 1080×1920:
  завершение заблокировано при отсутствии оборудования.

## Ограничения стенда

Монитор и ILITEK сейчас отключены (подтверждено владельцем). X11 сохраняет
1080×1920, но физическую картинку/касания после запуска приложения не проверяли.
HDMI, X11 transformation matrix и ILITEK устройства не менялись/не отключались.

USB–RS485 и `/dev/i2c-7` отсутствуют. GPIOchip0 есть, но назначение/подключение NV9
на этой плате не проверено. Поэтому io-helper НЕ запущен, simulation НЕ включён.
`docker-compose.factory.yml` убирает зависимость UI от отсутствующего helper;
`io_ready=false` не позволяет завершить установку. `start-post.sh` выбирает
этот режим при отсутствии обязательных device nodes. После подготовки устройств
перезапустить `sammoy2-post.service` и проверить штатный hardware stack.

Backup units установлены, но timer на второй плате отключён до запуска io-helper:
полный комплект включает журнал NV9 и без него не должен считаться готовым.
На первой плате её timer не изменён.

## До golden image

Это подготовленный стенд, а НЕ очищенный и зафиксированный golden image.
Сейчас он имеет собственные `.env`, DB и browser profile. Перед съёмом заводского
образа их нужно убрать штатным отдельным этапом, вместе с OS/SSH identity,
сетевыми привязками и данными сборщика. Не выполнять такую очистку на первой плате.

Следовать `docs/golden-readiness-2026-10-17.md`: реальные Click и межпостовые
операции не считать проверенными по browser/unit tests. Обе темы имеют успешные
browser tests, но ещё требуют физической визуальной приёмки.

## Продолжение установки: реле и активация

Проверен реальный Modbus slave 1, 9600 8N1. Все 8 выходов по одному включены
на 0.5 секунды и проверены readback; после каждого OFF все выходы выключены.
Владелец подтвердил отсутствие нагрузок. IN3 наблюдался в raw=false и raw=true
в отдельных проверках; в последнем 20-секундном наблюдении raw=true, ошибок 0,
переключений за интервал не было. Это не измерение полного отклика курка.

Второй код сервера разрешён как мойка `radxa`, пост 2. Активация выполнена,
лицензия valid/unlocked. Код и site token в документацию не записываются.

Подготовлен проверенный overlay TWI7 (SDA pin3/SCL pin5) с первой платы; добавлен
только в default entry extlinux второй платы, rescue entry сохранён. Создана
резервная копия extlinux, checksum overlay проверяется установщиком.
Нужна перезагрузка для появления /dev/i2c-7. PN532 engine-mode unit включён.

На второй плате выбран профиль `nfc-relay`: реальные реле и PN532, NV9 явно
выключен до подключения. GPIO listener не открывает линию при enabled=false;
новый флаг не ослабляет watchdog, Modbus freshness и one-hot readback.
Неподключённая денежная линия не должна создавать ложные платежи.
Проверки: 148 engine, 32 helper; 3 проверки изменения boot entry.

Владелец сообщил, что может подключить PN532. Ожидается физическое подключение
на выключенной плате и проверка адреса/firmware после загрузки. Общий кошелёк
на первом посте пока выключен; на нём имеется одна локальная VIP-карта с нулевым
денежным остатком. При настройке пары её нужно сохранить штатной миграцией,
а не удалять или автоматически считать принятой межпостовую работу VIP.

## PN532 и реальная пара

После перезагрузки появился /dev/i2c-7; PN532 ONLINE, 0x24, API firmware 1.6.7.
Реле modbus_ok=true, lastIoOk=true, lastError=null, все выходы OFF.
NV9 enabled=false, listener=false, pulses=0: GPIO не открыт для приёма денег.

Настроены главный пост 1 (10.10.10.8) и резервный пост 2 (10.10.10.7),
подтверждение операций двумя узлами, timeout визита 30 минут. Site keys совпадают
(проверены отпечатки, сами ключи в документацию не заносятся). После исправления
legacy VIP snapshot перенос завершён штатными API, синхронизация дала in-sync,
5 операций на каждом узле, pending=0. Реальные денежные переводы/карты и ручной
failover ещё не приняты.

Установка второго поста завершена, commissioning.complete=true. Backup timer
второго поста включён после появления настоящего helper/NV9 journal; первый запуск
backup service дал Result=success, ExecMainStatus=0 с restore rehearsal.
Копии пока находятся только на microSD, это не защита от отказа самой карты.

Перед настройкой пары первый пост сохранён в private backup и восстановлен в
отдельную проверочную БД. Финансовые итоги после миграции совпали; recovery 1744
не тронут. Установка/миграция не создавали тестовые денежные начисления.


### VIP occupied-post feedback fix
Signed wallet business conflicts inherited ValueError and were accidentally caught by the RPC JSON/network fallback. Preserve WalletConflict/WalletUnavailable before that fallback, including the definitive not-recorded marker. This allows existing safe rejection handling to finish a rejected grant job rather than showing transfer pending. UI maps the specific VIP-in-use rejection to localized card-in-use guidance. Regression test verifies a signed, request-bound 409 retains its type, message and definitive marker; 154 engine unit tests passed. Real simultaneous VIP retest remains required.
