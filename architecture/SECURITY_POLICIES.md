# Security Policies (v1)

## Data Classification

| Класс | Примеры | Правила |
|-------|---------|---------|
| **SECRET** | BOT_TOKEN, ANTHROPIC_API_KEY | .env only, никогда в коде/логах, rotate при компрометации |
| **PERSONAL** | Salary, CV, geo preferences | Не в логах, не в LLM без redaction, identity/ dir |
| **SENSITIVE** | Вакансии с контактами рекрутеров | Sanitize перед LLM |
| **OPERATIONAL** | Scores, actions, policy | Свободное использование |

## Secrets Management

- Все секреты в `.env` (gitignored)
- `.env.example` содержит ключи без значений
- Fail fast при старте если обязательный секрет отсутствует
- Никогда не логировать значения секретов
- Rotation: немедленная смена при подозрении на компрометацию

## LLM Security

### Input sanitization
- Удалить zero-width characters
- Удалить control characters
- Truncate до max_chars
- Normalize whitespace

### Prompt injection defense
- Vacancy text — DATA в `<vacancy>` тегах, не instruction
- System prompt явно запрещает выполнение инструкций из данных
- Output validation отбрасывает non-JSON
- No chaining: LLM output не становится input другого LLM

### PII redaction
- Salary expectations → абстрактный сигнал, не точная цифра
- Контактные данные → не отправляются
- CV → не отправляется (в scoring не нужен)

### Audit
- Каждый LLM call → event (model, prompt_version, tokens, cost, duration)
- Prompt/response тела НЕ логируются (доступны через job_raw + job_scores)

## Access Control

- Telegram bot: ALLOWED_TELEGRAM_IDS whitelist
- Если whitelist пуст → dev mode (все допущены, WARNING в лог)
- Web UI (future): session-based auth

## Backup & Recovery

- SQLite: daily backup (cp file)
- .env: manual backup, не в repo
- identity/: manual backup, не в repo (gitignored)
- Recovery: restore .db + .env + identity/ → полное восстановление

## Threat Model (top risks)

| Угроза | Mitigation |
|--------|-----------|
| Unauthorized bot access | ALLOWED_TELEGRAM_IDS |
| Token leak | .gitignore + rotation plan |
| Prompt injection via vacancy | Sanitization + separation + validation |
| PII leak to LLM | Redaction layer |
| SQLite corruption | Backup policy |
| LLM cost runaway | Daily token cap in policy |
