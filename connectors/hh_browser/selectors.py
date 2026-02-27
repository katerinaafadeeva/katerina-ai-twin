"""HH.ru DOM selectors for the apply flow.

Keep selectors in one place so they can be updated when HH changes markup.
All selectors use data-qa attributes (more stable than class names).

HH has TWO apply paths:
  Path A — Popup:      click apply → modal opens → fill COVER_LETTER_TEXTAREA → click SUBMIT_BUTTON
  Path B — Inline:     click apply → page updates → INLINE_LETTER_FORM appears →
                       fill INLINE_LETTER_TEXTAREA → click INLINE_LETTER_SUBMIT
"""

# --- Vacancy page ---
# Primary apply button at the top of the page
APPLY_BUTTON = "[data-qa='vacancy-response-link-top']"
# Alternative apply button at the bottom
APPLY_BUTTON_BOTTOM = "[data-qa='vacancy-response-link-bottom']"
# Indicator shown when candidate already applied (pre-click check)
ALREADY_APPLIED = "[data-qa='vacancy-response-exist']"
# "Чат" button — appears after quick-apply succeeds (strong already-applied indicator)
RESPONSE_TOPIC_LINK = "[data-qa='vacancy-response-link-view-topic']"
# Vacancy title (used to confirm page load)
VACANCY_TITLE = "[data-qa='vacancy-title']"

# --- Apply modal dialog (Path A — popup) ---
# Textarea for optional cover letter inside the popup
COVER_LETTER_TEXTAREA = "[data-qa='vacancy-response-popup-letter']"
# Submit button inside the apply modal popup
SUBMIT_BUTTON = "[data-qa='vacancy-response-submit-popup']"
# Close button (used for cleanup after apply)
MODAL_CLOSE = "[data-qa='vacancy-response-popup-close']"

# --- Inline apply path (Path B — quick apply / no popup) ---
# Container for the inline cover letter form (appears after quick apply succeeds).
# Confirmed in production artifact: vacancy-response-letter-informer is present
# on the page along with RESPONSE_TOPIC_LINK when quick apply path is used.
# Filling this form sends the cover letter to the employer chat.
INLINE_LETTER_FORM = "[data-qa='vacancy-response-letter-informer']"
# Textarea inside the inline form
INLINE_LETTER_TEXTAREA = "[data-qa='vacancy-response-letter-informer'] textarea"
# Submit button for the inline letter form
INLINE_LETTER_SUBMIT = "[data-qa='vacancy-response-letter-submit']"

# --- Post-click success indicators ---
# Toast / banner: "Отклик отправлен" (quick success feedback)
SUCCESS_TOAST = "[data-qa='bloko-notification']"
# Vacancy page re-renders to "already applied" state after quick apply
RESPONSE_SENT_LABEL = "[data-qa='vacancy-response-sent']"

# --- Cookies consent banner ---
# Accept button on the cookies policy banner (may block interactions if not dismissed)
COOKIES_ACCEPT = "[data-qa='cookies-policy-informer-accept']"

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
