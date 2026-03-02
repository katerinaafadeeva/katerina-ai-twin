-- Migration 009: apply_runs telemetry columns
-- Adds structured fields to track letter attachment outcome and flow diagnostics.
-- All columns are nullable / have defaults for backward compatibility with existing rows.

-- Which apply path was used: 'popup' | 'inline' | 'post_apply' | 'chat' | 'quick_apply' | 'unknown'
ALTER TABLE apply_runs ADD COLUMN flow_type TEXT;

-- Letter attachment outcome:
-- 'not_requested' | 'sent_popup' | 'sent_inline' | 'sent_post_apply'
-- | 'sent_chat' | 'no_field_found' | 'chat_closed' | 'fill_failed'
ALTER TABLE apply_runs ADD COLUMN letter_status TEXT;

-- Length of the cover letter text that was attempted (chars); 0 = not requested
ALTER TABLE apply_runs ADD COLUMN letter_len INTEGER DEFAULT 0;

-- 1 if a letter textarea was found on the page (any of the 4 paths), else 0
ALTER TABLE apply_runs ADD COLUMN textarea_found INTEGER DEFAULT 0;

-- What was detected on the page after clicking apply:
-- 'popup_submit' | 'inline_form' | 'success_toast' | 'response_sent'
-- | 'already_applied' | 'captcha' | 'external' | 'questionnaire' | 'phone' | 'unknown'
ALTER TABLE apply_runs ADD COLUMN detected_outcome TEXT;

-- URL of the page after all actions (may differ from apply_url if redirected to chat)
ALTER TABLE apply_runs ADD COLUMN final_url TEXT;

-- 1 if the employer chat button (RESPONSE_TOPIC_LINK) was visible after apply, else 0
ALTER TABLE apply_runs ADD COLUMN chat_available INTEGER DEFAULT 0;
