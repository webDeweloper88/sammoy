"""Bonus is promotional credit, never cash revenue. Whole-sum rounding down."""
from math import ceil
BONUS_SCHEMA_SQL="""
ALTER TABLE mode_usage ADD COLUMN IF NOT EXISTS bonus_spent_sum BIGINT NOT NULL DEFAULT 0 CHECK(bonus_spent_sum>=0);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS bonus_sum BIGINT NOT NULL DEFAULT 0 CHECK(bonus_sum>=0);
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS bonus_remaining_sum BIGINT NOT NULL DEFAULT 0 CHECK(bonus_remaining_sum>=0);
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS bonus_granted_sum BIGINT NOT NULL DEFAULT 0 CHECK(bonus_granted_sum>=0);
ALTER TABLE wash_sessions ADD COLUMN IF NOT EXISTS bonus_spent_sum BIGINT NOT NULL DEFAULT 0 CHECK(bonus_spent_sum>=0);
ALTER TABLE rfid_cards ADD COLUMN IF NOT EXISTS bonus_sum BIGINT NOT NULL DEFAULT 0 CHECK(bonus_sum>=0);
ALTER TABLE recovery_credits ADD COLUMN IF NOT EXISTS bonus_sum BIGINT NOT NULL DEFAULT 0 CHECK(bonus_sum>=0);
ALTER TABLE click_payment_intents ADD COLUMN IF NOT EXISTS bonus_sum BIGINT CHECK(bonus_sum>=0);
CREATE OR REPLACE FUNCTION capture_recovery_bonus() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 SELECT LEAST(NEW.amount_sum,bonus_remaining_sum) INTO NEW.bonus_sum FROM wash_sessions WHERE id=NEW.wash_session_id;
 NEW.bonus_sum=COALESCE(NEW.bonus_sum,0);
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS recovery_bonus_insert ON recovery_credits;
CREATE TRIGGER recovery_bonus_insert BEFORE INSERT ON recovery_credits FOR EACH ROW EXECUTE FUNCTION capture_recovery_bonus();
"""
def policy(value):
    value=value or {}
    if not isinstance(value,dict) or type(value.get('enabled',False)) is not bool or type(value.get('percent',10)) is not int or not 0<=value.get('percent',10)<=100:
        raise ValueError('Bonus: enabled must be boolean, percent must be an integer 0–100')
    return {'enabled':value.get('enabled',False),'percent':value.get('percent',10)}
def award(amount,params):
    p=policy(params.get('topUpBonus'))
    return int(amount)*p['percent']//100 if p['enabled'] else 0
def remaining(runtime):
    return min(int(runtime.state.get('creditSum') or 0),max(0,int(ceil(runtime.state.get('_bonusFloat',runtime.state.get('bonusSum',0))))))
def add(runtime,amount):
    runtime.state['_bonusFloat']=float(runtime.state.get('_bonusFloat',runtime.state.get('bonusSum',0)))+amount
    runtime.state['bonusSum']=remaining(runtime)
def spend(runtime,amount):
    before=float(runtime.state.get('_bonusFloat',runtime.state.get('bonusSum',0)))
    runtime.state['_lastBonusSpend']=min(before,amount)
    runtime.state['_bonusFloat']=max(0.,before-amount)
    runtime.state['bonusSum']=remaining(runtime)
def restore(runtime,amount):
    runtime.state['_bonusFloat']=float(amount or 0);runtime.state['bonusSum']=remaining(runtime)
