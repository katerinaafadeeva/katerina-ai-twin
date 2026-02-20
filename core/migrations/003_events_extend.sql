ALTER TABLE events ADD COLUMN actor TEXT DEFAULT 'system';
ALTER TABLE events ADD COLUMN correlation_id TEXT;
