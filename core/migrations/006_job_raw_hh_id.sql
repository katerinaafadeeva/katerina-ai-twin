ALTER TABLE job_raw ADD COLUMN hh_vacancy_id TEXT;
CREATE INDEX IF NOT EXISTS idx_job_raw_hh_id ON job_raw(hh_vacancy_id);
