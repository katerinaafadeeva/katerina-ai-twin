# CJM — AI Twin Career OS (MVP v1)
## Customer Journey Map — Финальная версия

**Версия:** 2.0 (Playwright Pivot)
**Дата:** 2026-02-24
**Контекст:** HH applicant API закрыт (дек 2025). Apply через Playwright.

---

## Роли и артефакты

| Компонент | Роль | Технология |
|-----------|------|-----------|
| **Ты (Катя)** | Единственный пользователь и оператор | — |
| **Telegram-бот** | Пульт управления | python-telegram-bot |
| **SQLite** | Память системы | job_raw, job_scores, actions, events, cover_letters, hh_applications |
| **HH API** | Глаза (поиск вакансий) | Anonymous REST API, GET /vacancies |
| **Playwright** | Руки (клики, отклики) | Browser automation, headless Chromium |
| **LLM** | Мозг (scoring + cover letters) | Claude Haiku (по лимитам) |

---

## Этап 0. Один раз: установка и включение

### 0.1 Установка
```bash
pip install -r requirements.txt
playwright install chromium
```

### 0.2 Конфиг (.env)
```
HH_ENABLED=true
SCORING_DAILY_CAP=100
APPLY_DAILY_CAP=20
COVER_LETTER_DAILY_CAP=50
APPLY_MIN_DELAY=3
APPLY_MAX_DELAY=8
ALLOWED_TELEGRAM_IDS=...
HH_SEARCHES_PATH=identity/hh_searches.json
HH_STORAGE_STATE_PATH=data/hh_storage_state.json
```

### 0.3 Подготовка "рук" (Playwright)

Ты запускаешь команду: `/hh_login` в Telegram

1. Playwright открывает Chromium (видимое окно, НЕ headless)
2. Ты логинишься сама на hh.ru (логин/пароль/2FA)
3. Playwright сохраняет сессию: `data/hh_storage_state.json`
4. Окно закрывается
5. Бот подтверждает: "✅ Сессия HH сохранена"

**Это не пароль.** Это cookies + localStorage браузерной сессии. Пароль нигде не хранится.

### 0.4 Поисковые запросы

Создаёшь файл `identity/hh_searches.json`:
```json
[
  {"text": "Product Manager", "area": "1", "schedule": "remote"},
  {"text": "Product Owner", "area": "113", "experience": "between3And6"}
]
```

### 0.5 Cover letter шаблоны

Создаёшь `profile/cover_letter_templates.md`:
```markdown
# Шаблон: Product Manager
Ключевые слова: продукт, стратегия, roadmap, метрики
Стиль: деловой, конкретный

# Шаблон: Tech / BD
Ключевые слова: технический, партнёрства, интеграции
Стиль: энергичный, проектный
```

И `profile/cover_letter_fallback.txt`:
```
Добрый день! Ваша вакансия мне интересна, я готова обсудить подробности. Буду рада возможности внести вклад в развитие вашей команды.
```

---

## Этап 1. Каждый день: сбор вакансий

### 1.1 HH Ingest (автоматически, по расписанию)

**Способ: HH REST API (анонимный, без OAuth)**

- Агент каждый час отправляет GET-запросы к `api.hh.ru/vacancies`
- По запросам из `hh_searches.json`
- Каждая вакансия сохраняется в job_raw: source="hh", hh_vacancy_id, url, raw_text
- Дедуп: по hh_vacancy_id + canonical_key (кросс-источник)

**Почему API, а не Playwright:** API быстрее, надёжнее, даёт структурированный JSON. Playwright — только для действий с авторизацией.

### 1.2 Telegram Ingest (как сейчас)

Ты можешь переслать вакансию вручную в бота (source="telegram").

---

## Этап 2. Оценка и решение

### 2.1 Pre-filter (без LLM, бесплатно)
- Запрещённые индустрии → reject
- Negative signals (MLM, cold calling, gambling) → reject
- Неподходящая география → reject (если настроено)

Экономит ~25% токенов.

### 2.2 Scoring (LLM 0–10, с дневным лимитом)
- Максимум SCORING_DAILY_CAP в день
- Если лимит закончился → вакансии ждут в БД до завтра
- Уведомление: "⚠️ Лимит скоринга достигнут"

### 2.3 Policy (детерминированно, без LLM)

| Score | Действие | Что происходит |
|-------|----------|----------------|
| < 5 | IGNORE | Тишина |
| 5-6, source=hh | AUTO_APPLY | Cover letter → Playwright apply |
| 5-6, source=tg | AUTO_QUEUE | Queued (без apply — TG вакансии без URL) |
| 5-6, лимит действий | HOLD | Ждёт до завтра |
| ≥ 7 | APPROVAL_REQUIRED | В Telegram с кнопками |

---

## Этап 3. Операторский цикл (Telegram)

### 3.1 Что ты видишь

**APPROVAL_REQUIRED (score ≥ 7):**
```
📋 Вакансия: Product Manager @ Yandex
⭐ Score: 8/10
💡 Причины: remote, AI-продукт, метрики
📝 Сопроводительное (черновик):
"Добрый день! Ваш продукт..."

[✅ Approve] [❌ Reject] [⏸ Snooze]
```

**AUTO_APPLY уведомления (score 5-6):**
```
✅ Отклик отправлен: Junior PM @ Сбер (score: 6)
```
или
```
🧩 Нужен тест — откликнитесь вручную: https://hh.ru/vacancy/12345
```

### 3.2 Команды

| Команда | Что делает |
|---------|-----------|
| `/today` | Что произошло сегодня (applied, rejected, pending) |
| `/stats` | Статистика + список ожидающих approval |
| `/limits` | Текущие лимиты и остатки |
| `/hh_login` | Обновить сессию HH |

---

## Этап 4. Сопроводительное письмо

### 4.1 Когда генерируется

| Ситуация | Действие |
|----------|----------|
| AUTO_APPLY (HH, 5-6) | Генерируем автоматически (LLM) |
| APPROVAL_REQUIRED (≥7) | Генерируем и показываем в карточке |
| LLM cap достигнут | Используем fallback шаблон |
| LLM API недоступен | Используем fallback шаблон |

### 4.2 Стиль

Режим A (MVP): шаблоны в `profile/cover_letter_templates.md`. Агент адаптирует под вакансию через LLM.

Режим B (позже): редактирование через Telegram (`/template show`, `/template set`).

Режим C (позже): правка перед отправкой через кнопку "Edit" в Telegram.

---

## Этап 5. Авто-отклик через Playwright

### 5.1 Очередь на apply

Агент собирает список AUTO_APPLY + approved APPROVAL_REQUIRED и идёт по ним:
- Не быстрее APPLY_DAILY_CAP в день
- Случайная задержка APPLY_MIN_DELAY–APPLY_MAX_DELAY секунд между действиями

### 5.2 Шаги авто-отклика

Для каждой вакансии:

1. **Открывает вакансию** в Playwright по URL
2. **Проверяет авторизацию:**
   - Если экран логина → СТОП → "/hh_login required"
3. **Ищет кнопку "Откликнуться"** (`data-qa="vacancy-response-link-top"`)
4. **Проверяет ограничения:**
   - Уже откликались → skip (ALREADY_APPLIED)
   - Direct/внешний сайт → skip (MANUAL_REQUIRED)
   - Тест/анкета обнаружены → skip (MANUAL_REQUIRED)
   - CAPTCHA → screenshot → TG → BLOCKED_CAPTCHA
5. **Кликает "Откликнуться"**
6. **Выбирает резюме** (если несколько — по HH_DEFAULT_RESUME_NAME)
7. **Вставляет сопроводительное** в текстовое поле
8. **Нажимает "Отправить"**
9. **Проверяет подтверждение**
10. **Записывает в БД и отправляет в TG**

### 5.3 Результаты apply

| Статус | TG сообщение | DB status |
|--------|-------------|-----------|
| Успех | ✅ "Отклик отправлен: {name}" | applied |
| Уже откликались | ℹ️ "Уже откликались ранее" | already_applied |
| Нужен тест | 🧩 "Нужен тест — вручную: {url}" | manual_required |
| Direct (внешний) | 🔗 "Внешний отклик: {url}" | manual_required |
| CAPTCHA | 🔒 "Требуется CAPTCHA" + скриншот | blocked_captcha |
| Auth expired | ⚠️ "Нужен логин → /hh_login" | blocked_auth |
| Ошибка | ❌ "Ошибка: {error}" + скриншот | failed |

---

## Этап 6. Ошибки и восстановление

### 6.1 Сессия HH протухла
- Playwright обнаруживает экран логина
- НЕ пытается подбирать пароль
- Все apply → `blocked_auth`
- TG: "⚠️ Сессия истекла → /hh_login"
- Ingest (API) продолжает работать

### 6.2 CAPTCHA
- Playwright делает скриншот
- TG: скриншот + "🔒 Требуется CAPTCHA"
- Apply приостановлен
- Ты решаешь CAPTCHA вручную или делаешь /hh_login
- НЕ используем сервисы решения CAPTCHA

### 6.3 HH "защитился" от частых действий
- Playwright увеличивает задержки (exponential backoff)
- Ставит паузу и уведомляет тебя
- Не продолжает агрессивно — чтобы не получить бан

### 6.4 LLM лимит/ошибки
- Если cap на cover letters достигнут → fallback шаблон
- Если LLM API недоступен → fallback шаблон
- Scoring cap достигнут → вакансии ждут до завтра

### 6.5 HH изменил UI
- Playwright не находит ожидаемые элементы
- Apply → failed со скриншотом
- TG: "⚠️ HH изменил интерфейс. Нужно обновить selectors."
- Ты обновляешь `selectors.py` (один файл, 5 минут)

---

## Этап 7. Бизнес-результат

Через 1–2 дня работы:
- HH вакансии сами попадают в воронку
- Мусор исчезает (IGNORE)
- Хорошие:
  - Score 5-6: откликаются сами с сопроводительным
  - Score ≥7: просят твоего одобрения
- Сопроводительные формируются автоматически
- **Твоя "ручная работа" = только approve/reject для топа + ручные кейсы (тесты/анкеты) + /hh_login раз в 2-4 недели**

---

## Безопасность

| Что | Как |
|-----|-----|
| Пароль HH | Нигде не хранится. Логин только вручную в браузере. |
| Сессия браузера | `data/hh_storage_state.json` — локально, gitignored |
| Cookies/токены | Никогда в логах, events, git |
| Скорость apply | 3-8 сек задержка, max 20-40/day — как обычный человек |
| Если что-то подозрительное | Агент останавливается и спрашивает тебя |
| CAPTCHA | Только ручное решение, никаких bypass-сервисов |
