-- The contract-table sequence is the identifier inspectors use to distinguish
-- subtasks.  It is kept separately from any sequence carried by a generated
-- inspection-task row so the source remains auditable.
ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS contract_sequence_no TEXT;
