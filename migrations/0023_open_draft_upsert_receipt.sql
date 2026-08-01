DROP TRIGGER application_command_receipt_no_update;

UPDATE application_command_receipt
SET command_name='UpsertOpenTradePlanDraft'
WHERE command_name IN ('CreateTradePlanDraft','ReviseTradePlanDraft');

CREATE TRIGGER application_command_receipt_no_update
BEFORE UPDATE ON application_command_receipt
BEGIN
  SELECT RAISE(ABORT,'APPLICATION_COMMAND_RECEIPT_IMMUTABLE');
END;
