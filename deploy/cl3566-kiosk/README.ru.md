# Минимальный киоск CL3566

LightDM остаётся; вместо XFCE запускается session.sh с Openbox и существующим Chromium launcher. Перед браузером ожидается успешный HTTP ответ /api/commissioning/state. Экран HDMI-1 повёрнут right. Калибровка ILITEK хранится отдельно в /etc/X11/xorg.conf.d/99-labrix-ilitek-touch.conf.

На стенде 10.10.10.26 удалены только явно выбранные XFCE desktop/application packages (план и список установленных версий до удаления: /var/lib/labrix/os-cleanup). Autoremove не выполнялся. LightDM, Xorg/libinput, Chromium, NetworkManager, SSH, vendor kernel/firmware и Rockchip startup сохранены. Apt cache очищен. Не применять Radxa minimal-kiosk/install.sh: он рассчитан на SDDM.

Выбор сеанса: /etc/lightdm/lightdm.conf.d/90-labrix.conf, autologin-session=labrix-cl3566. Session desktop: /usr/share/xsessions/labrix-cl3566.desktop. Openbox config: /etc/labrix/openbox.xml. Launcher: /home/kiosk/.local/bin/labrix-kiosk.sh. Новые платы требуют установки openbox без рекомендуемых пакетов.

IO5 startup: ожидание sysfs увеличено с 10 до 60 секунд, TimeoutStartSec=90, поскольку vendor module появляется позднее прежнего окна. При отсутствии GPIO отказ остаётся закрытым: Docker не запускается. Это не исправляет ранний LOW до загрузки vendor driver.

Повторный reboot выявил: jwsioc вообще не загружался автоматически, а не только запаздывал. Файл поставщика /lib/modules/jwsioc.ko лежит вне versioned modprobe tree. cl3566-io5-input.py теперь загружает именно этот модуль через insmod, только если /sys/module/jwsioc и интерфейс отсутствуют; ошибка загрузки останавливает старт. Другие GPIO не переключаются скриптом.

Добавлен экран загрузки из minimal-kiosk/boot.html с LABRIX logo, RU/UZ текстом и indeterminate progress bar. kiosk.conf теперь указывает file:///usr/local/share/labrix-kiosk/boot.html; файл не зависит от запущенного HTTP-сервера и переходит в /launch после доступности UI. Session больше не ждёт HTTP перед browser, чтобы сразу показывать загрузку. hide-cursor.py скрывает курсор XFixes на протяжении сеанса. Это экран графического киоска, не ранний U-Boot/kernel splash: стандартный Radxa Plymouth installer неприменим к vendor CL boot layout без отдельной адаптации.
