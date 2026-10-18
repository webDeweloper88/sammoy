"""Persist random identities on new rows; never rename historical receipts."""
FINANCIAL_IDS_SQL = r'''
CREATE OR REPLACE FUNCTION sammoy_payment_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.raw_payload := COALESCE(NEW.raw_payload, '{}'::jsonb) ||
    jsonb_build_object('wallet_receipt_id', 'payment:' || gen_random_uuid()::text);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS sammoy_payment_identity ON payments;
CREATE TRIGGER sammoy_payment_identity BEFORE INSERT ON payments
  FOR EACH ROW EXECUTE FUNCTION sammoy_payment_identity();
CREATE OR REPLACE FUNCTION sammoy_recovery_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.metadata := COALESCE(NEW.metadata, '{}'::jsonb) ||
    jsonb_build_object('wallet_recovery_id', 'recovery:' || gen_random_uuid()::text);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS sammoy_recovery_identity ON recovery_credits;
CREATE TRIGGER sammoy_recovery_identity BEFORE INSERT ON recovery_credits
  FOR EACH ROW EXECUTE FUNCTION sammoy_recovery_identity();
'''
