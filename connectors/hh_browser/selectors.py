"""HH.ru DOM selectors for the apply flow.

Keep selectors in one place so they can be updated when HH changes markup.
All selectors use data-qa attributes (more stable than class names).
"""

# --- Vacancy page ---
# Primary apply button at the top of the page
APPLY_BUTTON = "[data-qa='vacancy-response-link-top']"
# Alternative apply button at the bottom
APPLY_BUTTON_BOTTOM = "[data-qa='vacancy-response-link-bottom']"
# Indicator shown when candidate already applied
ALREADY_APPLIED = "[data-qa='vacancy-response-exist']"
# Vacancy title (used to confirm page load)
VACANCY_TITLE = "[data-qa='vacancy-title']"

# --- Apply modal dialog ---
# Textarea for optional cover letter
COVER_LETTER_TEXTAREA = "[data-qa='vacancy-response-popup-letter']"
# Submit button inside the apply modal
SUBMIT_BUTTON = "[data-qa='vacancy-response-submit-popup']"
# Close button (used for cleanup after apply)
MODAL_CLOSE = "[data-qa='vacancy-response-popup-close']"

# --- Auth / session ---
# Login button — indicates session has expired
AUTH_LOGIN_BUTTON = "[data-qa='login-button']"
# Auth form input — secondary session check
AUTH_EMAIL_INPUT = "[data-qa='account-signup-email']"

# --- Captcha ---
# Captcha container — if visible, stop the batch
CAPTCHA_WRAPPER = "[data-qa='captcha']"
# reCAPTCHA iframe alternative
RECAPTCHA_IFRAME = "iframe[src*='recaptcha']"
# SmartCaptcha from Yandex (also used on HH)
SMARTCAPTCHA_IFRAME = "iframe[src*='captcha.yandex']"
