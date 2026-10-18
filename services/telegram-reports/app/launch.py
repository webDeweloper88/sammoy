"""Load persistent keys into each child process before importing Settings."""
import os
import sys
import time
from dotenv import dotenv_values

while True:
    values = dotenv_values(os.environ.get('RTU_WASH_REPORTS_ENV', '/data/reports.env'))
    os.environ.update({k: v for k, v in values.items() if v is not None})
    if sys.argv[1] != 'bot' or (values.get('TELEGRAM_ENABLED') == 'true' and values.get('TELEGRAM_LEADER','true') == 'true' and values.get('TELEGRAM_BOT_TOKEN')):
        break
    time.sleep(2)
if sys.argv[1] == 'bot':
    from app.telegram_bot.main import main
    main()
else:
    import uvicorn
    is_report = sys.argv[1] == 'report'
    uvicorn.run('app.report_api.main:app' if is_report else 'app.hub.main:app', host='0.0.0.0' if is_report else '127.0.0.1', port=8091 if is_report else 8092, access_log=False)
