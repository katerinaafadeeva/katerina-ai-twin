ALTER TABLE actions ADD COLUMN score INTEGER;
ALTER TABLE actions ADD COLUMN reason TEXT;
ALTER TABLE actions ADD COLUMN actor TEXT DEFAULT 'policy_engine';
ALTER TABLE actions ADD COLUMN correlation_id TEXT;
