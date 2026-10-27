import json
import urllib.request


def check_unfinished_idle():
    def get(path):
        req=urllib.request.Request('http://127.0.0.1:8090/api/'+path,headers={'X-Commissioning-Client-IP':'127.0.0.1'})
        with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
    if get('commissioning/status')['commissioning']['complete']:
        raise RuntimeError('Commissioning is closed')
    state=get('wash/state')['state']
    if any(state.get(k) for k in ('creditSum','activeSessionId','activeMode','armedMode','requestedOutput','walletTransferPending','walletCashHeld','vipRemainingSeconds')):
        raise RuntimeError('Finish the customer session first')
