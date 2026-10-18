"""Shared-wallet accounting kernel. No IO, relays, clocks, or implicit retries.

This is staged infrastructure, not a replacement for the live RFID workflow.
Money and pause allowances move only through explicit, journaled commands.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


class WalletConflict(ValueError):
    pass


def positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise WalletConflict(f"{name} must be a positive integer")
    return value


@dataclass
class WalletPolicy:
    visit_timeout_minutes: int = 30
    free_pause_millis: int = 60_000
    water_amount_sum: int = 1000
    water_duration_seconds: int = 40

    def __post_init__(self):
        if type(self.visit_timeout_minutes) is not int or not 1 <= self.visit_timeout_minutes <= 1440:
            raise WalletConflict("Visit timeout must be 1–1440 minutes")
        if type(self.free_pause_millis) is not int or not 0 <= self.free_pause_millis <= 86_400_000:
            raise WalletConflict("Invalid free-pause budget")


@dataclass
class WalletState:
    uid: str
    wallet_sum: int = 0
    wallet_bonus_sum: int = 0
    bonus_issued_sum: int = 0
    bonus_spent_sum: int = 0
    spent_sum: int = 0
    external_income_sum: int = 0
    opening_sum: int = 0
    visit: dict | None = None
    assignment: dict | None = None
    revision: int = 0
    card_type: str = 'customer'
    enabled: bool = True
    status: str = 'active'
    display_name: str = ''
    vip_profile: dict | None = None
    vip_visit: dict | None = None
    vip_uses: dict = field(default_factory=dict)
    service_configuration: dict = field(default_factory=dict)
    # Old intent IDs retain a visit binding; registration happens before payment.
    payment_intents: dict = field(default_factory=dict)
    funding_receipts: dict = field(default_factory=dict)

    def validate(self):
        if not isinstance(self.uid, str) or not self.uid or len(self.uid) > 80:
            raise WalletConflict("Invalid card UID")
        for name in ("wallet_sum", "spent_sum", "external_income_sum", "opening_sum", "revision", "wallet_bonus_sum", "bonus_issued_sum", "bonus_spent_sum"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise WalletConflict(f"Invalid {name}")
        assigned = self.assignment["balance_sum"] if self.assignment else 0
        if type(assigned) is not int or assigned < 0:
            raise WalletConflict("Invalid assigned balance")
        if self.wallet_sum + assigned + self.spent_sum != self.opening_sum + self.external_income_sum + self.bonus_issued_sum:
            raise WalletConflict("Money conservation check failed")
        assigned_bonus=(self.assignment or {}).get('bonus_sum',0)
        if type(assigned_bonus) is not int or not 0<=assigned_bonus<=assigned or self.wallet_bonus_sum>self.wallet_sum or self.bonus_spent_sum>self.spent_sum:
            raise WalletConflict('Invalid bonus balance')
        if self.wallet_bonus_sum+assigned_bonus+self.bonus_spent_sum!=self.bonus_issued_sum:
            raise WalletConflict('Bonus conservation check failed')
        if self.vip_visit:
            if type(self.vip_visit.get('remaining_sum')) is not int or self.vip_visit['remaining_sum'] < 0 or type(self.vip_visit.get('pause_millis')) is not int or self.vip_visit['pause_millis'] < 0:
                raise WalletConflict('Invalid VIP allowance')
        if self.assignment:
            if not self.visit or self.assignment["visit_id"] != self.visit["id"]:
                raise WalletConflict("Assignment visit mismatch")
            if self.assignment["status"] not in {"reserved", "active", "returning"}:
                raise WalletConflict("Invalid assignment status")
        if self.visit and (type(self.visit["pause_millis"]) is not int or self.visit["pause_millis"] < 0):
            raise WalletConflict("Invalid pause budget")


def apply_command(state: WalletState, command: dict, *, now: datetime,
                  policy: WalletPolicy) -> tuple[WalletState, dict]:
    """Return a new state; rejected commands cannot mutate the original.

    Operation-ID idempotency and serialization are enforced by the repository.
    Caller identity/site/authority and real hardware stop proof belong to adapters.
    A lost heartbeat deliberately has no command here that releases an assignment.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise WalletConflict("Authority time must be timezone-aware")
    state.validate()
    next_state = deepcopy(state)
    action = command.get("action")
    if action=='import_vip':
        from .vip_import_domain import apply_import
        return apply_import(state,command,now=now,policy=policy)
    if action in {'configure_vip','remove_vip','grant_vip','checkpoint_vip','return_vip'}:
        from .wallet_vip_domain import apply_vip
        return apply_vip(state,command,now=now,policy=policy)
    amount = command.get("amount_sum")
    assignment = next_state.assignment
    def bonus_amount(value):
        if type(value) is not int or value<0:raise WalletConflict('Invalid bonus amount')
        return value
    def receipt_value(source,amount,assignment_id,bonus):
        value={'source':source,'amount_sum':amount,'assignment_id':assignment_id}
        if bonus:value['bonus_sum']=bonus
        return value
    result: dict = {"action": action}

    def require_assignment(status: str):
        if not assignment or assignment["status"] != status:
            raise WalletConflict(f"Assignment must be {status}")
        if command.get("assignment_id") != assignment["id"] or command.get("post_no") != assignment["post_no"]:
            raise WalletConflict("Post assignment mismatch")
        return assignment

    if action == 'configure_service':
        if not state.uid.startswith('@') or not isinstance(command.get('value'),dict):
            raise WalletConflict('Service configuration identity required')
        next_state.service_configuration=deepcopy(command['value'])
    elif action == 'configure_customer':
        if next_state.card_type!='customer' or next_state.uid.startswith('@'):
            raise WalletConflict('Only customer cards can be configured here')
        if type(command.get('enabled')) is not bool or command.get('status') not in {'active','blocked','lost','expired'}:
            raise WalletConflict('Invalid customer card status')
        next_state.enabled=command['enabled'];next_state.status=command['status']
        next_state.display_name=str(command.get('display_name') or '')[:120]
    elif action == 'import_local_balance':
        if next_state.card_type!='customer' or assignment:
            raise WalletConflict('Local money cannot be imported into VIP or an assigned card')
        amount=positive_int(amount,'Local balance')
        receipt=command.get('receipt_id')
        if not isinstance(receipt,str) or not receipt.startswith('local-import:'):
            raise WalletConflict('Local import receipt required')
        bonus=bonus_amount(command.get('bonus_sum',0))
        if bonus>amount:raise WalletConflict('Bonus exceeds local balance')
        value=receipt_value('opening',amount,None,bonus)
        prior=next_state.funding_receipts.get(receipt)
        if prior:
            if prior!=value:raise WalletConflict('Local import receipt changed')
            return next_state,{'action':action,'already_imported':True,'wallet_sum':next_state.wallet_sum}
        if next_state.revision==0:
            if type(command.get('enabled')) is not bool or command.get('status') not in {'active','blocked','lost','expired'}:
                raise WalletConflict('Invalid source card status')
            next_state.enabled=command['enabled'];next_state.status=command['status']
            next_state.display_name=str(command.get('display_name') or '')[:120]
        next_state.funding_receipts[receipt]=value
        next_state.wallet_sum+=amount;next_state.opening_sum+=amount-bonus
        next_state.wallet_bonus_sum+=bonus;next_state.bonus_issued_sum+=bonus
    elif action == "import_opening":
        amount = positive_int(amount, "Opening balance")
        if next_state.revision != 0 or next_state.opening_sum or assignment:
            raise WalletConflict("Opening balance already initialized")
        next_state.wallet_sum = amount
        next_state.opening_sum = amount
    elif action == "wallet_credit":
        if next_state.card_type!='customer':raise WalletConflict('VIP grants cannot receive wallet money')
        bonus=bonus_amount(command.get('bonus_sum',0))
        if type(amount) is not int or amount<0 or amount+bonus<=0:raise WalletConflict('Invalid external wallet credit')
        receipt=command.get('receipt_id')
        source=command.get('source')
        if not isinstance(receipt,str) or not receipt or source not in {'cash','click'}:
            raise WalletConflict('Invalid wallet funding receipt')
        bonus=bonus_amount(command.get('bonus_sum',0))
        value=receipt_value(source,amount,None,bonus)
        existing=next_state.funding_receipts.get(receipt)
        if existing:
            if existing!=value:raise WalletConflict('Funding receipt reused with different contents')
            return next_state, {'action':action,'already_credited':True,'wallet_sum':next_state.wallet_sum}
        next_state.funding_receipts[receipt]=value
        next_state.wallet_sum+=amount+bonus
        next_state.wallet_bonus_sum+=bonus;next_state.bonus_issued_sum+=bonus
        next_state.external_income_sum+=amount
    elif action == "open_post":
        if next_state.card_type!='customer' or not next_state.enabled or next_state.status!='active':
            raise WalletConflict('Card is not an active customer card')
        if assignment:
            raise WalletConflict("Card is already assigned to a post")
        post=positive_int(command.get('post_no'),'Post number')
        amount=positive_int(amount,'Existing post credit')
        visit_id, assignment_id=command.get('visit_id'),command.get('assignment_id')
        if not isinstance(visit_id,str) or not visit_id or not isinstance(assignment_id,str) or not assignment_id:
            raise WalletConflict('Visit and assignment IDs required')
        remaining=command.get('pause_millis')
        if type(remaining) is not int or not 0 <= remaining <= policy.free_pause_millis:
            raise WalletConflict('Invalid existing pause allowance')
        old_visit=next_state.visit
        deadline=datetime.fromisoformat(old_visit['expires_at']) if old_visit and old_visit.get('expires_at') else None
        if not old_visit or (deadline and now >= deadline):
            next_state.visit={'id':visit_id,'pause_millis':remaining,'timeout_minutes':policy.visit_timeout_minutes,'expires_at':None}
        else:
            next_state.visit['pause_millis']=min(remaining,next_state.visit['pause_millis'])
            next_state.visit['expires_at']=None
        # This balance is already accounted in the post ledger, not new income
        # generated by saving it to a card. Opening credit preserves conservation.
        bonus=bonus_amount(command.get('bonus_sum',0))
        if bonus>amount:raise WalletConflict('Bonus exceeds existing balance')
        next_state.opening_sum+=amount-bonus
        next_state.bonus_issued_sum+=bonus
        next_state.assignment={'id':assignment_id,'visit_id':next_state.visit['id'],'post_no':post,
                               'status':'active','balance_sum':amount,**({'bonus_sum':bonus} if bonus else {})}
        result.update(next_state.assignment)
        result["pause_millis"]=next_state.visit["pause_millis"]
    elif action == "checkpoint":
        a=require_assignment('active')
        remaining=command.get('remaining_sum')
        pause=command.get('pause_millis')
        if type(remaining) is not int or remaining < 0 or type(pause) is not int or not 0 <= pause <= next_state.visit['pause_millis']:
            raise WalletConflict('Invalid post checkpoint')
        new_income=0
        new_bonus=0
        for funding in command.get('funding',[]):
            receipt=funding.get('id')
            if not isinstance(receipt,str) or not receipt or funding.get('source') not in {'cash','click'}:
                raise WalletConflict('Invalid funding receipt')
            value=positive_int(funding.get('amount_sum'),'Funding')
            bonus=bonus_amount(funding.get('bonus_sum',0))
            normalized=receipt_value(funding['source'],value,a['id'],bonus)
            if receipt in next_state.funding_receipts:
                if next_state.funding_receipts[receipt]!=normalized:
                    raise WalletConflict('Funding receipt reused with different contents')
            else:
                next_state.funding_receipts[receipt]=normalized
                new_income+=value
                new_bonus+=bonus
        maximum=a['balance_sum']+new_income+new_bonus
        bonus_available=a.get('bonus_sum',0)+new_bonus
        if remaining > maximum:
            raise WalletConflict('Checkpoint creates unaccounted money')
        next_state.bonus_issued_sum+=new_bonus
        bonus_left=command.get('remaining_bonus_sum',max(0,bonus_available-(maximum-remaining)))
        if type(bonus_left) is not int or not 0<=bonus_left<=min(bonus_available,remaining) or bonus_available-bonus_left>maximum-remaining:
            raise WalletConflict('Checkpoint creates or spends unaccounted bonus')
        next_state.bonus_spent_sum+=bonus_available-bonus_left
        if bonus_left or 'bonus_sum' in a:a['bonus_sum']=bonus_left
        next_state.external_income_sum+=new_income
        next_state.spent_sum+=maximum-remaining
        a['balance_sum']=remaining
        next_state.visit['pause_millis']=pause
        result['pause_millis']=pause
    elif action == "reserve_load":
        if next_state.card_type!='customer' or not next_state.enabled or next_state.status!='active':
            raise WalletConflict('Card is not an active customer card')
        if assignment:
            raise WalletConflict("Card is already assigned to a post")
        if next_state.wallet_sum <= 0:
            raise WalletConflict("Wallet is empty")
        post = positive_int(command.get("post_no"), "Post number")
        visit_id = command.get("visit_id")
        assignment_id = command.get("assignment_id")
        if not isinstance(visit_id, str) or not visit_id or not isinstance(assignment_id, str) or not assignment_id:
            raise WalletConflict("Visit and assignment IDs required")
        old_visit = next_state.visit
        deadline = datetime.fromisoformat(old_visit["expires_at"]) if old_visit and old_visit.get("expires_at") else None
        if not old_visit or (deadline and now >= deadline):
            if old_visit and old_visit["id"] == visit_id:
                raise WalletConflict("New visit requires a new ID")
            next_state.visit = {"id": visit_id, "pause_millis": policy.free_pause_millis,
                                "timeout_minutes": policy.visit_timeout_minutes, "expires_at": None}
        else:
            next_state.visit["expires_at"] = None
        next_state.assignment = {"id": assignment_id, "visit_id": next_state.visit["id"],
                                 "post_no": post, "status": "reserved", "balance_sum": next_state.wallet_sum,
                                 **({"bonus_sum":next_state.wallet_bonus_sum} if next_state.wallet_bonus_sum else {})}
        next_state.wallet_sum = 0
        next_state.wallet_bonus_sum = 0
        result.update(next_state.assignment)
        result["pause_millis"]=next_state.visit["pause_millis"]
    elif action == "accept_load":
        a = require_assignment("reserved")
        a["status"] = "active"
        result.update(a)
    elif action == "post_credit":
        a = require_assignment("active")
        amount = positive_int(amount, "Credit")
        if command.get("source") not in {"cash", "online"}:
            raise WalletConflict("Unsupported external credit source")
        # Online credit uses bound intents, not a generic post-credit operation.
        if command["source"] == "online":
            raise WalletConflict("Online credit requires a registered payment intent")
        a["balance_sum"] += amount
        next_state.external_income_sum += amount
    elif action == "register_payment":
        a = require_assignment("active")
        intent = command.get("intent_id")
        if not isinstance(intent, str) or not intent or intent in next_state.payment_intents:
            raise WalletConflict("Payment intent must be new")
        next_state.payment_intents[intent] = {"visit_id": a["visit_id"], "assignment_id": a["id"],
                                             "amount_sum": positive_int(amount, "Payment"), "credited": False}
    elif action == "confirm_payment":
        payment = next_state.payment_intents.get(command.get("intent_id"))
        if not payment:
            raise WalletConflict("Unknown payment intent")
        amount = positive_int(command.get("amount_sum"), "Payment")
        if amount != payment["amount_sum"]:
            raise WalletConflict("Payment amount mismatch")
        if payment["credited"]:
            result["already_credited"] = True
            return next_state, result
        amount = payment["amount_sum"]
        if assignment and assignment["status"] == "active" and assignment["id"] == payment["assignment_id"]:
            assignment["balance_sum"] += amount
            result["destination"] = "post"
        else:
            next_state.wallet_sum += amount
            result["destination"] = "wallet"
        next_state.external_income_sum += amount
        payment["credited"] = True
    elif action == "spend":
        a = require_assignment("active")
        amount = positive_int(amount, "Spend")
        if amount > a["balance_sum"]:
            raise WalletConflict("Insufficient post credit")
        bonus_used=min(amount,a.get("bonus_sum",0))
        if bonus_used:a["bonus_sum"]-=bonus_used
        next_state.bonus_spent_sum+=bonus_used
        a["balance_sum"] -= amount
        next_state.spent_sum += amount
    elif action == "consume_pause":
        require_assignment("active")
        elapsed = positive_int(command.get("elapsed_millis"), "Elapsed pause")
        consumed = min(elapsed, next_state.visit["pause_millis"])
        next_state.visit["pause_millis"] -= consumed
        result.update(consumed_millis=consumed, unpaid_millis=elapsed-consumed)
    elif action == "prepare_return":
        a = require_assignment("active")
        a["status"] = "returning"
        result["amount_sum"] = a["balance_sum"]
    elif action == "complete_return":
        a = require_assignment("returning")
        next_state.wallet_sum += a["balance_sum"]
        next_state.wallet_bonus_sum += a.get("bonus_sum",0)
        result["amount_sum"] = a["balance_sum"]
        next_state.assignment = None
        next_state.visit["expires_at"] = (now + timedelta(minutes=next_state.visit["timeout_minutes"])).isoformat()
    else:
        raise WalletConflict("Unknown wallet command")
    next_state.revision += 1
    next_state.validate()
    result.update(wallet_sum=next_state.wallet_sum, revision=next_state.revision)
    return next_state, result
