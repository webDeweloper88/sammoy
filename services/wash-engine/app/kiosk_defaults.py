from copy import deepcopy
import re
from typing import Any


KIOSK_LANGUAGES = ["uz", "kz", "ky", "ru"]

DEFAULT_PROGRAM_STYLE: dict[str, Any] = {
    "tone": "theme",
    "idle": {
        "background": "",
        "border": "",
        "text": "",
        "glow": "",
    },
    "active": {
        "background": "",
        "border": "",
        "text": "",
        "glow": "",
    },
}

DEFAULT_KIOSK_SETTINGS: dict[str, Any] = {
    "version": 1,
    "brand": {
        "name": "RTU WASH",
        "productLine": "Wash Control",
        "logoUrl": "",
    },
    "theme": {
        "design": "cards",
        "appearance": {"mode": "auto", "manualTheme": "dark", "lightStart": "08:00", "lightEnd": "18:00", "timezone": "Asia/Tashkent"},
        "id": "rtu-wash-classic",
        "preset": "rtu-wash-classic",
        "typography": {
            "fontFamily": "display",
        },
        "background": {
            "mode": "solid",
            "gradientStart": "#020b10",
            "gradientEnd": "#102f36",
            "gradientAngle": 180,
        },
        "tokens": {
            "accentPrimary": "#00dfff",
            "accentSecondary": "#ff12bb",
            "statusOnline": "#31e978",
            "background": "#020b10",
            "surface": "#071f27",
            "surfaceRaised": "#102f36",
            "text": "#f4fbff",
            "muted": "#9dc7cf",
            "danger": "#ff535d",
            "warning": "#f2e91f",
        },
    },
    "texts": {
        "uz": {
            "mode": "REJIM",
            "insertPayment": "To'lov qiling",
            "chooseMode": "Rejim tanlang",
            "active": "Rejim yoqilgan, pul yechilyapti",
            "triggerFreePause": "Kurokni bosing. Bepul pauza {seconds}s",
            "triggerCharging": "Kurok bosilmagan. Rejim bo'yicha yechilyapti",
            "pauseCharging": "Pauza bosilgan. Bepul pauza tugadi, pul yechilyapti",
            "manualPause": "Pauza bosilgan. {seconds}s bepul qoldi",
            "licenseLocked": "Litsenziya bloklangan",
            "unsupportedMode": "Rejim ulanmagan",
            "systemError": "Tizim xatosi",
            "paymentRequiredTitle": "Avval to'lov qiling",
            "paymentRequiredText": "{mode} rejimini ishga tushirish uchun to'lov turini tanlang.",
            "pauseTime": "PAUZA VAQTI",
            "sum": "SUMMA",
            "time": "VAQT",
            "payment": "TO'LOV",
            "choosePayment": "To'lov tanlang",
            "online": "ONLINE",
            "offline": "OFFLINE",
            "alarm": "AVARIYA",
            "operatorLogin": "Operator kirish",
            "instagramLine1": "Instagram sahifamizga",
            "instagramLine2": "obuna bo'ling",
            "bonusProgram": "Bonus",
            "service": "RTU WASH servis",
            "serviceContacts": "Servis",
        },
        "kz": {
            "mode": "РЕЖИМ",
            "insertPayment": "Төлем салыңыз",
            "chooseMode": "Режим таңдаңыз",
            "active": "Режим қосылды, ақша шегерілуде",
            "triggerFreePause": "Шүріппені басыңыз. Тегін пауза {seconds}s",
            "triggerCharging": "Шүріппе басылмаған. Режим бойынша шегеріледі",
            "pauseCharging": "Пауза басылды. Тегін пауза аяқталды, ақша шегерілуде",
            "manualPause": "Пауза басылды. {seconds}s тегін қалды",
            "licenseLocked": "Лицензия бұғатталған",
            "unsupportedMode": "Режим қосылмаған",
            "systemError": "Жүйе қатесі",
            "paymentRequiredTitle": "Алдымен төлем салыңыз",
            "paymentRequiredText": "{mode} режимін іске қосу үшін төлем түрін таңдаңыз.",
            "pauseTime": "ПАУЗА УАҚЫТЫ",
            "sum": "СОМА",
            "time": "УАҚЫТ",
            "payment": "ТӨЛЕМ",
            "choosePayment": "Төлем таңдаңыз",
            "online": "ОНЛАЙН",
            "offline": "OFFLINE",
            "alarm": "АВАРИЯ",
            "operatorLogin": "Оператор кіру",
            "instagramLine1": "Instagram парақшамызға",
            "instagramLine2": "жазылыңыз",
            "bonusProgram": "Bonus",
            "service": "RTU WASH сервис",
            "serviceContacts": "Сервис",
        },
        "ky": {
            "mode": "РЕЖИМ",
            "insertPayment": "Төлөм салыңыз",
            "chooseMode": "Режим тандаңыз",
            "active": "Режим күйдү, акча эсептен чыгууда",
            "triggerFreePause": "Курокту басыңыз. Акысыз пауза {seconds}s",
            "triggerCharging": "Курок басылган жок. Режим боюнча эсептен чыгат",
            "pauseCharging": "Пауза басылды. Акысыз пауза бүттү, акча эсептен чыгууда",
            "manualPause": "Пауза басылды. {seconds}s акысыз калды",
            "licenseLocked": "Лицензия бөгөттөлгөн",
            "unsupportedMode": "Режим туташкан эмес",
            "systemError": "Система катасы",
            "paymentRequiredTitle": "Алгач төлөм салыңыз",
            "paymentRequiredText": "{mode} режимин иштетүү үчүн төлөм түрүн тандаңыз.",
            "pauseTime": "ПАУЗА УБАКТЫСЫ",
            "sum": "СУММА",
            "time": "УБАКЫТ",
            "payment": "ТӨЛӨМ",
            "choosePayment": "Төлөм тандаңыз",
            "online": "ОНЛАЙН",
            "offline": "OFFLINE",
            "alarm": "АВАРИЯ",
            "operatorLogin": "Оператор кирүү",
            "instagramLine1": "Instagram баракчабызга",
            "instagramLine2": "жазылыңыз",
            "bonusProgram": "Bonus",
            "service": "RTU WASH сервис",
            "serviceContacts": "Сервис",
        },
        "ru": {
            "mode": "РЕЖИМ",
            "insertPayment": "Внесите оплату",
            "chooseMode": "Выберите режим",
            "active": "Режим включён, идёт списание",
            "triggerFreePause": "Нажмите курок. Бесплатная пауза {seconds}s",
            "triggerCharging": "Курок не нажат. Идёт списание по режиму",
            "pauseCharging": "Пауза нажата. Бесплатная пауза закончилась, идёт списание",
            "manualPause": "Пауза нажата. Осталось {seconds}s бесплатно",
            "licenseLocked": "Лицензия заблокирована",
            "unsupportedMode": "Режим не подключён",
            "systemError": "Ошибка системы",
            "paymentRequiredTitle": "Сначала внесите оплату",
            "paymentRequiredText": "Для запуска режима {mode} выберите способ оплаты.",
            "pauseTime": "ПАУЗА ВРЕМЯ",
            "sum": "СУММА",
            "time": "ВРЕМЯ",
            "payment": "ОПЛАТА",
            "choosePayment": "Выберите оплату",
            "online": "ОНЛАЙН",
            "offline": "OFFLINE",
            "alarm": "АВАРИЯ",
            "operatorLogin": "Вход оператора",
            "instagramLine1": "Подписывайтесь",
            "instagramLine2": "на наш",
            "bonusProgram": "Bonus",
            "service": "RTU WASH сервис",
            "serviceContacts": "Сервис",
        },
    },
    "payment": {
        "quickAmounts": [2000, 5000, 10000, 20000],
        "minAmount": 1000,
        "maxAmount": 9999999,
        "uz": {
            "amount": "Summa",
            "acceptedBills": "Qabul qilingan kupyuralar",
            "back": "Ortga",
            "bonus": "Bonuslar",
            "cash": "Naqd",
            "cashInfo": "Pul tushgandan keyin oyna avtomatik yopiladi. Asosiy ekranda balans va mavjud yuvish rejimlari ko'rinadi.",
            "cashTitle": "Naqd pul kiriting",
            "clickTitle": "Click orqali to'lov",
            "future": "keyinroq",
            "inserted": "Kiritildi:",
            "insertBillsLine1": "Kupyuralarni",
            "insertBillsLine2": "qabul qilgichga soling",
            "otherAmount": "Boshqa summa",
            "paymentLink": "To'lov havolasi",
            "qrNotReady": "QR hali yaratilmagan",
            "scanQr": "To'lovni yakunlash uchun QR-kodni skaner qiling yoki havolaga o'ting",
            "soon": "tez orada",
            "sum": "so'm",
            "waitBills": "Kupyura impulslari kutilmoqda",
            "waitingPayment": "To'lov kutilmoqda",
            "creatingPayment": "QR yaratilmoqda",
            "paymentReady": "QR tayyor",
            "paymentCredited": "To'lov tushdi",
            "paymentCreditedText": "Balans yangilandi. Yuvish rejimini tanlashingiz mumkin.",
            "paymentError": "Click xatosi",
        },
        "kz": {},
        "ky": {},
        "ru": {
            "amount": "Сумма",
            "acceptedBills": "Принятые купюры",
            "back": "Назад",
            "bonus": "Бонусы",
            "cash": "Наличные",
            "cashInfo": "После зачисления средств окно закроется автоматически. На главном экране отобразится ваш баланс и доступные режимы мойки.",
            "cashTitle": "Внесите наличные",
            "clickTitle": "Оплата через Click",
            "future": "в будущем",
            "inserted": "Внесено:",
            "insertBillsLine1": "Вставьте купюры",
            "insertBillsLine2": "в купюроприёмник",
            "otherAmount": "Другая сумма",
            "paymentLink": "Ссылка для оплаты",
            "qrNotReady": "QR ещё не создан",
            "scanQr": "Отсканируйте QR-код или перейдите по ссылке для завершения оплаты",
            "soon": "скоро",
            "sum": "сум",
            "waitBills": "Ждём импульсы купюроприёмника",
            "waitingPayment": "Ожидание оплаты",
            "creatingPayment": "Создаём QR",
            "paymentReady": "QR готов",
            "paymentCredited": "Оплата зачислена",
            "paymentCreditedText": "Баланс обновлён. Можно выбрать режим мойки.",
            "paymentError": "Ошибка Click",
        },
    },
    "programs": [
        {"id": "water", "label": {"uz": "SUV", "kz": "СУ", "ky": "СУУ", "ru": "ВОДА"}, "iconUrl": "", "visible": True, "style": DEFAULT_PROGRAM_STYLE},
        {"id": "foam", "label": {"uz": "KO'PIK", "kz": "КӨБІК", "ky": "КӨБҮК", "ru": "ПЕНА"}, "iconUrl": "", "visible": True, "style": {**DEFAULT_PROGRAM_STYLE, "tone": "secondary"}},
        {"id": "air", "label": {"uz": "HAVO", "kz": "АУА", "ky": "АБА", "ru": "ВОЗДУХ"}, "iconUrl": "", "visible": True, "style": DEFAULT_PROGRAM_STYLE},
        {"id": "vacuum", "label": {"uz": "CHANGYUTGICH", "kz": "ШАҢСОРҒЫШ", "ky": "ЧАҢ СОРГУЧ", "ru": "ПЫЛЕСОС"}, "iconUrl": "", "visible": True, "style": DEFAULT_PROGRAM_STYLE},
        {"id": "pause", "label": {"uz": "pauza", "kz": "пауза", "ky": "пауза", "ru": "пауза"}, "iconUrl": "", "visible": True, "style": {**DEFAULT_PROGRAM_STYLE, "tone": "secondary"}},
        {"id": "osmos", "label": {"uz": "Osmos", "kz": "Осмос", "ky": "Осмос", "ru": "Осмос"}, "iconUrl": "", "visible": True, "style": DEFAULT_PROGRAM_STYLE},
        {"id": "nano", "label": {"uz": "NANO", "kz": "НАНО", "ky": "НАНО", "ru": "НАНО"}, "iconUrl": "", "visible": True, "style": DEFAULT_PROGRAM_STYLE},
        {"id": "wax", "label": {"uz": "MUM", "kz": "БАЛАУЫЗ", "ky": "МОМ", "ru": "ВОСК"}, "iconUrl": "", "visible": True, "style": {**DEFAULT_PROGRAM_STYLE, "tone": "secondary"}},
        {"id": "chem", "label": {"uz": "KIMYO", "kz": "ХИМИЯ", "ky": "ХИМИЯ", "ru": "ХИМИЯ"}, "iconUrl": "", "visible": True, "style": DEFAULT_PROGRAM_STYLE},
    ],
    "contacts": {
        "serviceSite": "support.example.com",
        "supportPhone": "+998 91 111 69 29",
        "socialLinks": {"telegram": "", "instagram": "", "youtube": ""},
        "footerCompany": "© 2025-2026 RTU WASH",
    },
    "layout": {
        "templateId": "precision-grid",
        "defaultLanguage": "uz",
        "showLanguageButtons": True,
        "backgroundImageUrl": "",
    },
}


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict):
        if not isinstance(override, dict):
            return deepcopy(base)
        result = deepcopy(base)
        for key, value in override.items():
            result[key] = deep_merge(base.get(key), value) if key in base else deepcopy(value)
        return result
    if isinstance(base, list):
        return deepcopy(override) if isinstance(override, list) else deepcopy(base)
    return deepcopy(override) if override is not None else deepcopy(base)


def normalize_kiosk_settings(value: dict[str, Any] | None) -> dict[str, Any]:
    settings = deep_merge(DEFAULT_KIOSK_SETTINGS, value or {})
    theme = settings.get("theme")
    if not isinstance(theme, dict):
        theme = settings["theme"] = deepcopy(DEFAULT_KIOSK_SETTINGS["theme"])
    theme["design"] = theme.get("design") if theme.get("design") in ("wheel", "cards") else "cards"
    defaults = DEFAULT_KIOSK_SETTINGS["theme"]["appearance"]
    appearance = theme.get("appearance")
    if not isinstance(appearance, dict):
        appearance = {}
    theme["appearance"] = {
        "mode": appearance.get("mode") if appearance.get("mode") in ["manual", "auto"] else "auto",
        "manualTheme": appearance.get("manualTheme") if appearance.get("manualTheme") in ["light", "dark"] else "dark",
        "lightStart": appearance.get("lightStart") if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(appearance.get("lightStart", ""))) else defaults["lightStart"],
        "lightEnd": appearance.get("lightEnd") if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(appearance.get("lightEnd", ""))) else defaults["lightEnd"],
        "timezone": "Asia/Tashkent",
    }
    layout = settings.setdefault("layout", {})
    layout.pop("showTemperature", None)
    layout.pop("temperatureText", None)
    layout.pop("showInternetStatus", None)
    layout.pop("showInstagramBlock", None)
    layout.pop("showBonusBlock", None)
    layout.pop("showServiceBlock", None)
    contacts = settings.setdefault("contacts", {})
    contacts.pop("instagramUrl", None)
    contacts.pop("bonusUrl", None)
    contacts.pop("serviceUrl", None)


    texts = settings.setdefault("texts", {})
    for language in KIOSK_LANGUAGES:
        texts[language] = deep_merge(DEFAULT_KIOSK_SETTINGS["texts"][language], texts.get(language, {}))
    payment = settings.setdefault("payment", {})
    for language in KIOSK_LANGUAGES:
        payment[language] = deep_merge(DEFAULT_KIOSK_SETTINGS["payment"].get(language) or DEFAULT_KIOSK_SETTINGS["payment"]["uz"], payment.get(language, {}))

    default_programs = {program["id"]: program for program in DEFAULT_KIOSK_SETTINGS["programs"]}
    normalized_programs = []
    seen = set()
    for program in settings.get("programs", []):
        program_id = program.get("id")
        if not program_id:
            continue
        base = default_programs.get(program_id, {"id": program_id, "label": {}, "iconUrl": "", "visible": True, "style": DEFAULT_PROGRAM_STYLE})
        merged = deep_merge(base, program)
        if program_id == "osmos":
            label = merged.setdefault("label", {})
            legacy_labels = {"uz": "OSMOS", "kz": "ОСМОС", "ky": "ОСМОС", "ru": "ОСМОС"}
            for language, legacy_value in legacy_labels.items():
                if label.get(language) == legacy_value:
                    label[language] = DEFAULT_KIOSK_SETTINGS["programs"][5]["label"][language]
        merged["visible"] = merged.get("visible") is not False
        normalized_programs.append(merged)
        seen.add(program_id)

    for program_id, program in default_programs.items():
        if program_id not in seen:
            normalized_programs.append(deepcopy(program))

    settings["programs"] = normalized_programs
    return settings
