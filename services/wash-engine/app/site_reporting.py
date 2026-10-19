"""Independent receipts, service consumption and card turnover; no Telegram dependency."""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from .db import db

TZ=ZoneInfo('Asia/Tashkent')
TOTALS=('cash_sum','click_sum','receipts_sum','service_sum','money_spent_sum','bonus_spent_sum',
        'bonus_granted_sum','vip_virtual_spent_sum','customer_saved_sum','customer_used_sum',
        'vip_grant_count','vip_grant_seconds','test_credit_sum','sessions')

def bounds(start=None,end=None):
    try:
        a=date.fromisoformat(start) if start else datetime.now(TZ).date()
        b=date.fromisoformat(end) if end else a
    except (TypeError,ValueError):raise HTTPException(422,'Invalid report dates') from None
    if b<a or (b-a).days>365:raise HTTPException(422,'Choose a period of up to one year')
    return datetime.combine(a,time.min,TZ).astimezone(UTC),datetime.combine(b+timedelta(days=1),time.min,TZ).astimezone(UTC)

def local_report(start=None,end=None):
    a,b=bounds(start,end)
    # Each statement uses its own event time. Session origin and card loads are
    # never external income. A repeatable-read snapshot keeps subtotals aligned.
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        c.execute("SET LOCAL statement_timeout='2500ms'")
        payments=c.execute("""SELECT provider,COALESCE(sum(amount_sum),0) amount,
            COALESCE(sum(bonus_sum),0) bonus,count(*) count FROM payments
            WHERE created_at >= %s AND created_at < %s AND status IN ('paid','credited')
            GROUP BY provider""",(a,b)).fetchall()
        modes=c.execute("""SELECT u.mode,COALESCE(sum(u.duration_ms),0) duration_ms,
            COALESCE(sum(u.spent_sum) FILTER(WHERE s.source IS DISTINCT FROM 'vip'),0) service_sum,
            COALESCE(sum(u.bonus_spent_sum) FILTER(WHERE s.source IS DISTINCT FROM 'vip'),0) bonus_spent_sum,
            COALESCE(sum(u.spent_sum) FILTER(WHERE s.source='vip'),0) vip_virtual_spent_sum
            FROM mode_usage u JOIN wash_sessions s ON s.id=u.wash_session_id
            WHERE u.started_at >= %s AND u.started_at < %s GROUP BY u.mode ORDER BY u.mode""",(a,b)).fetchall()
        ledger=c.execute("""SELECT reason,count(*) count,COALESCE(sum(amount_sum),0) amount,
            COALESCE(sum(duration_seconds),0) seconds FROM rfid_card_ledger
            WHERE created_at >= %s AND created_at < %s GROUP BY reason""",(a,b)).fetchall()
        timeline=c.execute("""SELECT (created_at AT TIME ZONE 'Asia/Tashkent')::date AS day,
            COALESCE(sum(amount_sum) FILTER(WHERE provider='cash'),0) cash_sum,
            COALESCE(sum(amount_sum) FILTER(WHERE provider='click'),0) click_sum
            FROM payments WHERE created_at >= %s AND created_at < %s
            AND status IN ('paid','credited') AND provider IN ('cash','click')
            GROUP BY day ORDER BY day""",(a,b)).fetchall()
        count=c.execute('SELECT count(*) count FROM wash_sessions WHERE started_at >= %s AND started_at < %s',(a,b)).fetchone()['count']
    p={r['provider']:r for r in payments};l={r['reason']:r for r in ledger}
    summary={k:0 for k in TOTALS}
    for kind in ('cash','click'):summary[kind+'_sum']=int(p.get(kind,{}).get('amount',0))
    summary['receipts_sum']=summary['cash_sum']+summary['click_sum']
    summary['bonus_granted_sum']=sum(int(p.get(k,{}).get('bonus',0)) for k in ('cash','click'))
    summary['test_credit_sum']=int(p.get('admin',{}).get('amount',0))+int(p.get('manual',{}).get('amount',0))
    for key in ('service_sum','bonus_spent_sum','vip_virtual_spent_sum'):
        summary[key]=sum(int(r[key]) for r in modes)
    summary['money_spent_sum']=summary['service_sum']-summary['bonus_spent_sum']
    for key,reason in [('customer_saved_sum','save_remaining'),('customer_used_sum','use_balance')]:summary[key]=int(l.get(reason,{}).get('amount',0))
    summary['vip_grant_count']=int(l.get('vip_grant',{}).get('count',0))
    summary['vip_grant_seconds']=int(l.get('vip_grant',{}).get('seconds',0));summary['sessions']=int(count)
    return {'summary':summary,'modes':[{k:int(v) if k!='mode' else v for k,v in r.items()} for r in modes],
            'timeline':[{**{k:int(v) for k,v in r.items() if k!='day'},'day':r['day'].isoformat()} for r in timeline],
            'accounting_basis':'payment_event_and_usage_segment_start',
            'period':{'from':a.astimezone(TZ).date().isoformat(),'to':(b.astimezone(TZ)-timedelta(days=1)).date().isoformat()}}

def aggregate(posts):
    total={k:0 for k in TOTALS};modes={};days={}
    for post in posts:
        if post.get('status')!='online':continue
        report=post['report']
        for key in TOTALS:total[key]+=report['summary'][key]
        for row in report['modes']:
            target=modes.setdefault(row['mode'],dict.fromkeys(('duration_ms','service_sum','bonus_spent_sum','vip_virtual_spent_sum'),0))
            for key in target:target[key]+=row[key]
        for row in report['timeline']:
            target=days.setdefault(row['day'],{'cash_sum':0,'click_sum':0})
            for key in target:target[key]+=row[key]
    online=sum(p.get('status')=='online' for p in posts)
    return {'summary':total,'complete':online==len(posts),'online_posts':online,
            'modes':[{'mode':key,**row} for key,row in modes.items()],
            'timeline':[{'day':key,**row} for key,row in sorted(days.items())]}
