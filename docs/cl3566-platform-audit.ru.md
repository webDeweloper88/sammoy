# Аудит поддержки CL3566 и Cubie A7A

Дата:2026-10-27. Исходники: e2bfe3b. Аудит чтения исходников; оборудование/работающие посты этим аудитом не изменены. Документ описывает предлагаемую реализацию, не готовую поддержку CL3566.

## Вывод

Существующий hardware profile выбирает набор сервисов/режим поста, а не аппаратную платформу. Простая замена YAML-портов недостаточна. Нужен независимый подтверждённый board profile, транспорт PN532 UART, источник GPIO vendor sysfs и согласованная поддержка установщика, запуска, выпуска/OTA. Общие бизнес-API, фильтры денег и журнал импульсов сохраняются.

## Найденные привязки

|Участок|Фактическое поведение|Изменение для CL3566|
|---|---|---|
|`.hardware-profile`, deploy/start-post.sh|full/nfc-relay/relay-only/dry-fog/factory-only; проверка ttyUSB0,gpiochip0,i2c-7; при отсутствии заводской UI|Не переопределять старые значения; отдельный board-profile и единый resolver файлов Compose/required nodes|
|docker-compose.yml,config/io-map*.yaml|Жёсткие device mounts ttyUSB0,gpiochip0,i2c-7; NFC bus7,Modbus ttyUSB0|Профиль CL3566 с ttyS7,ttyS9 и узко ограниченным доступом к vendor GPIO; проверять итоговый Compose без старых обязательных devices|
|deploy/apply-commissioning-profile.py|Требует именно три устройства Radxa|Проверки по подтверждённой модели, а не глобальный список|
|deploy/apply-device-profile.sh|Переключает wash/dry_fog и Compose; сохраняет bill config, требует отсутствие сессии и OFF proof|Сохранить interlocks и тип поста; не потерять transport/source CL3566 при смене wash/dry_fog|
|services/io-helper/rfid.py,pn532_linux.py|Только LinuxI2cPn532; state/log привязаны к bus/address|Фабрика transport i2c/hsu; общий формат UID/SAK/ATQA, release/de-dup и NFC phone protection без регрессий|
|services/io-helper/main.py:nv9_listener|Всегда gpiod chip.get_line/request, API мониторинга ожидают line/event методы|Абстракция источника уровня; отдельный vendor sysfs adapter, совместимые diagnostics и lifecycle|
|bill_process_reader.py|Читает приватный gpiod FD и GPIO v1 ioctl|Нельзя просто передать sysfs FD; отдельный изолированный read-only sampler либо обобщение child reader с явным backend|
|services/io-helper/hardware_profile.py|Валидирует тип wash/dry_fog и safety для dry_fog|Не смешивать модель платы и тип услуги|
|apps/kiosk-ui/src/InstallHardware.vue|Инструкция подключить USB, кнопка Apply; выбора модели нет|Показать найденную/неизвестную модель, ручной выбор, явное подтверждение и точные ошибки оборудования; RU/UZ/EN|
|deploy/install-software-updates.sh,golden/first-boot-updates.py|Запуск разрешён только compatible radxa,cubie-a7a, marker cubie-a7a|Provisioning по подтверждённой плате, не устанавливать Cubie marker на CL3566|
|deploy/update_protocol.py и wash-engine/app/update_protocol.py|Допускается только manifest hardware=cubie-a7a|Согласованный allowlist известных платформ, сохранение точного совпадения с локальным marker|
|deploy/software-update-agent.py|Проверка hardware+arch, allowlist Compose, backup .env/.hardware-profile/compose|Добавить новый Compose, board selection и нужные host resources в backup/restore/rollback; существующую проверку совместимости не убирать|
|scripts/build-software-release.py|hardware=cubie-a7a жёстко в manifest|Явный обязательный target для нового выпуска, подпись связывает target с артефактом; прежний путь Cubie сохраняется|
|wash-engine/app/main.py:read_microsd_cid|Первый доступный mmcblk CID; название microSD, но eMMC тоже может попасть|Не менять действующие fingerprints Radxa; проверить стабильность eMMC identity на CL3566 с/без SD до активации лицензии|

## Контракт платформы (предложение)

- Отдельные board IDs `cubie-a7a` и `cl3566-a-e` (новый ID требует согласованного включения gateway/каталога OTA).
- Независимые оси: модель платы, тип wash/dry_fog, роли primary/backup, provisioning factory/commissioned.
- Декларативный каталог с version, fixed known port paths/driver backend, required resources, NFC/bill capabilities. Клиент передаёт ID из allowlist, не произвольные sysfs-пути или shell-команды.
- Хост хранит атомарную запись selected/confirmed board ID +schema; backend/UI читают её через ограниченный интерфейс. Неподтверждённый выбор не открывает денежные операции.
- Автоопределение — только предложение. `Rockchip RK3566 EVB2` не уникален CL3566; учитывать vendor hw_rev и driver signatures как evidence, при неоднозначности просить выбор. Не доверять одному ttyS7 как доказательству модели.
- Подтверждение не меняется автоматически при reboot/update. Смена платформы только отдельным административным действием на остановленном посту с backup и OFF/readiness проверками.
- Legacy Cubie migration: явно различать existing commissioned legacy deployment и fresh unknown board; сохранить старый рабочий путь без автоматического применения Cubie к неизвестному железу.
- Разные hardware manifests для OTA. Общие ARM64 application images возможны, но это не делает host BSP/ядра/профили взаимозаменяемыми. OTA не заменяет vendor kernel/bootloader.

## Проверенная конфигурация CL3566

RS485 ttyS7,9600/8N1,slave1,coils0..7,8реле поочерёдно проверены без нагрузки.
PN532 V3 HSU ttyS9,115200/8N1,OFF/OFF; firmware1.6 и карта прочитаны. Важен combined wake:55 55+12zero+GetFirmwareVersion в одном write. Проверить холодный старт/повторное соединение, finite polling и обработку ACK/NAK/частичных кадров. UID/SAK/ATQA извлекаются из одного target response.
Bill IO1 physicalpin8=IO5=GPIO4_C6,gpiochip4offset22; владелец jwsioc_a. Sysfs external_gpio mode0=input,1=output; rawlevels. PC817 activeLOW; реальная серия10пульсов≈50ms LOW/100ms HIGH. Не использовать этот единичный тест как доказательство production sampler.
Подробные местные документы: /opt/sammoy/docs/cl3566/CONNECTIONS.md и HARDWARE-AUDIT.md. В них нет полного номинального монтажа PC817/подтяжек.

## Последовательность реализации и проверки

1. Каталог и resolver board profile +readonly host detection. Тесты unknown/ambiguous/spoofed model, manual confirm, legacy Cubie compatibility; без deployment.
2. PN532 HSU transport, сохранить I2C. Проверить framing/CRC-checksum/ACK/timeout/close/reconnect, card metadata и запрет ISO-DEP денежных операций существующей политикой. Не вводить регистрацию карт как новое требование.
3. Vendor GPIO level source и изолированный sampler. Сохранить PulseJournal/BillFilter/cash semantics; fail closed при отсутствии источника/изменении direction, не придумывать потерянные импульсы. Проверить jitter/backpressure/ошибки read, shutdown, startup active/stuck и длительные серии под нагрузкой. Доступ к sysfs только разрешённой линии.
4. Compose/start/apply и host input preparation. Исправить ранний outputLOW до systemd input: DT/подтверждённый vendor способ и электрическая проверка. Не считать userspace oneshot достаточной гарантией безопасности холодного старта.
5. Установщик RU/UZ/EN: модель/ручной выбор/подтверждение →readiness →отдельные безопасные аппаратные тесты. До разрешения эксплуатации выходы остаются OFF, деньги не принимаются; это включает аппаратное inhibit/блокировку купюроприёмника, если доступно. Одного программного игнорирования импульсов недостаточно, если купюра физически принята.
6. OTA/gateway/release: типизированный target, подпись, runtime compatibility, persisted board config, rollback. Проверить пары Cubie←CL и CL←Cubie как отказ, успешные обновления каждого target и возврат host/application конфигурации.
7. Cold-power acceptance и интеграция без клиентов на CL3566. Только после доказанных тестов — отдельный заводской image и release CL3566. Существующие Cubie посты не обновлять экспериментальной сборкой.

## Дополнительные границы

- Производственное ядро Debian CL3566 ещё не проверялось на все необходимые Docker/cgroup возможности. Наличие containerd не доказывает возможность работы текущего стека.
- Не переносить Cubie image resize/boot scripts на eMMC RK3566.
- Vendor Chromium132 wrapper добавляет свои флаги; это отдельный kiosk/browser вопрос, не повод менять рабочее ядро в аппаратном патче.
- В аудите не запускались аппаратные команды, обновления, установка зависимостей или тесты со сторонними эффектами. Требуемые функциональные тесты перечислены для последующей реализации.

## Уточнение: лицензирование eMMC (согласовано 2026-10-27)

CL3566 эксплуатируется с внутренней32GB eMMC, без обязательной microSD. Лицензионную поддержку включить в обязательный объём, до активации новой платы.

- Действующие лицензии/fingerprints Cubie A7A сохранить побайтно совместимыми; никаких массовых пересчётов.
- Для CL3566 выбирать CID именно встроенной eMMC, а не первого mmcblk. Источник определять по sysfs type=MMC, топологии и фактическому root device; не полагаться только на номер mmcblk0. Обрабатывать неоднозначность/отсутствие явной ошибкой, не случайным fallback.
- Read-only проверить наличие eMMC CID и стабильных board identifiers на реальной плате; логировать наличие/тип источника, не сырой CID/MAC. Выбрать итоговую комбинацию только после проверки данных и API gateway; наличие надёжного уникального board ID пока не доказано.
- Добавить версионированный identity scheme для CL3566 с согласованной реализацией labrixpay, сохранением старой схемы Radxa и signed activation semantics. Не менять только клиентскую сторону.
- Идентификатор не должен меняться от вставки/извлечения временной microSD, смены IP, application update или клонирования golden image на ту же плату. Поведение при замене eMMC определить как явную процедуру переноса лицензии.
- Golden image не содержит license token/fingerprint предыдущего устройства, активированной базы или уникального device identity; получать identity локально на новой плате.

## Поэтапный порядок исполнения

|Этап|Результат|Проверка перед завершением|
|---|---|---|
|1. Основа платформ|Каталог cubie-a7a/cl3566-a-e, evidence-based detection, сохранённый подтверждённый выбор; legacy migration policy|Unknown/ambiguous не активируется; manual confirmation валидируется; существующий Cubie сохраняется|
|2. Лицензирование|Определение eMMC identity +версионированная поддержка gateway без обязательной SD|Legacy fingerprint без изменений; CL3566 с/без SD стабилен; отсутствие/неоднозначность — отказ; image не клонирует license|
|3. NFC|PN532 HSU драйвер с общими metadata/event semantics|Firmware/card/reconnect/cold boot, фильтр телефона, I2C Radxa без регрессий|
|4. GPIO|Vendor IO5 input +изолированный считыватель, сохранённый журнал и фильтры|Полные серии разных купюр под нагрузкой; timeout/backpressure/stuck; отсутствие ложного начисления; cold-power input timing|
|5. Применение оборудования|CL3566 Compose/start/apply/ограниченные разрешения|Реле OFF на старте/сбое, правильные mounts, wash/dry_fog не теряют board settings, Docker kernel support|
|6. Установщик|RU/UZ/EN модель/ручной выбор/подтверждение/readiness|Ошибочный профиль блокирует запуск; подтверждение не изменяется после reboot/update; отдельный тест оборудования|
|7. Выпуски и OTA|Target-aware build/sign/gateway/update/rollback|Отказ cross-board update, backup/restore board profile и identity scheme, оба поддерживаемых target|
|8. Приёмка и golden image|Отдельный CL3566 image и полный журнал стендовой приёмки|Холодный старт, установка чистого поста, лицензия eMMC, деньги/NFC/реле, обновление/откат; Radxa контрольные регрессии|

Статус после обновления плана: аудит завершён; реализация этапа1 ещё не выполнена. Согласованный объём — выполнять последовательно, фиксируя изменения и проверку каждого этапа. Не смешивать реализацию с развёртыванием на работающие посты.

## Результат этапа1 — основа реализована

Добавлены deploy/board_profiles.py и deploy/test_board_profiles.py. Stdlib-каталог двух платформ, readonly detection с evidence, CLI административного подтверждения и атомарный schema1 record /etc/labrix/board-profile.json (0600, lock, fsync). Отказ при конфликте обнаруженной модели/выбора, ambiguous evidence, повреждённом record, неизвестном ID и попытке заменить уже подтверждённую модель. Повторное подтверждение той же модели сохраняет исходную запись. Detection сам ничего не подтверждает и не активирует.

10 unittest прошли. Readonly smoke: текущий хост определяется cubie-a7a по compatible;10.10.10.26 определяется cl3566-a-e по hw_rev CL3566-A-V3.0 +jwsioc_a, несмотря на общий model EVB2. Ни на одной плате selection не записывался, CLI --confirm не запускался. На CL3566 скопирован только диагностический файл /home/admin/labrix-board-profile-check.py. Работающие сервисы не менялись.

Граница этапа: это самостоятельная основа, ещё не подключённая к действующим installer/start/OTA. Старые Cubie пути оставлены без изменений; автоматической миграции ещё нет. CLI confirmation записывает выбор, но НЕ включает оборудование и НЕ заменяет дальнейшие commissioning/idle/off readiness interlocks. UI integration — этап6, host apply — этап5. Следующий этап2: версионированная лицензия eMMC и gateway compatibility.

Проверка: `python3 -m unittest discover -s deploy -p test_board_profiles.py -v`. Readonly диагностика: `python3 deploy/board_profiles.py`. Не запускать --confirm на рабочем посту как замену полноценному commissioning.

## Этап2 — реализация eMMC identity

Добавлен app/storage_identity.py: scheme cl3566-emmc-v1, ровно один non-removable typeMMC, валидный32hex CID, отсутствие fallback на SD/второй sysfs root при неоднозначности. WLAN+CID остаются двумя компонентами; уникальный дополнительный boardserial не предполагался. Все3хеша разделены scheme domain. Транспорт лицензии и signed offline contract сохраняют три старых поля; microsd_cid_hash для CL3566 — исторический wire alias хеша eMMC. Схема различается формулой хеша, без нового поля БД/изменения OC1. Не выдавать alias за наличие физической microSD.

main.py использует новую формулу только при подтверждённом board-profile.json; неизвестный/повреждённый выбор или vendor CL без выбора даёт complete=false. Legacy Cubie formula сохранена. Чтение board record в контейнере требует будущего readonly mount на этапе5 (либо host environment-controlled path LABRIX_BOARD_PROFILE_FILE); mount ещё не добавлен, профиль на плате не подтверждался и лицензия не активировалась.

Проверки:11 identity tests PASS, включая legacy hash compatibility и SD insertion fixture. Реальная CL3566: eMMC identity complete=true и повторные результаты равны, сырые CID/MAC и хеши не выводились. Стабильность после coldboot и реальной вставки SD ещё не проверена.

labrixpay: контракт opaque hash уже совместим; DBmigration не нужна. Подготовлены нейтральные сообщения storage/controller и RU/UZ/EN подпись CID microSD/eMMC.4новых теста контракта eMMC, активации/замены и offline binding. Вся доступная suite:29 PASS,10OTA DB integration SKIP. VPS SSH admin сwash_gateway отклонён publickey; публикация серверных правок не выполнена, запрошен агент. Денежные таблицы, платежи и действующие лицензии не изменялись.

### Публикация серверных правок

После предоставления пользователем файла парольной фразы ключ разблокирован через временный SSH_ASKPASS (содержимое не выводилось; файл секрета chmod600). VPS исходники совпали с базовым18d6a72. Сохранены /opt/labrix/backups/emmc-license-20261027/source-before.tar.gz и image pay-gateway-app:before-emmc-20261027. Обновлены только source app и документация/тесты; финальный образ производный от предыдущего runtime image, зависимости сохранены. Перезапущен толькоapp безpostgres. Локальный и публичный HTTPS /ready=200,ok=true,checks migrations/backup/payment_delivery/click_signatures=true. Изменения схемы БД/лицензий/платежей не выполнялись. Live активация CL3566 ещё не проводилась.

Контрактные4теста в production image PASS. Полная unittest discovery в этом image выявила отсутствие test-only httpx для импорта OTA TestClient, поэтому эти DB integration тесты там не запускались; в локальном изолированном тестовом окружении результат29PASS/10SKIP. Рабочие зависимости для тестов не менялись.

## Этап3 — PN532 HSU driver candidate

Добавлен services/io-helper/pn532_hsu.py на stdlib Linux UART:exclusive open,115200/8N1,combined wake, bounded normal frames/ACK/NAK/checksums, partial reads, write/read deadline, finite passive retry,timeout cancellation,close/restore. Используется общий контракт firmware_version/SAM_configuration/read_target_info/close. rfid.py выбирает transport i2c(default,старое поведение) или hsu; события UID/SAK/ATQA и de-dup/release не изменены. Неизвестный transport — ошибка, не fallback.

15тестов PASS (PTY fragmented serial +timeouts/checksums/cleanup +legacy I2C +HSU event metadata). На реальной CL3566 кандидат проверен2цикла open→firmware1.6→SAM/RF configuration→5polls без карты→close, без ошибок на timeout0.25сек. Только файл драйвера скопирован в /home/admin/labrix-driver-test; production application/config на плате ещё не развёрнуты. Отдельный180sec монитор candidate запущен для проверки пластика/телефона, результат ожидается. Ранее карта читалась диагностическим скриптом, а не этим новым модулем. Cold-power/reconnect under failure и финансовый phone filter в полном приложении требуют интеграционной проверки.

### HSU candidate card/phone bench result

User presented plastic then phone during candidate monitor session6405. Plastic:SAK08,ATQA0004,UID4bytes,ISO-DEPfalse; removal detected. Phone:SAK20,ATQA0004,UID4bytes,ISO-DEPtrue; removal detected. No raw UID logged, no wallet operations. Confirms candidate HSU driver supplies metadata needed by existing phone policy; actual financial rejection must still be tested through integrated application. This is not a universal phone classifier. Stage3 driver bench checks passed; cold-power and full-app integration remain acceptance work.

## Этап4 — vendor GPIO candidate

Добавлен bill_vendor_gpio.py:фиксированный IO5, readonly O_NOFOLLOW value/mode FDs, direction=input проверяется при каждом чтении, некорректный уровень/режим вызывает ошибку; ни записи GPIO, ни gpiod request. bill_process_reader.py расширен backend vendor-sysfs с передачей только value/mode FD в отдельный sampler; прежний gpiod backend остаётся default. VendorProcessLevelReader использует прежний bounded stream/queue/timeout/failure handling и поддерживает reconfigure. nv9_listener выбирает source vendor-sysfs и level-process, общие BillFilter/PulseJournal/API остаются прежними. Файлы закрываются и при ошибке initial filter setup.

51тест предыдущих sampler/filter/API+vendor PASS; дополнительный integration test vendor listener→filter→durable journal200пульсов PASS, после reopen journal200. Отдельные5vendor tests включают реальный дочерний процесс, mode change failclosed, readonly descriptors и invalid/missing file. Production map/compose ещё не применялись, hardware bootinput проблема не объявлена решённой.

На CL3566 скопированы только кандидатные модули в /home/admin/labrix-driver-test. Запущен180sec bench script с production sampler/filter и временной disposable SQLite, без связи с backend или балансом. Пример сценария /opt/sammoy/docs/cl3566/tools/check-bill-candidate.py. Реальная серия купюры ожидается. Результат диагностического считывателя ранее не заменяет приёмку этого нового пути.

### Vendor GPIO candidate real50000sum test

User inserted50000sum in restarted bench session58086. Production-candidate isolated vendor-sysfs sampler +existing BillFilter +disposable PulseJournal accepted exactly50pulses. At pulse50:filteraccepted50,rejected{},uncertaingaps0,readererrornull,queued0,maxsamplegap2.604ms. Wallet/backend not involved. Single bill bench passed; production load endurance, host permissions/Compose and coldpower input initialization still pending. No inference of missing pulses or filter bypass used.

## Этап5 — интеграция запуска CL3566

Добавлены docker-compose.cl3566.yml и cl3566-fog overlay, отдельные io-map.cl3566*.yaml (cashdisabled до commissioning), board_runtime.py resolver, apply-cl3566-profile.py, install-cl3566-host.sh и host IO5input unit/script. Два tty device mounts толькоS7/S9; vendorGPIO каталогreadonly; boardrecordreadonly в engine. Start-post оставляет прежнюю ветку Cubie и делегирует confirmedCL отдельномуresolver. Admin system actions используютresolver; commissioning nodes проверяются по модели. ApplyCL сохраняет idle/wallet/OFFreadback interlocks, старый billconfig vendor backend, marker/map rollback, подтверждает engine type/IO readiness. Выбор типа услуги независим от board ID. OTA allowlist обновится на этапе7,не считать поддержку OTA CL уже готовой.

Реальная плата: Docker20.10.24 был установлен, но не стартовал с nftiptables:vendor kernel CONFIG_NFT_MASQ disabled, legacyMASQUERADE built-in. Сохранён backup /home/admin/labrix-docker-backup-20261027-223130, switched толькоiptables alternative→legacy (правила не очищались). Dockerstart PASS,overlay2,cgroupv2; ARM64hello-world PASS. Установлен ARM64Composeplugin из текущегохоста, версияv5.5.1; docker autostart включён. Ядро не менялось.

Из новой io-helper code собран отдельный image tag cl3566-candidate на существующих зависимостях,передан на плату. Стендовый контейнерlabrix-cl3566-io-bench запускался безnetwork/hostports/restart,configcashfalse,tempjournal. Реальный/io:modbus_ok=true,all8outputsfalse,nv9_enabledfalse;PN532 firmware1.6. В этомконтейнере VendorProcessLevelReader получил817samples за2сек,maxgap2.403ms,0uncertain,0errors. Контейнер затемостановлен,shutdownOFF выполнен; приложениепользователей/engine/db наCL ещё не разворачивались.

Проверки14board/runtime tests,3applyCL guards,3existing commissioningtests,9existingadminsystemtests PASS;Compose resolveddevices exactlyS7/S9,sysfs/boardmetadatareadonly;shsyntax/diffcheckPASS. Полный applyCL с engine пока не прогонялся. Hostbootstrapinputunit код подготовлен,но ещё не установлен наCL; прежняярабочаяlabrix-io5-input.service остаётся. Раннее GPIOoutputLOW отvendorDT доuserspace не устранено; нужна отдельнаяcoldpower/электрическаяпроверка передприёмомденег.

Следующийэтап6: UIвыбормодели,confirmedprofileиcommissioningcashgate, затем развёртываниеполногостека наCL и интеграционныепроверки. Не объявлять этап5 полнымproductiondeployment.

## Этап6 — установщик и полный заводской стек на CL3566

Добавлен InstallBoard (RU/UZ/EN): обнаруженная модель, явный выбор/подтверждение, receipt/retry и блокировка продолжения до подтверждения. Host API принимает только два фиксированных board action; подтверждение разрешено только на незавершённом посту без активного/денежного сеанса. Существующий подтверждённый профиль не заменяется. Добавлены 3 API tests PASS; 14 board/runtime и 9 admin-system tests PASS; повторный runtime suite 4 PASS. UI production build PASS, git diff check PASS. Browser fixture обновлён, но полный Playwright сценарий пока не запускался.

На 10.10.10.26 развёрнут чистый application stack без исходных клиентских данных: postgres, engine, UI, reports healthy. Новый .env содержит отдельные случайные служебные секреты; начальные Owner/Admin labrix по согласованному требованию. /install HTTP200; nginx API board возвращает suggested cl3566-a-e, selection=null. Установлены admin-system/admin-network и factory stack autostart. Kiosk открыт на http://127.0.0.1/install. Network service установлена без изменения сетевых профилей. Board confirmation, site activation, hardware apply и завершение установки НЕ выполнялись.

Vendor kernel оставил nft FORWARD DROP после неудачного запуска Docker с nft backend. Для CL overlay задан стабильный bridge labrix-cl3566 и адресные nft исключения в cl3566-network-compat.py, глобальные правила не очищались. Связь engine/postgres восстановлена; все четыре контейнера healthy. Host IO5 input unit установлен до Docker; ранний vendor DT output LOW до userspace остаётся открытым вопросом cold-power приёмки.

Попытка автоматического DOM smoke через vendor Chromium headless невозможна: сборка сообщает Invalid ozone platform: headless. Обычный kiosk Chromium запущен с /install. Визуальная проверка нового выбора модели ожидает пользователя. IO helper в factory режиме не запущен, cash maps disabled. Следом: пользователь подтверждает CL3566-A-E в установщике, затем проверяем eMMC identity и аппаратный apply. OTA allowlist/полная интеграционная и coldboot приёмка остаются отдельными этапами.

## Минимальная ОС и восстановление autostart

После жалобы пользователя проверен reboot: GPIO service failed, Docker зависимость не запускалась, Chromium оставался на ERR_CONNECTION_REFUSED. Выявлено отсутствие автоматической загрузки vendor jwsioc (поставляется /lib/modules/jwsioc.ko вне versioned tree). Startup script теперь явно insmod при отсутствии модуля и затем подтверждает IO5=input; ожидание60sec/timeout90. Ошибки не игнорируются.

Установлен Openbox без recommends, LightDM переключён на отдельный labrix-cl3566 session; сохранены vendor Chromium, Xorg/libinput, сеть/SSH, kernel/firmware. Удалены19явных XFCE desktop/application packages без autoremove; список и план сохранены /var/lib/labrix/os-cleanup. Apt cache очищен. Новая сессия ожидает доступности /api/commissioning/state до запуска browser. Экран right и ILITEK calibration сохранились после LightDM restart. Проверка повторного reboot после module fix продолжается.

Повторный reboot после module fix PASS: docker/post/input/lightdm active; четыре контейнера healthy; /api/commissioning/state ok=true,complete=false; Openbox и Chromium /install запущены; IO5 direction0=input; ILITEK calibration right сохранилась. Root использовано6.5G,доступно21G. Физический cold-power и экранная проверка пользователем ещё нужны; commissioning не завершён.

### Графический экран запуска и курсор
На CL установлен прежний LABRIX boot.html/logo из Radxa minimal-kiosk: локальная file page, RU/UZ startup text, анимированная полоса, переход /launch при доступности UI. XFixes hide-cursor.py включён в session с cleanup. LightDM restart PASS, hide-cursor process active, Chromium initialURL local boot.html, /launch HTTP200. Ранний vendor bootloader/kernel splash не менялся; отсутствие стандартных Plymouth/update-initramfs и boot layout CL не позволяют применять Radxa install-splash.sh напрямую. Визуальная приёмка ожидается.

### Исправление перехода после board confirmation
Пользователь подтвердил CL3566 и сохранил static10.10.10.26. Backend board confirmed, eMMC identity complete, network pending=null, баланс0/сеансовнет. Найдена UI race: InstallBoard emits ready во время hardwareBusy, родитель run(load) игнорирует refresh. Добавлен onBoardReady с прямым refresh, не обходящим остальные action interlocks. Production UI build PASS, diff check PASS. На CL заменён только kiosk-ui image, предыдущий tag before-board-refresh сохранён; browser перезапущен для новых assets. База/сеть/роли/оборудование не менялись. Проверка кнопки на физическом экране ожидается.

### Клавиатура в диалогах управления
Пользователь обнаружил, что SystemControls reboot dialog перекрывает inline auth keyboard. TouchKeyboard теперь при focus в role=dialog/alertdialog переносится в body, получает слой120 (backdrop110), а backdrop освобождает нижнюю область по фактической высоте клавиатуры через ResizeObserver. Обычная auth keyboard остаётся inline; class attrs передаются явно при Teleport root. Next ограничен полями текущего диалога. Observer отслеживает также teleported DOM: закрытие окна удаляет клавиатуру.

Playwright modal-keyboard.mjs PASS на1080x1920,1920x1080,390x844: реальные tap, отсутствие перекрытия клавиш, ввод login/password, Next, Done, Cancel cleanup. Существующий touch.mjs PASS наобоихориентациях и обязательнойсменепароля; fixture обновлён для существующего updates/notice API. Системные команды в тестах не отправлялись.

### Повторное применение оборудования и язык ошибок
Пользователь сообщил failed hardware/HTTP500 и UZ сообщение при EN интерфейсе. Воспроизведение host apply выявило ModuleNotFoundError: yaml в preserve-bill-config.py: на чистой CL host не хватало python3-yaml. Установлен Debian python3-yaml; prerequisite добавлен install-cl3566-host.sh. Повторный прямой apply EXIT0; затем полная реальная цепочка POST /api/commissioning/hardware HTTP200 → host job completed. Сеанс/баланс0, все8выходовOFF, cashdisabled. Отдельный прежний HTTP500 по traceback не воспроизведён; сервисный перезапуск во время apply временно прерывает API.

InstallHardware хранит semantic status, переводит computed при смене RU/UZ/EN; terminal result очищает старые reconnect/error сообщения. Добавлен request-error.js для локализованных сервисных/HTTP/network сообщений на installer, вместо голого HTTP500/сырого response. Полный Playwright install scenario PASS включая RU→EN→UZ→RU после failed job и успешную повторную операцию. Unit request-error PASS. Production UI build/diff check PASS. CL UI обновлён, прежний tag сохранён; источник синхронизирован. Финальное завершение commissioning пользователем не выполнялось агентом.

### Денежный вход после commissioning
Пользователь завершил настройку без общего кошелька/Telegram и вставил2x10000, баланс0. Проверка: активная CL map retained bill_acceptor.enabled=false (изначальная bench restriction), listenerfalse, journal pulses0, billPulseSum1000. Причина не связана с кошельком/Telegram. Эти купюры программой не зарегистрированы; сумма не начислялась вручную и не восстанавливалась предположением.

На конкретной подтверждённой/commissioned CL разрешён vendor IO5 input: backup .cl3566-cash-before-enable.yaml, проверены баланс/сеансы0,inputHIGH/directioninput,8outputsOFF. Engine остановлен на время изменения/перезапускаhelper, journal сохранён. Первый readiness check оказался преждевременным (bill ready раньше Modbus), выполнен rollback; повторный combined readiness PASS: cashenabled,true listener,true ready,true faultnull total0 outputsOFF. Engine запущен обратно. Default factory map в репозитории остаётся cashdisabled; явный installer cash acceptance/enable flow для будущих плат ещё требует реализации. Запущен5min monitor pulse/balance для контрольной однойкупюры.

### Потеря6из20импульсов на полном стеке
После2x10000 пользователь получил14000. До изменения фильтра зафиксировано raw_edges40/raw_pulses20,validated/published/journal14,rejected sampling_gap6; pulsevalue1000,bonusdisabled,servicesinactive. Это6отклонённых наблюдаемых импульсов, не потеря backend начислений и не повод отключать sampling_gap.

В CL overlay не был перенесён Cubie IO_BILL_SAMPLER_NICE=-10: runtime diagnosticnice0. Добавлен CL override -10 для последующих запусков. Без перезапуска приложения и без изменения14000баланса live sampler поднят os.setpriority до-10. Для измеренного PC817 сигнала50msLOW/100msHIGH установлены прежние проверенные Cubie minpulse25/mingap25 (вместо generic5/5),max1000,stuck5000,startup500,rate0. Filter API сохранил настройки в durable journal и перезапустил только sampler, новый PID также поднят до-10. Journal total14 сохранён, сумма не дописывалась. Sampling_gap остаётся включён. Диагностика env sampler_nice пока показывает0 у текущего контейнера, фактический os.getpriority=-10; env вступит после будущего idle recreation. Запущен5мин monitor через localhost endpoints без dockerexec для проверки контрольной купюры; приёмка нового режима ещё ожидается.

### Бесплатная пауза локальных карт
Подтверждён local-card loophole: save закрывает сеанс/сбрасывает budget, load не восстанавливает его; на общем wallet уже есть visit accounting. Добавлен local_card_pause.py и интеграция save/load: existing card metadata,row locks,atomic money+visit transfer; min merge,service scope,30min expiry,invalid failclosed0,legacyinitiallimit. Restored budget сразу сохраняется в sessionmetadata для power recovery. Shared protocol/DBschema неизменны.

8unit/runtime+16wash+43wallet/bonus/cardguards PASS. Disposable PostgreSQL real SQL test5roundtrips,10000money+2000bonus unchanged,24.25/0pause preserved,persistedrecoverymetadata andexpiry PASS. DisposableDB/network подлежат удалению после теста. На CL перед установкой баланс0,нетсеанса. Резервная копия базы verified-before*.sql.gz прошла gzip/header check, старый image сохранён. Установлен отдельный local-pause-fix engine; Radxa не обновлялась. Физическая карточная приёмка ожидается.
