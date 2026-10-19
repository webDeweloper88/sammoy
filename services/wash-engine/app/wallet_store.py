"""Durable prepare/commit journal for the staged shared wallet.

The authority coordinator obtains signed standby durability acknowledgements
before commit_prepared; no network failure becomes a successful transfer here.
"""
from .wallet_devices import state_dump
import hashlib
import json

from psycopg.types.json import Jsonb

from .wallet_domain import WalletConflict, WalletPolicy, WalletState, apply_command

WALLET_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shared_wallet_cards (
    site_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    state JSONB NOT NULL,
    pending_operation TEXT,
    PRIMARY KEY (site_id, uid)
);
CREATE TABLE IF NOT EXISTS shared_wallet_operations (
    sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    command JSONB NOT NULL,
    before_revision BIGINT NOT NULL,
    proposed_state JSONB NOT NULL,
    result JSONB NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('prepared','committed','abandoned')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    committed_at TIMESTAMPTZ,
    UNIQUE (site_id, operation_id),
    FOREIGN KEY (site_id, uid) REFERENCES shared_wallet_cards(site_id, uid)
);
CREATE TABLE IF NOT EXISTS shared_wallet_funding_receipts (
    site_id TEXT NOT NULL, receipt_id TEXT NOT NULL, uid TEXT NOT NULL,
    value JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(site_id,receipt_id)
);
CREATE TABLE IF NOT EXISTS shared_wallet_vip_uses (
    site_id TEXT NOT NULL, uid TEXT NOT NULL, day TEXT NOT NULL,
    used INTEGER NOT NULL CHECK(used>=0), PRIMARY KEY(site_id,uid,day)
);
CREATE INDEX IF NOT EXISTS shared_wallet_operations_pending_idx
    ON shared_wallet_operations(site_id, sequence) WHERE status='prepared';
"""


def fingerprint(uid: str, command: dict) -> str:
    raw = json.dumps({"uid": uid, "command": command}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class WalletStore:
    def __init__(self, connection, site_id: str):
        if not isinstance(site_id, str) or not site_id.strip():
            raise WalletConflict("Site identity required")
        if not connection.autocommit:
            raise WalletConflict("WalletStore requires an autocommit connection for durable acknowledgements")
        self.conn = connection
        self.site_id = site_id

    def _lock(self):
        # Serialize all operations in a site; also guards operation-ID reuse
        # across cards. A later optimization must preserve these invariants.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("wallet:" + self.site_id,))

    def _operation(self, operation_id):
        return self.conn.execute("SELECT * FROM shared_wallet_operations WHERE site_id=%s AND operation_id=%s",
                                 (self.site_id, operation_id)).fetchone()

    @staticmethod
    def _receipt(row):
        return {"operation_id": row["operation_id"], "sequence": row["sequence"],
                "status": row["status"], "result": row["result"]}

    def prepare(self, operation_id: str, uid: str, command: dict, policy: WalletPolicy) -> dict:
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 160:
            raise WalletConflict("Operation ID required")
        if not isinstance(uid, str) or not uid or len(uid) > 80:
            raise WalletConflict("Card UID required")
        digest = fingerprint(uid, command)
        with self.conn.transaction():
            self._lock()
            existing = self._operation(operation_id)
            if existing:
                if existing["status"] == "abandoned":
                    raise WalletConflict("Operation was abandoned during fenced reconciliation")
                if existing["fingerprint"] != digest:
                    raise WalletConflict("Operation ID reused with different content")
                return self._receipt(existing)
            self.conn.execute("INSERT INTO shared_wallet_cards(site_id,uid,state) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                              (self.site_id, uid, Jsonb(state_dump(WalletState(uid)))))
            row = self.conn.execute("SELECT state,pending_operation FROM shared_wallet_cards WHERE site_id=%s AND uid=%s FOR UPDATE",
                                    (self.site_id, uid)).fetchone()
            if row["pending_operation"]:
                raise WalletConflict("Card has an unresolved operation")
            state = WalletState(**row["state"])
            now = self.conn.execute("SELECT clock_timestamp() AS current_time").fetchone()["current_time"]
            # Receipt tombstones are stored once, instead of copying a card's
            # entire lifetime payment map into every journal snapshot (32 GB boards).
            receipts=self._receipts(uid,command)
            if receipts:
                known=self.conn.execute("SELECT receipt_id,uid,value FROM shared_wallet_funding_receipts WHERE site_id=%s AND receipt_id=ANY(%s)",
                                         (self.site_id,[r[0] for r in receipts])).fetchall()
                for receipt in known:
                    if receipt['uid']!=uid:raise WalletConflict('Funding receipt belongs to another card')
                    state.funding_receipts[receipt['receipt_id']]=receipt['value']
            if command.get('action')=='import_vip':
                for day in command['snapshot'].get('daily_uses',{}):
                    usage=self.conn.execute('SELECT used FROM shared_wallet_vip_uses WHERE site_id=%s AND uid=%s AND day=%s',(self.site_id,uid,day)).fetchone()
                    if usage:state.vip_uses[day]=usage['used']
            if command.get('action')=='grant_vip':
                from zoneinfo import ZoneInfo
                day=now.astimezone(ZoneInfo('Asia/Tashkent')).date().isoformat()
                usage=self.conn.execute('SELECT used FROM shared_wallet_vip_uses WHERE site_id=%s AND uid=%s AND day=%s',(self.site_id,uid,day)).fetchone()
                if usage:state.vip_uses[day]=usage['used']
            proposed, result = apply_command(state, command, now=now, policy=policy)
            proposed.funding_receipts={}
            proposed.vip_uses={}
            operation = self.conn.execute("""
                INSERT INTO shared_wallet_operations
                (site_id,operation_id,uid,fingerprint,command,before_revision,proposed_state,result,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'prepared') RETURNING *
                """, (self.site_id, operation_id, uid, digest, Jsonb(command), state.revision,
                      Jsonb(state_dump(proposed)), Jsonb(result))).fetchone()
            self.conn.execute("UPDATE shared_wallet_cards SET pending_operation=%s WHERE site_id=%s AND uid=%s",
                              (operation_id, self.site_id, uid))
            return self._receipt(operation)

    def commit_prepared(self, operation_id: str) -> dict:
        """Coordinator-only: invoke AFTER standby acknowledgement/fencing checks.

        This method does not itself implement or assert redundant durability.
        It is intentionally not registered as an HTTP endpoint.
        """
        with self.conn.transaction():
            self._lock()
            operation = self._operation(operation_id)
            if not operation:
                raise WalletConflict("Unknown operation")
            if operation["status"] == "committed":
                return self._receipt(operation)
            card = self.conn.execute("SELECT state,pending_operation FROM shared_wallet_cards WHERE site_id=%s AND uid=%s FOR UPDATE",
                                     (self.site_id, operation["uid"])).fetchone()
            if card["pending_operation"] != operation_id or card["state"]["revision"] != operation["before_revision"]:
                raise WalletConflict("Prepared revision no longer matches")
            proposed = WalletState(**operation["proposed_state"])
            proposed.validate()
            for receipt_id,value in self._receipts(operation['uid'],operation['command']):
                known=self.conn.execute("SELECT uid,value FROM shared_wallet_funding_receipts WHERE site_id=%s AND receipt_id=%s",(self.site_id,receipt_id)).fetchone()
                if known and (known['uid']!=operation['uid'] or known['value']!=value):raise WalletConflict('Funding receipt conflicts with durable journal')
                self.conn.execute("INSERT INTO shared_wallet_funding_receipts(site_id,receipt_id,uid,value) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                  (self.site_id,receipt_id,operation['uid'],Jsonb(value)))
            if operation['result'].get('vip_day'):
                self.conn.execute("INSERT INTO shared_wallet_vip_uses(site_id,uid,day,used) VALUES(%s,%s,%s,%s) ON CONFLICT(site_id,uid,day) DO UPDATE SET used=EXCLUDED.used",(self.site_id,operation['uid'],operation['result']['vip_day'],operation['result']['vip_total_uses']))
            for day,used in operation['result'].get('vip_import_uses',{}).items():
                self.conn.execute('INSERT INTO shared_wallet_vip_uses(site_id,uid,day,used) VALUES(%s,%s,%s,%s) ON CONFLICT(site_id,uid,day) DO UPDATE SET used=EXCLUDED.used',(self.site_id,operation['uid'],day,used))
            self.conn.execute("UPDATE shared_wallet_cards SET state=%s,pending_operation=NULL WHERE site_id=%s AND uid=%s",
                              (Jsonb(state_dump(proposed)), self.site_id, operation["uid"]))
            row = self.conn.execute("UPDATE shared_wallet_operations SET status='committed',committed_at=now() WHERE site_id=%s AND operation_id=%s RETURNING *",
                                    (self.site_id, operation_id)).fetchone()
            return self._receipt(row)

    @staticmethod
    def _receipts(uid,command):
        if command.get('action')=='import_vip':
            from .vip_import_domain import receipt
            return [(command['receipt_id'],receipt(command))]
        if command.get('action')=='import_local_balance':
            if not all(key in command for key in ('receipt_id','amount_sum')):raise WalletConflict('Local import fields required')
            return [(command['receipt_id'],{'source':'opening','amount_sum':command['amount_sum'],'assignment_id':None,**({'bonus_sum':command['bonus_sum']} if command.get('bonus_sum') else {}),**({'bonus_domain':command.get('bonus_domain','shared')} if command.get('wallet_protocol')==2 else {})})]
        if command.get('action')=='wallet_credit':
            if not all(key in command for key in ('receipt_id','source','amount_sum')):
                raise WalletConflict('Funding receipt fields required')
            return [(command['receipt_id'],{'source':command['source'],'amount_sum':command['amount_sum'],'assignment_id':None,**({'bonus_sum':command['bonus_sum']} if command.get('bonus_sum') else {}),**({'bonus_domain':command.get('bonus_domain','shared')} if command.get('wallet_protocol')==2 else {})})]
        if command.get('action')=='checkpoint':
            funding=command.get('funding',[])
            if not isinstance(funding,list) or 'assignment_id' not in command or any(not isinstance(r,dict) or not all(k in r for k in ('id','source','amount_sum')) for r in funding):
                raise WalletConflict('Valid funding receipts required')
            return [(r['id'],{'source':r['source'],'amount_sum':r['amount_sum'],'assignment_id':command['assignment_id'],**({'bonus_sum':r['bonus_sum']} if r.get('bonus_sum') else {}),**({'bonus_domain':r.get('bonus_domain','shared')} if command.get('wallet_protocol')==2 else {})}) for r in command.get('funding',[])]
        return []

    def export_operation(self, operation_id: str) -> dict:
        row = self._operation(operation_id)
        if not row:
            raise WalletConflict("Unknown operation")
        return {key: row[key] for key in ("site_id", "operation_id", "uid", "fingerprint",
                "command", "before_revision", "proposed_state", "result")}

    def receive_replica(self, payload: dict) -> dict:
        """Persist an authenticated primary's proposal before acknowledging it.

        Caller must validate authority/site identity. Snapshot equality on retries
        protects against two proposals sharing an operation ID. Reconciliation
        keeps staged entries blocked until an explicit commit or fenced promotion.
        """
        if payload.get("site_id") != self.site_id:
            raise WalletConflict("Replica belongs to a different site")
        uid, operation_id = payload.get("uid"), payload.get("operation_id")
        if not isinstance(uid, str) or not uid or not isinstance(operation_id, str) or not operation_id:
            raise WalletConflict("Replica identity missing")
        if fingerprint(uid, payload["command"]) != payload.get("fingerprint"):
            raise WalletConflict("Replica fingerprint mismatch")
        proposed = WalletState(**payload["proposed_state"])
        proposed.validate()
        if proposed.uid != uid:
            raise WalletConflict("Replica card mismatch")
        with self.conn.transaction():
            self._lock()
            existing = self._operation(operation_id)
            if existing:
                comparable = self.export_operation(operation_id)
                if comparable != payload:
                    raise WalletConflict("Conflicting replica operation")
                return self._receipt(existing)
            self.conn.execute("INSERT INTO shared_wallet_cards(site_id,uid,state) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                              (self.site_id, uid, Jsonb(state_dump(WalletState(uid)))))
            card = self.conn.execute("SELECT state,pending_operation FROM shared_wallet_cards WHERE site_id=%s AND uid=%s FOR UPDATE",
                                     (self.site_id, uid)).fetchone()
            if card["pending_operation"] or card["state"]["revision"] != payload["before_revision"]:
                raise WalletConflict("Replica is not caught up")
            if proposed.revision not in {payload["before_revision"], payload["before_revision"] + 1}:
                raise WalletConflict("Replica revision gap")
            row = self.conn.execute("""
                INSERT INTO shared_wallet_operations
                (site_id,operation_id,uid,fingerprint,command,before_revision,proposed_state,result,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'prepared') RETURNING *
                """, (self.site_id, operation_id, uid, payload["fingerprint"], Jsonb(payload["command"]),
                      payload["before_revision"], Jsonb(payload["proposed_state"]), Jsonb(payload["result"]))).fetchone()
            self.conn.execute("UPDATE shared_wallet_cards SET pending_operation=%s WHERE site_id=%s AND uid=%s",
                              (operation_id, self.site_id, uid))
            return self._receipt(row)

    def pending_operations(self) -> list:
        return self.conn.execute("SELECT operation_id FROM shared_wallet_operations WHERE site_id=%s AND status='prepared' ORDER BY sequence",
                                 (self.site_id,)).fetchall()

    def history(self) -> list:
        return self.conn.execute("SELECT operation_id,status FROM shared_wallet_operations WHERE site_id=%s AND status != 'abandoned' ORDER BY sequence",
                                 (self.site_id,)).fetchall()

    def reconcile_manifest(self, operation_ids: list[str]):
        """After old-primary fencing, discard only uncommitted orphan proposals.

        A divergent COMMITTED operation blocks rejoin and requires operator
        reconciliation. Its money is never silently overwritten by a snapshot.
        """
        known=set(operation_ids)
        with self.conn.transaction():
            self._lock()
            rows=self.history()
            if any(row['operation_id'] not in known and row['status']=='committed' for row in rows):
                raise WalletConflict('Committed journals diverge; financial reconciliation required')
            for row in rows:
                if row['operation_id'] not in known:
                    self.conn.execute("UPDATE shared_wallet_cards SET pending_operation=NULL WHERE site_id=%s AND pending_operation=%s",
                                      (self.site_id,row['operation_id']))
                    self.conn.execute("UPDATE shared_wallet_operations SET status='abandoned' WHERE site_id=%s AND operation_id=%s",
                                      (self.site_id,row['operation_id']))

    def history_pages(self, size=200):
        after=0
        while True:
            rows=self.conn.execute("SELECT operation_id,status,sequence FROM shared_wallet_operations WHERE site_id=%s AND status!='abandoned' AND sequence>%s ORDER BY sequence LIMIT %s",(self.site_id,after,size)).fetchall()
            if not rows:return
            yield rows
            after=rows[-1]['sequence']

    def summaries(self, operation_ids):
        if not isinstance(operation_ids,list) or len(operation_ids)>200 or any(not isinstance(v,str) for v in operation_ids):
            raise WalletConflict('At most 200 operation IDs per batch')
        rows=self.conn.execute("SELECT * FROM shared_wallet_operations WHERE site_id=%s AND operation_id=ANY(%s) AND status!='abandoned'",(self.site_id,operation_ids)).fetchall()
        return {r['operation_id']:{'status':r['status'],'digest':self.operation_digest(r)} for r in rows}

    @staticmethod
    def operation_digest(row):
        operation={k:row[k] for k in ('site_id','operation_id','uid','fingerprint','command','before_revision','proposed_state','result')}
        return hashlib.sha256(json.dumps(operation,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def reconcile_pending(self, operation_ids):
        # Final full digest detects committed divergence; this step only removes
        # staged orphan proposals left by the physically fenced former primary.
        known=set(operation_ids)
        with self.conn.transaction():
            self._lock()
            for row in self.pending_operations():
                if row['operation_id'] not in known:
                    self.conn.execute("UPDATE shared_wallet_cards SET pending_operation=NULL WHERE site_id=%s AND pending_operation=%s",(self.site_id,row['operation_id']))
                    self.conn.execute("UPDATE shared_wallet_operations SET status='abandoned' WHERE site_id=%s AND operation_id=%s",(self.site_id,row['operation_id']))

    def digest(self):
        digest=hashlib.sha256();after=''
        while True:
            rows=self.conn.execute("SELECT * FROM shared_wallet_operations WHERE site_id=%s AND status!='abandoned' AND operation_id>%s ORDER BY operation_id LIMIT 200",(self.site_id,after)).fetchall()
            if not rows:break
            for row in rows:
                digest.update((self.operation_digest(row)+':'+row['status']+'\n').encode())
            after=rows[-1]['operation_id']
        return digest.hexdigest()

    def state_digest(self):
        """Hash the materialized state as well as the operation journal.

        Caller holds the site advisory lock. Keyset pages bound RAM usage.
        SQL sequence IDs and local timestamps are deliberately excluded.
        """
        digest=hashlib.sha256()
        sources=(
            ('cards',"SELECT uid,state,pending_operation FROM shared_wallet_cards WHERE site_id=%s AND uid>%s ORDER BY uid LIMIT 200",('uid',)),
            ('receipts',"SELECT receipt_id,uid,value FROM shared_wallet_funding_receipts WHERE site_id=%s AND receipt_id>%s ORDER BY receipt_id LIMIT 200",('receipt_id',)),
            ('vip_uses',"SELECT uid,day,used FROM shared_wallet_vip_uses WHERE site_id=%s AND (uid,day)>(%s,%s) ORDER BY uid,day LIMIT 200",('uid','day')),
        )
        for label,query,keys in sources:
            digest.update((label+'\n').encode());after=tuple('' for key in keys)
            while True:
                rows=self.conn.execute(query,(self.site_id,*after)).fetchall()
                if not rows:break
                for row in rows:
                    digest.update((json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
                after=tuple(rows[-1][key] for key in keys)
        return digest.hexdigest()

    def diagnostics(self):
        counts=self.conn.execute("SELECT count(*) FILTER(WHERE status!='abandoned') AS operations,count(*) FILTER(WHERE status='prepared') AS pending,max(committed_at) AS last_committed_at FROM shared_wallet_operations WHERE site_id=%s",(self.site_id,)).fetchone()
        return {'proof_version':2,'journal_digest':self.digest(),'state_digest':self.state_digest(),
                'operation_count':int(counts['operations']),'pending_count':int(counts['pending']),
                'last_committed_at':counts['last_committed_at'].isoformat() if counts['last_committed_at'] else None}

    def vip_cards(self):
        return self.conn.execute("SELECT state FROM shared_wallet_cards WHERE site_id=%s AND state->>'card_type'='vip' ORDER BY uid",(self.site_id,)).fetchall()

    def inspect(self, uid: str) -> dict | None:
        row = self.conn.execute("SELECT state,pending_operation FROM shared_wallet_cards WHERE site_id=%s AND uid=%s",
                                (self.site_id, uid)).fetchone()
        if not row:
            return None
        return {"state": row["state"], "pending_operation": row["pending_operation"],
                "available": row["pending_operation"] is None}
