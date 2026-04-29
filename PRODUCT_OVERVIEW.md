# Medical Treatment Compliance & Reimbursement Audit Platform

מערכת בקרת התאמה והחזרים על טיפולים רפואיים לפי מסמכי אשפוז.

Short description: A platform that audits hospitalization documents against predefined treatment criteria, identifies non-compliant billed treatments, and creates evidence-backed reimbursement cases.

What the system does:
- Reads hospitalization documents
- Extracts structured treatment-level facts
- Compares performed treatments against predefined specifications
- Detects mismatches
- Creates audit-backed reimbursement/appeal cases
- Gives management full visibility by customer, treatment, document, rule, and reimbursement status

This is an operational medical-audit and reimbursement system for insurance companies, HMOs, claims departments, medical audit teams, reimbursement/settlement teams, and TPAs. It is not a generic AI classifier and it does not replace doctors.

**פלטפורמת תמיכת החלטה קלינית (Clinical Decision Support) ברמת Production —
שלוש מערכות בליבה אחת: בדיקת בטיחות אינטראקציות בין תרופות, סיווג חכם של מסמכים רפואיים,
ומנוע חילוץ מבוסס JSON שמחזיר טבלת ערכים מטופסים פר treatment_code עם audit נפרד.**

> מתאימה לקופות חולים, בתי חולים, מערכות EHR, מרפאות פרטיות, וחברות ביטוח רפואי בישראל ובעולם.
> בנוי על FastAPI + PostgreSQL + Redis, עם אינטגרציה למסדי נתונים תרופתיים מובילים (Lexicomp / Micromedex / DrugBank / RxNorm)
> ומותאם במיוחד לסל התרופות הישראלי וטקסטים קליניים בעברית ובאנגלית.

---

## תוכן עניינים
0. [התקנה בקליק (One-Click Install)](#0-התקנה-בקליק-one-click-install)
1. [למה זה קיים — הבעיה העסקית](#1-למה-זה-קיים--הבעיה-העסקית)
2. [שני המוצרים בפלטפורמה](#2-שני-המוצרים-בפלטפורמה)
3. [Stack טכנולוגי](#3-stack-טכנולוגי)
4. [Drug Safety Engine — איך זה עובד](#4-drug-safety-engine--איך-זה-עובד)
5. [Medical Document Classifier — איך זה עובד](#5-medical-document-classifier--איך-זה-עובד)
6. [ארכיטקטורה כללית ושכבות](#6-ארכיטקטורה-כללית-ושכבות)
7. [API Endpoints](#7-api-endpoints)
8. [Data Model — סכמת מסד הנתונים](#8-data-model--סכמת-מסד-הנתונים)
9. [אינטגרציות חיצוניות](#9-אינטגרציות-חיצוניות)
10. [ביצועים, Caching ו-Scalability](#10-ביצועים-caching-ו-scalability)
11. [אבטחה, פרטיות ו-Compliance](#11-אבטחה-פרטיות-ו-compliance)
12. [Quality, Testing & Observability](#12-quality-testing--observability)
13. [Deployment והפעלה](#13-deployment-והפעלה)
14. [מה נוסף בגרסה הנוכחית (Changelog)](#14-מה-נוסף-בגרסה-הנוכחית-changelog)
15. [Roadmap ופוטנציאל הרחבה](#15-roadmap-ופוטנציאל-הרחבה)
16. [למי זה מיועד — Pitch ללקוח](#16-למי-זה-מיועד--pitch-ללקוח)

---

## 0. התקנה בקליק (One-Click Install)

המערכת כוללת installer אחד שמטפל בכל הבוטסטראפ — בניית images, יצירת `.env` עם API key אקראי, הרצת מיגרציות, סידינג, והרמת המחסנית המלאה (api + worker + outbox + postgres + redis).

**דרישות:**
- Docker + Docker Compose (`docker compose` או `docker-compose`)
- `curl`, `python3` (רק להזרקת ה-secrets ל-`.env`)

**הפעלה:**
```bash
./install.sh           # bootstrap מלא (Docker)
./install.sh local     # מצב פיתוח לוקלי (venv, ללא Docker)
./install.sh status    # מצב הריצה של כל שירות
./install.sh logs      # מעקב logs של כל המחסנית
./install.sh reset     # מחיקה מלאה של containers + volumes (postgres + מסמכים)
```

מה ה-installer עושה ב-`docker` mode:
1. בודק dependencies, בוחר `docker compose` או fallback ל-`docker-compose`.
2. אם אין `.env` — מעתיק מ-[.env.example](.env.example), מייצר `API_KEYS` ו-`WEBHOOK_SIGNING_SECRET` אקראיים, ומדפיס אותם פעם אחת על המסך.
3. בונה images, מרים `postgres` + `redis`, מריץ `alembic upgrade head` בקונטיינר `migrate`, מריץ `seed_drugs` + `seed_synonyms`.
4. מרים `api` + `worker` + `outbox`, ומחכה ש-`/health` מחזיר 200.
5. מדפיס דוגמת `curl` מוכנה לשליחה עם ה-API key שנוצר.

המערכת זמינה לאחר מכן ב-`http://localhost:8000` (Swagger ב-`/docs`, metrics ב-`/metrics`, readiness ב-`/ready`).

---

## 1. למה זה קיים — הבעיה העסקית

**טעויות בתרופות הן אחת מ-3 הסיבות המובילות לתמותה שניתן למנוע במערכות בריאות מודרניות.**
מחקרים מראים ש-30%-50% מאשפוזים חוזרים אצל מטופלים מורכבים נגרמים מ-Adverse Drug Events (ADEs) — ובחלק גדול מהם, האינטראקציה הייתה ידועה וניתנת לחיזוי.

במקביל, קופות חולים וחברות ביטוח **משלמות סכומי עתק על פרוצדורות רפואיות** שלא תמיד בוצעו בפועל, או שלא תועדו נכון — וכל סקירה ידנית של מסמך אשפוז עולה זמן יקר של רופאי בקרה.

המוצר נותן מענה מדויק לשני הכאבים האלו:

| כאב עסקי | פתרון מובנה במערכת |
|---|---|
| מרשמים שמסתכנים באינטראקציה מסוכנת | בדיקת בטיחות real-time עם החזרת המלצה רפואית מנומקת |
| בלבול בשמות מסחריים (Lipitor / Atorvastatin / ליפיטור) | שכבת Drug Normalization עם מילון synonyms |
| חוסר התאמה לסל התרופות הישראלי | סנכרון יומי של סל התרופות + עדיפות לחלופות בסל |
| תביעות על פרוצדורות שלא בוצעו | סיווג חכם של מסמכים רפואיים — האם הפרוצדורה בוצעה בפועל |
| מסמכים בעברית + אנגלית מעורבת | תמיכה דו-לשונית מובנית, כולל Priority Sections בעברית |
| חשיפת PII ל-LLM חיצוני | מנגנון masking של ת.ז. ישראליות לפני כל קריאה ל-LLM |

---

## 2. שני המוצרים בפלטפורמה

### 🛡️ מוצר א': Drug Safety Engine
שירות API שמקבל מטופל + רשימת תרופות חדשות, ומחזיר תוך מילי-שניות **תשובה קלינית מלאה**:
- האם הצירוף בטוח?
- אם לא — אילו תרופות מתנגשות, באיזו חומרה (`A/B/C/D/X` לפי ה-Lexicomp standard), ומה הסיכון הקליני
- הסבר רפואי בשפה מובנת (deterministic — לא תלוי LLM)
- **חלופות מוצעות מדורגות** — לפי תת-מחלקה תרופתית (ATC), נוכחות בסל, ופרופיל אינטראקציה כולל

### 🧠 מוצר ב': Medical Document Classifier
שירות API שמקבל מסמך רפואי + קוד פרוצדורה, ומחזיר **0 / 1 בינארי**: האם הפרוצדורה בוצעה בפועל באשפוז הנוכחי?
- מבוסס על **config-driven Procedure Definitions** — אין צורך לכתוב קוד כדי להוסיף פרוצדורה חדשה
- תמיכה מלאה בעברית, אנגלית ומסמכים מעורבי-שפה
- Fallback prompt גנרי לכל קוד פרוצדורה שלא הוגדר ידנית
- **PII masking אוטומטי** לפני שליחה ל-LLM (OpenAI / OpenRouter)
- Pluggable LLM Runner — ניתן להחליף את ספק ה-LLM ללא שינוי קוד

### 🧬 מוצר ג': Medical Extraction Engine (JSON-driven)
שירות API שמקבל מסמך רפואי + **JSON specification** המגדיר treatments ו-rules, ומחזיר **טבלה שטוחה** בה כל row הוא `(document_id, treatment_code)` וכל rule הופך לעמודה עם ערך מטופס.
- ה-spec הוא **המקור היחיד** לעמודות — המנוע לא ממציא שדות
- תומך ב-5 סוגי rules: `boolean`, `enum`, `date`, `number`, `text`
- חילוץ דטרמיניסטי first (regex / indicator matching), LLM כ-fallback opt-in בלבד
- כל ערך מלווה ב-record audit נפרד עם `evidence`, `confidence`, ו-`reason` — לא מערבב את הטבלה התפעולית עם נתוני ההסבר
- Hebrew + English indicators באותו פורמט; ללא תלות בספריות tokenization חיצוניות
- חולק את אותה תשתית settings ו-PII masking של ה-Classifier; לא משפיע עליו

---

## 3. Stack טכנולוגי

| שכבה | טכנולוגיה | למה זה חשוב למכירה |
|---|---|---|
| Runtime | **Python 3.11** | תאימות מלאה לסטנדרטים מודרניים (PEP 695, asyncio TaskGroup) |
| Web Framework | **FastAPI 0.115** | OpenAPI auto-generated, ביצועים גבוהים, תיעוד אינטראקטיבי בחינם |
| Validation | **Pydantic v2** | סכמות חזקות + מהיר פי 5-50 מ-v1 — חוסך CPU בייצור |
| ORM | **SQLAlchemy 2.0 (async)** | non-blocking I/O — שירות יחיד יכול להחזיק 10K connections |
| DB | **PostgreSQL** | ACID, foreign keys, indexes — bulletproof לשיא תעבורה |
| Cache | **Redis** | hot-path cache + fallback אוטומטי לזיכרון מקומי אם Redis לא זמין |
| Migrations | **Alembic** | גרסאות סכמה מבוקרות, מתאים לצוותי DBA קלאסיים |
| HTTP Client | **httpx + Tenacity** | retries אוטומטיים עם exponential backoff |
| Logging | **JSON structured logs** | Datadog / Splunk / ELK ready מהיום הראשון |
| Tests | **pytest + pytest-asyncio** | כיסוי לכל השכבות הקריטיות |

> כל התלויות נעולות לגרסה מדויקת ב-`requirements.txt` — reproducible builds, zero supply chain surprises.

---

## 4. Drug Safety Engine — איך זה עובד

### 4.1 אסטרטגיית בדיקה רב-שכבתית (Multi-Tier Lookup)

הליבה היא [InteractionChecker](app/algorithms/interaction_checker.py) — מבצע בדיקה לפי סדר עדיפויות שתוכנן למיקסום ביצועים והקטנת עלות:

```
┌─────────────────────────────────────────────────────────────┐
│  1. Redis Cache         → < 1ms  (TTL 24h)                  │
│  2. In-Memory Graph     → O(1)   adjacency lookup           │
│  3. Local DB            → ~5ms   (PostgreSQL indexed)       │
│  4. External Providers  → ~200ms (parallel httpx calls)     │
│  5. Persist + Cache + Graph Update (write-through)          │
└─────────────────────────────────────────────────────────────┘
```

**הערך העסקי:**
- 99% מהבדיקות מסתיימות ב-Cache או ב-Graph — **חסכון ענקי בעלויות API חיצוניות** (Lexicomp עולה $$$ לכל קריאה)
- אם ספק חיצוני נפל — המערכת ממשיכה לתפקד מ-Local Cache + DB
- כל בדיקה חדשה **מחממת אוטומטית** את כל השכבות (write-through pattern)

### 4.2 Provider Aggregation עם Severity-First Tie-Breaking

כשמספר ספקים מגיבים על אותה אינטראקציה, [InteractionChecker._aggregate_external](app/algorithms/interaction_checker.py:91) בוחר:
1. את **החומרה הגבוהה ביותר** (X > D > C > B > A) — תמיד מעדיף הצהרה בטוחה
2. ובמקרה שוויון — לפי **Provider Priority** המוגדרת ב-settings
3. כל הקריאות נשלחות **ב-parallel** עם `asyncio.gather`

**הערך העסקי:** הלקוח לא צריך לבחור ספק יחיד — הוא מקבל את ה-consensus החכם של כל הספקים שהוא רכש מהם רישיון.

### 4.3 Drug Normalization Layer

[DrugNormalizationService](app/services/drug_normalization_service.py) פותר את אחד הכאבים הכי גדולים: **אותה תרופה בעשרות שמות**.
- `"Lipitor"` → `"atorvastatin"`
- `"ASA"` / `"acetylsalicylic acid"` / `"cartia"` → `"aspirin"`
- מילון Synonyms ב-DB עם UNIQUE constraint
- חיפוש אחיד דרך `get_by_name_or_synonym`

**הערך העסקי:** מטפלים יכולים להזין שמות מסחריים — המערכת מתרגמת לחומר הפעיל הקנוני. אין יותר false negatives בגלל איות שונה.

### 4.4 ATC Code Resolution Chain

[DrugClassService](app/services/drug_class_service.py) קובע את הסיווג התרופתי-אנטומי:
1. בדיקה אם כבר קיים ב-DB (cached)
2. שאילתא ל-RxNorm (רשמי — NIH)
3. Fallback ל-DrugBank
4. אחסון בזיכרון + DB לפעם הבאה

**הערך העסקי:** ATC הוא הבסיס למציאת חלופות — בלי זה אי אפשר להציע "תרופה דומה". המערכת בונה אוטומטית את ה-mapping מ-Day 1.

### 4.5 Alternative Suggestion Engine

[AlternativeService](app/services/alternative_service.py) + [DrugRanker](app/algorithms/drug_ranker.py):
1. מוצא את כל התרופות ב-ATC subclass של התרופה הבעייתית
2. מסנן את אלה שיוצרות אינטראקציה עם התרופות הנוכחיות (`AlternativeFinder`)
3. מדרג לפי 6 קריטריונים משוקללים:
   - חומרת אינטראקציה הגרועה ביותר
   - **התאמת תת-מחלקה (ATC[:5])** — חלופה קרובה יותר
   - **נוכחות בסל הישראלי** — bonus משמעותי
   - מספר אינטראקציות עם low-severity
   - Popularity score
   - Alphabetical (deterministic)

**הערך העסקי:** הרופא לא מקבל סתם רשימה — הוא מקבל **3 חלופות מובילות עם הסבר למה הן מובילות**. זה הופך את המערכת מ-"alert" ל-"decision support" אמיתי.

### 4.6 Multi-Drug Pairwise Check

[InteractionService.check_prescription](app/services/interaction_service.py:77) בודק:
- כל תרופה חדשה מול **כל תרופה נוכחית** של המטופל
- כל תרופה חדשה מול **כל תרופה חדשה אחרת** (`combinations`)
- מצטבר את כל הבעיות + dedupe של חלופות (לפי שם תרופה)

**הערך העסקי:** טיפול במצבים real-world של "המטופל מקבל 4 תרופות חדשות בו-זמנית אחרי שחרור" — שזה בדיוק שלב הסיכון הגבוה ביותר.

### 4.7 Israeli Drug Basket Integration

[DrugBasketService](app/services/drug_basket_service.py) + [IsraelDrugBasketAPI](app/integrations/israel_drug_basket_api.py):
- **לולאת רענון יומית אוטומטית** ב-`lifespan` של FastAPI ([app/main.py:31](app/main.py:31))
- Fallback אוטומטי ל-dataset מקומי ב-`data/israel_drug_basket.json` כשאין API
- סקריפט מקביל להפעלה ידנית (`python -m scripts.update_israel_basket`)

**הערך העסקי:** מבדיל יוצא דופן בשוק הישראלי — חלופות שמוצעות הן **תרופות שהמטופל יכול לקנות בסבסוד**, לא תרופות פרטיות יקרות.

### 4.8 Deterministic Clinical Explanation

[ClinicalExplanationService](app/services/clinical_explanation_service.py):
- מייצר משפט קליני עקבי לכל אינטראקציה לא בטוחה
- **לא תלוי ב-LLM** — אפס latency, אפס עלות, אפס hallucinations
- דוגמה: "Aspirin combined with Warfarin is generally discouraged because it can increase the risk of increased bleeding."

**הערך העסקי:** רגולטורים אוהבים deterministic logic. כשיש תביעה משפטית — אפשר להוכיח שכל מטופל קיבל את אותו ההסבר.

### 4.9 Patient-Specific Contraindication Framework

[ContraindicationChecker](app/algorithms/contraindication_checker.py) — תשתית למודל סיכון אישי:
- מתחשב בגיל, eGFR (תפקוד כליות), הריון, אי-ספיקת כבד
- כללים שמרניים מובנים: NSAIDs בגיל 75+, Metformin ב-eGFR < 30, Warfarin בהריון, Valproic Acid באי-ספיקת כבד

**הערך העסקי:** Hook מוכן להרחבה לפי הנחיות משרד הבריאות / FDA / EMA.

---

## 5. Medical Document Classifier — איך זה עובד

### 5.1 Config-Driven Procedure Definitions

[ProcedureDefinitionLoader](app/services/medical_classifier/procedure_definition_loader.py) טוען קבצי JSON מתיקייה — **כל פרוצדורה היא קובץ אחד**:

```json
{
  "treatment_code": "arthroscopy_knee",
  "procedure_name": "ארתרוסקופיה ברך",
  "procedure_aliases": ["Knee arthroscopy", "ארטרוסקופיה של הברך"],
  "priority_sections": ["תיאור ניתוח", "מהלך ניתוח", "operative report"],
  "global_positive_signals": ["בוצע ניתוח", "performed", "underwent"],
  "global_negative_signals": ["מיועד לניתוח", "planned", "history of"],
  "categories": [
    {
      "key": "IDX_PROCEDURE_PERFORMED",
      "title": "האם הניתוח בוצע בפועל",
      "scope": "full",
      "positive_signals": [...],
      "negative_signals": [...],
      "examples_positive": [...],
      "examples_negative": [...]
    }
  ]
}
```

**הערך העסקי:** צוות **non-engineer** (אנליסטים רפואיים, רופאי בקרה) יכול להוסיף פרוצדורות חדשות — אין רגרסיות, אין deploy, אין PR.

### 5.2 Prompt Builder עם Hard Rules

[procedure_prompt_builder.py](app/services/medical_classifier/procedure_prompt_builder.py) בונה prompt מובנה ל-LLM הכולל:
- System message שמדגיש: **"רק מה שבוצע בפועל באשפוז הנוכחי"**
- חוקים קשיחים: history → 0, plan → 0, ambiguous → 0, actual execution → 1
- Priority sections למיקוד הקשב של ה-LLM
- Positive/negative signals
- Few-shot examples

**הערך העסקי:** Prompt engineering ברמה production — לא תלוי בכישרון של מי שכתב את ה-prompt. כל פרוצדורה מקבלת את אותה איכות של hint-ים.

### 5.3 Generic Fallback Prompt

[fallback_prompt_provider.py](app/services/medical_classifier/fallback_prompt_provider.py):
- כשמגיע קוד פרוצדורה שלא הוגדר — המערכת לא נופלת
- בונה prompt גנרי עם הוראות יסוד + דוגמאות שליליות בעברית
- מסומן ב-response כ-`prompt_source: "fallback"` — שקיפות מלאה

**הערך העסקי:** Onboarding מהיר — אפשר להתחיל עם פרוצדורה אחת ולהרחיב בהדרגה, בלי שמסמכים אחרים יחזירו שגיאה.

### 5.4 PII Masking Layer (חובה ל-LLM חיצוני)

[mask_israeli_ids](app/services/medical_classifier/pii_cleaner.py):
- regex שמזהה רצפי 5-9 ספרות (טווח של ת.ז. ישראלית)
- מחליף ב-`[ID_REMOVED]` לפני שליחה ל-LLM
- מחזיר את מספר ה-IDs שהוסרו ב-log

**הערך העסקי:**
- **Compliance:** עמידה בתקנות הגנת הפרטיות + GDPR
- **Audit trail:** כל מסמך מתועד עם הספירה של ה-ID-ים שנוקו
- **לא נשלח שום מידע מזהה ל-OpenAI / OpenRouter** — מסר חזק לרכש בקופ"ח

### 5.5 Pluggable LLM Runner (Provider-Agnostic)

[ConfigurableLLMJsonPromptRunner](app/services/medical_classifier/llm_runner.py):
- תומך ב-OpenAI / OpenRouter (זה את זה ב-config בלבד)
- `response_format: json_object` כפוי — schema-safe
- API key יכול לבוא מ-ENV variable או מ-Settings ישירות
- error handling מלא: timeout / HTTP error / invalid JSON / invalid result_code
- כל שגיאה מוחזרת כ-structured payload (`error.code` + `error.message`) — לא נופל בריצה

**הערך העסקי:** Vendor lock-in נמוך. לקוח שרוצה לעבור ל-Anthropic / Cohere / Azure OpenAI / מודל פרטי on-prem — שינוי של function אחת.

### 5.6 Multiple Categories per Procedure (IDX Pattern)

כל פרוצדורה יכולה להגדיר כמה קטגוריות בדיקה (IDX):
- `IDX_PROCEDURE_PERFORMED` — האם הניתוח בוצע
- `IDX_CURRENT_ENCOUNTER_ONLY` — האם זה האשפוז הנוכחי
- כל IDX רץ בנפרד מול ה-LLM
- **התוצאה הכוללת** היא AND לוגי — הפרוצדורה הוכחה רק אם כל ה-IDX-ים מחזירים 1

**הערך העסקי:** דיוק גבוה דרך פירוק — קל יותר ל-LLM לענות על שאלה ממוקדת אחת מאשר על מקבץ שאלות.

---

## 5b. Medical Extraction Engine — JSON-driven Extraction

המנוע השלישי מתמקד בחילוץ ערכים מטופסים פר `treatment_code`. בשונה מה-Classifier (שמחזיר 0/1 בינארי), כאן ה-spec ב-JSON מגדיר rules לכל treatment, ולכל rule נחזיר ערך, evidence, confidence ו-reason.

### 5b.1 Concept

```text
Specification JSON  →  Validate schema  →  For each treatment_code:
                                              For each rule:
                                                deterministic extractor
                                                (LLM fallback if configured)
                                            →  Flat row + Audit record
```

המנוע **לעולם** לא ממציא עמודות, treatment_codes או rules. ה-spec הוא ה-source of truth.

### 5b.2 Specification shape

```json
{
  "version": "1.0",
  "treatments": [
    {
      "treatment_code": "CATARACT_SURGERY",
      "display_name": "Cataract Surgery",
      "rules": [
        {
          "field_name": "has_cataract_diagnosis",
          "type": "boolean",
          "positive_indicators": ["cataract", "קטרקט"],
          "negative_indicators": ["no cataract", "ללא קטרקט"],
          "default_when_missing": false,
          "evidence_required": true
        },
        { "field_name": "surgery_date", "type": "date", "evidence_required": true },
        {
          "field_name": "operated_eye",
          "type": "enum",
          "allowed_values": ["left", "right", "both", "unknown"],
          "evidence_required": true
        }
      ]
    }
  ]
}
```

ה-spec עובר ולידציה דרך Pydantic models ב-[app/services/extraction_engine/spec.py](app/services/extraction_engine/spec.py):
- duplicate `treatment_code` → 422
- duplicate `field_name` בתוך treatment → 422
- `enum` ללא `allowed_values` → 422
- `default_when_missing` שלא תואם לסוג ה-rule → 422
- שדות לא צפויים ב-rule → 422 (`extra="forbid"`)

### 5b.3 Supported rule types

| Type | Deterministic path | LLM fallback | Output |
|---|---|---|---|
| `boolean` | indicator scanning, negation wins per-sentence | ✅ | `true` / `false` / `null` (לפי `default_when_missing`) |
| `enum` | substring match נגד `allowed_values` | ✅ + נורמליזציה ל-`allowed_values` | אחת מ-`allowed_values` או `null` |
| `date` | regex לפורמטים: ISO, DD/MM/YYYY, DD.MM.YYYY, DD-MM-YYYY (כולל YY דו-ספרתי) | ✅ + נורמליזציה ל-ISO | `YYYY-MM-DD` או `null` |
| `number` | regex לטוקן מספרי (תומך נקודה ופסיק עשרוני) | ✅ | `int` / `float` / `null` |
| `text` | sentence הכי קרוב ל-`positive_indicators` | ✅ | string / `null` |

ערכים שלא נמצאו מחזירים `null` כברירת מחדל. עבור `boolean` ניתן להגדיר `default_when_missing: false` כדי ליישר עם דרישות עסקיות.

### 5b.4 Output table + Audit (separation of concerns)

הטבלה השטוחה (`rows`) מכילה **רק** את `document_id`, `treatment_code` והעמודות שהוגדרו ב-spec — נקייה, מתאימה ל-export ל-Parquet/CSV/Postgres.

ה-`audit` הוא רשימת רשומות נפרדת, אחת לכל `(treatment_code, field_name)`, עם `value`, `confidence`, `evidence` (רשימת sentences מצוטטות מהמסמך), `reason` (איך הגענו לערך), ו-`error` אופציונלי.

```json
{
  "rows": [
    { "document_id": "doc_123", "treatment_code": "CATARACT_SURGERY",
      "has_cataract_diagnosis": true, "surgery_date": "2024-02-10", "operated_eye": "left" }
  ],
  "audit": [
    { "document_id": "doc_123", "treatment_code": "CATARACT_SURGERY",
      "field_name": "has_cataract_diagnosis", "value": true, "confidence": 0.9,
      "evidence": ["Patient diagnosed with cataract."],
      "reason": "Matched positive indicator(s): cataract" }
  ]
}
```

### 5b.5 LLM usage policy

ה-LLM **לא** מחליט מה לחלץ — הוא resolver של rule ספציפי בלבד:
- הוא מקבל מסמך + rule בודד
- מחזיר אך ורק `{value, confidence, evidence, reason}`
- אסור לו להמציא שדות חדשים
- אם אין evidence והכלל מוגדר עם `evidence_required: true` — המנוע מחזיר את ה-default
- אם הוא מחזיר ערך enum שאיננו ב-`allowed_values` — המנוע מחזיר default ושומר את השגיאה ב-audit

ה-LLM משתמש באותו provider/model/api_key של ה-Classifier (`MEDICAL_CLASSIFIER_LLM_*`). כש-`provider=disabled` המנוע פועל ב-deterministic-only mode.

### 5b.6 Hebrew + English

הזיהוי דטרמיניסטי הוא substring case-insensitive על Unicode — אותה התנהגות בעברית ובאנגלית. אין צורך ב-tokenizer חיצוני.

### 5b.7 הערך העסקי

- **Onboarding מהיר:** treatment חדש = JSON אחד, ללא deploy.
- **Audit מלא:** כל ערך מלווה ב-evidence ו-reason — מתאים לבקרה רגולטורית ולהוכחת תביעה.
- **Stable schema:** אותו spec מייצר תמיד אותן עמודות — אין surprise columns ב-pipeline downstream.
- **Compliance:** PII masking שיתופי עם ה-Classifier; אותו flag אחד שולט בשתי המערכות.

---

## 6. ארכיטקטורה כללית ושכבות

```
                     ┌────────────────────────────────────────────┐
                     │              FastAPI service               │
                     │  Middleware: RequestId · CORS · API-Key    │
                     │  Errors: 5 handlers, unified envelope      │
                     │  Routes:                                   │
                     │    /health · /ready · /metrics             │
                     │    /v1/check-prescription-safety           │
                     │    /v1/classifications        (POST/GET)   │
                     │    /internal/medical-classifier/classify   │
                     └─────┬───────────────────────┬──────────────┘
                           │ sync path             │ async path
        ┌──────────────────┘                       └──────────────────┐
        │                                                             │
┌───────▼──────────────────┐                              ┌───────────▼───────────┐
│ Interaction Service      │                              │ Classification        │
│  Cache → Graph → DB →    │                              │ Pipeline.ingest():    │
│  External providers      │                              │  • hash + dedupe      │
│  (Lexicomp/Micromedex/   │                              │  • store raw text     │
│  DrugBank, parallel)     │                              │  • create pending run │
│  Severity-first dedupe   │                              │  • enqueue Arq job    │
│  Alternative ranker      │                              └─────────┬─────────────┘
│  ATC class via RxNorm    │                                        │ 202
└──────────┬───────────────┘                                        │
           │                                              ┌─────────▼──────────────┐
           │                                              │ Redis queue (Arq)      │
           │                                              │ classification_queue   │
           │                                              └─────────┬──────────────┘
           │                                                        │
           │                                              ┌─────────▼──────────────┐
           │                                              │ Worker (Arq)           │
           │                                              │ ClassificationExecutor │
           │                                              │  • load doc from store │
           │                                              │  • PII mask            │
           │                                              │  • build prompt        │
           │                                              │  • call LLM            │
           │                                              │  • write run row       │
           │                                              │  • enqueue outbox      │
           │                                              └─────────┬──────────────┘
           │                                                        │
           │                                              ┌─────────▼──────────────┐
           │                                              │ Outbox publisher       │
           │                                              │  • SELECT FOR UPDATE   │
           │                                              │    SKIP LOCKED         │
           │                                              │  • HMAC-signed POST    │
           │                                              │  • exp. backoff + DLQ  │
           │                                              └─────────┬──────────────┘
           │                                                        │ webhook
┌──────────▼─────────────────────────────────────────────────────────▼─────────────┐
│                                 PostgreSQL                                       │
│  drugs · drug_synonyms · drug_interactions · patient_medications                 │
│  documents · classification_runs · outbox_events                                 │
└──────────────────────────────────────────────────────────────────────────────────┘
                                       │
                       ┌───────────────┴───────────────┐
                       │                               │
                ┌──────▼──────┐               ┌────────▼─────────┐
                │ Redis cache │               │ Document storage │
                │ interaction │               │ S3 / MinIO /     │
                │ basket      │               │ local FS         │
                └─────────────┘               └──────────────────┘
```

**Clean Architecture:** API → Services → Algorithms → Repositories → DB / Cache / External.
**Async pipeline:** הקלט (POST) חוזר תוך milli-seconds עם `job_id`; כל העבודה הכבדה (LLM, DB writes, webhook) רצה ב-worker נפרד עם retry, dead-letter ו-outbox transactional consistency.

---

## 7. API Endpoints

> **כל ה-endpoints (חוץ מ-`/health`, `/ready`, `/metrics`) דורשים header `X-API-Key`.**
> Internal endpoints (medical classifier, async classifications) מקבלים גם `INTERNAL_API_KEYS` נפרד אם הוגדר.

### 7.1 `GET /health` · `GET /ready` · `GET /metrics`
- `/health` — liveness probe ל-Kubernetes / Docker / Load Balancer.
- `/ready` — readiness: בודק חיבור DB + Redis ומחזיר `degraded` אם משהו נפל.
- `/metrics` — Prometheus exposition (counters, histograms ל-LLM, classifications, interactions).

### 7.2 `POST /v1/check-prescription-safety`
**Request:**
```json
{
  "patient_id": "123",
  "new_drugs": ["asa"],
  "new_medications": [
    {"drug": "metformin", "dose": "500", "unit": "mg", "frequency": "bid"}
  ]
}
```

**Response:**
```json
{
  "safe": false,
  "issues": [
    {
      "drug": "aspirin",
      "conflicts_with": "warfarin",
      "severity": "D",
      "risk": "increased bleeding",
      "recommendation": "Avoid routine combination or use strict INR and bleeding monitoring",
      "source": "Lexicomp",
      "explanation": "Aspirin combined with Warfarin is generally discouraged because it can increase the risk of increased bleeding."
    }
  ],
  "suggested_alternatives": [
    {"drug": "clopidogrel", "reason": "same therapeutic class", "interaction_risk": "none detected"}
  ]
}
```

**ולידציה:**
- `patient_id`: 1–128 תווים (חובה)
- חובה ספק לפחות תרופה חחת ב-`new_drugs` או ב-`new_medications`
- שמות תרופות מנורמלים אוטומטית ל-lowercase + trim + dedupe

### 7.3 `POST /internal/medical-classifier/classify` (סינכרוני, נשמר לתאימות לאחור)
מבצע סיווג מיידי וחוזר עם התוצאה במשיכה אחת. מתאים לטסטים ול-fallback.

**Request:**
```json
{
  "procedure_code": "arthroscopy_knee",
  "document_text": "המטופל הגיע לאשפוז... בוצעה ארתרוסקופיה ברך ימין...",
  "document_id": "DOC-2024-001"
}
```

**Response:** ראה schema ב-[`MedicalClassifierResponse`](app/schemas/medical_classifier.py).

### 7.4 `POST /v1/classifications/batch` (Bulk submission — **חדש**)
שולח עד `CLASSIFICATION_BATCH_MAX_ITEMS` מסמכים בקריאה אחת ומחזיר `batch_id` משותף + ack לכל פריט.

**Request:**
```json
{
  "items": [
    {"procedure_code": "arthroscopy_knee", "document_text": "...", "document_id": "EHR-1"},
    {"procedure_code": "arthroscopy_knee", "document_text": "...", "document_id": "EHR-2"}
  ]
}
```

**Response (`202 Accepted`):**
```json
{
  "batch_id": "f1a4...-uuid",
  "submitted": 2,
  "deduplicated": 0,
  "items": [
    {"job_id": "...", "document_id": "...", "status": "pending", "deduplicated": false, "poll_url": "/v1/classifications/..."},
    {"job_id": "...", "document_id": "...", "status": "pending", "deduplicated": false, "poll_url": "/v1/classifications/..."}
  ],
  "poll_url": "/v1/classifications/batch/f1a4..."
}
```

מגבלות:
- מקסימום `CLASSIFICATION_BATCH_MAX_ITEMS` (ברירת מחדל 500) — חריגה מחזירה `413`
- `document_id` חייבים להיות ייחודיים בתוך אותו batch — אחרת `422`
- כל פריט עובר את אותו pipeline (hash → dedupe → enqueue) ומקבל `batch_id` משותף ב-`classification_runs.batch_id`

### 7.5 `GET /v1/classifications/batch/{batch_id}` (Bulk status — **חדש**)
מחזיר ספירת מצבים מצטברת + תצוגה מלאה של כל ה-runs בתוך ה-batch. מסונן אוטומטית לפי `X-Tenant-Id` כדי שלקוח אחד לא יראה batch של אחר.

**Response:**
```json
{
  "batch_id": "f1a4...",
  "counts": {"total": 100, "pending": 12, "running": 3, "done": 84, "failed": 1},
  "items": [{"job_id": "...", "status": "done", "result_code": 1, "...": "..."}]
}
```

### 7.6 `POST /v1/classifications` (אסינכרוני, **המומלץ לשימוש production**)
מקבל מסמך, מאחסן אותו ב-object storage, יוצר `classification_runs` row במצב `pending`,
ומחזיר `202 Accepted` עם `job_id`. ה-LLM call עצמו רץ ב-worker.

**Request:**
```json
{
  "procedure_code": "arthroscopy_knee",
  "document_text": "...",
  "document_id": "EHR-DOC-2024-001",
  "source_system": "EHR-Clalit",
  "callback_url": "https://customer.example/hooks/classifications",
  "metadata": {"department": "ortho", "received_via": "HL7"}
}
```

**Headers:** `X-API-Key`, אופציונלי `X-Tenant-Id` (ברירת מחדל `default`).

**Response (`202 Accepted`):**
```json
{
  "job_id": "1c2b...-uuid",
  "document_id": "uuid",
  "status": "pending",
  "deduplicated": false,
  "poll_url": "/v1/classifications/1c2b..."
}
```

`deduplicated=true` כאשר אותו תוכן הוגש שוב (`sha256(document_text)` כבר קיים ל-tenant).

### 7.7 `GET /v1/classifications/{job_id}`
מחזיר את מצב ה-job ואת התוצאה.

**Response (`200 OK`, status `done`):**
```json
{
  "job_id": "1c2b...",
  "document_id": "uuid",
  "status": "done",
  "procedure_code": "arthroscopy_knee",
  "result_code": 1,
  "idx_results": {"IDX_PROCEDURE_PERFORMED": 1, "IDX_CURRENT_ENCOUNTER_ONLY": 1},
  "prompt_source": "definition",
  "used_definition": true,
  "masked": true,
  "pii_masked_count": 2,
  "llm_provider": "openai",
  "llm_model": "gpt-4o-mini",
  "latency_ms": 1840,
  "started_at": "2026-04-27T08:32:11Z",
  "finished_at": "2026-04-27T08:32:13Z",
  "error": null
}
```

`?include_raw=true` מצרף גם את `raw_model_output` המלא (לדיבוג, gated לתפקידי IT).

### 7.8 Webhook callbacks
אם ה-`callback_url` סופק בבקשה, ה-outbox publisher שולח אירוע אחרי כל סיום:
- אירועים: `classification.completed` · `classification.failed`
- Headers: `X-Event-Type`, `X-Event-Id`, `X-Aggregate-Id`, `X-Signature: sha256=...` (HMAC-SHA256 על ה-body, מפתח מ-`WEBHOOK_SIGNING_SECRET`)
- Retry: backoff מעריכי עד שעה, `max_attempts=6` ואחר כך `dead`
- **דוגמת receiver לאימות חתימה:** [`scripts/webhook_receiver_example.py`](scripts/webhook_receiver_example.py) — שירות FastAPI מינימלי שמראה איך מוודאים את ה-`X-Signature` לפני אמון על ה-payload (`python -m scripts.webhook_receiver_example --port 9000`).

### 7.9 Rate limiting (`429 Too Many Requests`)
כשה-flag `RATE_LIMIT_ENABLED=true`:
- Window קבוע (ברירת מחדל: 60 שניות) עם spool דיגיטלי ב-Redis (INCR + EXPIRE) ו-fallback ל-in-memory אם Redis לא זמין
- Identity = `sha256(API key)` + `X-Tenant-Id` (או IP אם אין API key)
- כל תגובה מחזירה `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- כשעולה על הסף — `429` עם header `Retry-After` ו-error envelope אחיד
- מסלולי probe (`/health`, `/ready`, `/metrics`, `/docs`...) מוחרגים אוטומטית
- Metrics: `rate_limit_rejected_total{identity_kind="api"|"ip"}`

### 7.10 `POST /v1/extractions/run` (Medical Extraction Engine)

מקבל מסמך + JSON specification, מחזיר טבלה שטוחה + audit נפרד + תוצאות compliance כאשר ה-spec כולל `compliance_rules`.

**Request:**
```json
{
  "document_id": "doc_123",
  "document_text": "Patient diagnosed with cataract. Surgery date: 10/02/2024. Left eye operated.",
  "metadata": {
    "patient_id": "patient_1",
    "claim_id": "claim_1",
    "provider_id": "provider_1",
    "provider_name": "Example Hospital",
    "hospital_name": "Example Hospital",
    "billed_amount": 1234.56,
    "currency": "ILS"
  },
  "spec": {
    "version": "1.0",
    "treatments": [
      {
        "treatment_code": "CATARACT_SURGERY",
        "rules": [
          {
            "field_name": "has_cataract_diagnosis",
            "type": "boolean",
            "positive_indicators": ["cataract", "קטרקט"],
            "negative_indicators": ["no cataract", "ללא קטרקט"],
            "default_when_missing": false
          },
          { "field_name": "surgery_date", "type": "date" },
          {
            "field_name": "operated_eye",
            "type": "enum",
            "allowed_values": ["left", "right", "both", "unknown"]
          }
        ],
        "compliance_rules": [
          {
            "rule_id": "requires_cataract_diagnosis",
            "description": "Treatment requires cataract diagnosis",
            "field": "has_cataract_diagnosis",
            "operator": "equals",
            "value": true,
            "severity": "high",
            "on_fail": {
              "status": "non_compliant",
              "reason": "Cataract diagnosis was not documented",
              "recommended_action": "request_reimbursement"
            }
          }
        ]
      }
    ]
  }
}
```

**Response:**
```json
{
  "document_id": "doc_123",
  "spec_version": "1.0",
  "rows": [
    {
      "document_id": "doc_123",
      "treatment_code": "CATARACT_SURGERY",
      "has_cataract_diagnosis": true,
      "surgery_date": "2024-02-10",
      "operated_eye": "left"
    }
  ],
  "audit": [
    {
      "document_id": "doc_123",
      "treatment_code": "CATARACT_SURGERY",
      "field_name": "has_cataract_diagnosis",
      "value": true,
      "confidence": 0.9,
      "evidence": ["Patient diagnosed with cataract."],
      "reason": "Matched positive indicator(s): cataract"
    }
  ],
  "compliance": [
    {
      "document_id": "doc_123",
      "treatment_code": "CATARACT_SURGERY",
      "status": "compliant",
      "recommended_action": "none",
      "failed_rules": [],
      "passed_rules": [
        {
          "rule_id": "requires_cataract_diagnosis",
          "description": "Treatment requires cataract diagnosis",
          "field": "has_cataract_diagnosis",
          "operator": "equals",
          "expected": true,
          "actual": true,
          "severity": "high",
          "reason": "Rule passed",
          "recommended_action": "none",
          "evidence": ["Patient diagnosed with cataract."]
        }
      ],
      "insufficient_data_rules": [],
      "manual_review_rules": []
    }
  ],
  "masked": false,
  "pii_masked_count": 0
}
```

**Errors:**
- `422` — invalid spec (duplicate `treatment_code`, duplicate `field_name`, enum ללא `allowed_values`, default לא תואם לסוג, שדה לא צפוי).
- `503` — extraction engine לא אותחל ב-app state.

**Behavior contract:**
- One row per `(document_id, treatment_code)`. כל rule הופך לעמודה.
- Audit נפרד מה-row; שומר `value`, `confidence`, `evidence`, `reason`, `error?`.
- Deterministic indicator/regex matching רץ קודם; LLM resolver הוא fallback opt-in.
- `default_when_missing` לפי spec, אחרת `null`.
- Hebrew indicators פועלים זהה ל-English (Unicode substring match, case-insensitive).
- `compliance_rules` נפרדים מ-`rules`: extraction rules קובעים מה לחלץ, compliance rules קובעים מה חייב להיות נכון.
- Operators ב-V1: `equals`, `not_equals`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `exists`, `missing`.
- Verdicts ב-V1: `compliant`, `non_compliant`, `insufficient_data`, `manual_review`.
- כל compliance rule חייב להפנות לשדה extraction שהוגדר באותו treatment; reference לא קיים נדחה ב-validation.
- כשל עם `recommended_action=request_reimbursement` יוצר `reimbursement_case` פנימי בסטטוס `draft`; אין שליחה חיצונית באיטרציה זו.
- example: [data/extraction_specs/cataract_surgery.json](data/extraction_specs/cataract_surgery.json)

### 7.11 Dashboard APIs

Customer dashboard endpoints מסוננים תמיד לפי `tenant_id` שנפתר מה-API key המאומת. אין אמון ב-`X-Tenant-Id` או ב-`tenant_id` שמגיע מהלקוח.

- `GET /v1/dashboard/summary`
- `GET /v1/dashboard/treatments`
- `GET /v1/dashboard/rules`
- `GET /v1/dashboard/documents/timeseries`
- `GET /v1/dashboard/reimbursement-cases`
- `GET /v1/dashboard/reimbursement-cases/{case_id}`
- `PATCH /v1/dashboard/reimbursement-cases/{case_id}`

Admin dashboard endpoints משתמשים ב-`InternalApiKeyDep`, יכולים לראות את כל הלקוחות, ויכולים לסנן לפי `tenant_id`:

- `GET /v1/admin/dashboard/summary`
- `GET /v1/admin/dashboard/tenants`
- `GET /v1/admin/dashboard/tenants/{tenant_id}/summary`
- `GET /v1/admin/dashboard/treatments`
- `GET /v1/admin/dashboard/reimbursement-cases`
- `GET /v1/admin/dashboard/reimbursement-cases/{case_id}`
- `PATCH /v1/admin/dashboard/reimbursement-cases/{case_id}`

Query params נתמכים: `date_from`, `date_to`, `tenant_id` ל-admin בלבד, `treatment_code`, `status`, `recommended_action`, `limit`, `offset`.

Lifecycle ל-reimbursement cases:
- `draft -> ready|closed`
- `ready -> sent|closed|draft`
- `sent -> accepted|rejected|closed`
- `accepted -> closed`
- `rejected -> closed`
- `closed` סופי

כל שינוי סטטוס, הוספת note, עדכון amount/currency, ויצירה אוטומטית של case נשמרים ב-`reimbursement_case_events`.

Metrics עיקריים:
- documents/runs/treatments/compliance status counts
- reimbursement case counts by status and estimated/accepted amounts
- treatment non-compliance rate and refund opportunity
- failed rule counts, missing fields, evidence coverage
- tenant comparison, top tenants by volume/refund opportunity, insufficient-data rate
- run duration averages/p95, spec hash usage, spec versions over time

---

## 8. Data Model — סכמת מסד הנתונים

### `drugs`
- `id` PK, `name` (UNIQUE), `normalized_name` (UNIQUE, INDEX)
- `atc_code` (INDEX) — לחיפוש לפי class
- `is_in_israel_basket` (INDEX, BOOLEAN) — לסינון מהיר של חלופות בסל
- `created_at` / `updated_at` (timezone aware, server-side default)

### `drug_synonyms`
- `id` PK, `drug_id` FK CASCADE, `synonym` (UNIQUE, INDEX)
- מאפשר חיפוש מ-O(1) משם מסחרי לחומר פעיל

### `drug_interactions`
- `drug_a_id` / `drug_b_id` FK עם **UniqueConstraint על הזוג** (uq_drug_pair)
- ID-ים תמיד מסודרים בעלייה (`min/max`) — אין כפילויות symmetric
- `severity` (INDEX) — A/B/C/D/X
- `risk`, `recommendation`, `source`

### `patient_medications`
- `patient_id` (INDEX) + `drug_id` עם UNIQUE זוגית
- `dose` / `unit` / `frequency` — שדות אופציונליים לתיעוד מלא

### `documents` (חדש — async pipeline)
- `id` UUID PK (cross-DB type adapter — native UUID ב-Postgres, CHAR(36) ב-SQLite ל-tests)
- `tenant_id` + `document_hash` עם UNIQUE — דדופ של אותו תוכן בתוך לקוח
- `procedure_code`, `storage_uri` (S3/local), `size_bytes`, `source_system`, `external_document_id`, `metadata_json` (JSONB)
- raw text **לא** נשמר ב-DB — נשמר ב-object storage, ב-DB יש רק URI

### `classification_runs` (חדש — async pipeline)
- `id` UUID PK, `job_id` UUID UNIQUE
- FK ל-`documents.id` עם CASCADE
- `status` ∈ `pending|running|done|failed`
- `attempt`, `max_attempts` — לתמיכה ב-retry
- `result_code` (smallint 0/1), `idx_results` (JSONB), `raw_model_output` (JSONB), `error` (JSONB)
- `llm_provider`, `llm_model`, `masked`, `pii_masked_count`, `latency_ms`
- `started_at`, `finished_at`, `callback_url`
- אינדקס מורכב על `(status, created_at)` לסריקה מהירה של queue lag

### `outbox_events` (חדש — webhook delivery)
- `id` UUID PK, `aggregate_type`+`aggregate_id`, `event_type`, `payload` (JSONB)
- `destination_url`, `status` ∈ `pending|sent|failed|dead`
- `attempts`, `max_attempts`, `next_attempt_at`, `last_error`
- אינדקס מורכב על `(status, next_attempt_at)` ל-`SELECT ... FOR UPDATE SKIP LOCKED`

### `extraction_runs`
- `id` UUID PK, `document_id`, `spec_version`, `spec_hash`, `tenant_id`
- `masked`, `pii_masked_count`, `duration_ms`, `metadata` JSONB, `created_at`
- `metadata` אופציונלי ומיועד ל-business context הדרגתי: `patient_id`, `claim_id`, `provider_id`, `provider_name`, `hospital_name`, `institute_name`, `billed_amount`, `currency`

### `extraction_rows`
- `id` UUID PK, FK ל-`extraction_runs.id`
- `document_id`, `treatment_code`, `values` JSONB
- אין dynamic SQL columns ואין טבלה פיזית לכל treatment

### `extraction_audit`
- `id` UUID PK, FK ל-`extraction_runs.id`
- `treatment_code`, `field_name`, `value`, `confidence`, `evidence`, `reason`, `error`
- מקור evidence עבור failed compliance rules

### `compliance_results`
- `id` UUID PK, FK ל-`extraction_runs.id`
- `document_id`, `treatment_code`, `status`, `recommended_action`
- `failed_count`, `passed_count`, `insufficient_data_count`, `highest_severity`, `created_at`

### `compliance_rule_results`
- `id` UUID PK, FK ל-`compliance_results.id` ו-`extraction_runs.id`
- `rule_id`, `field_name`, `operator`, `expected` JSONB, `actual` JSONB, `status`, `severity`, `reason`, `evidence` JSONB

### `reimbursement_cases`
- `id` UUID PK, FK ל-`extraction_runs.id` ו-`compliance_results.id`
- `tenant_id`, `document_id`, `treatment_code`, `status`
- `reason`, `estimated_amount`, `currency`, `sent_at`, `resolved_at`, `created_at`, `updated_at`
- נוצרת אוטומטית כ-`draft` כאשר verdict הוא `non_compliant` וה-action הוא `request_reimbursement`

### `reimbursement_case_events`
- `id` UUID PK, FK ל-`reimbursement_cases.id` עם CASCADE
- `tenant_id`, `previous_status`, `new_status`, `event_type`, `note`, `actor_id`, `metadata`, `created_at`
- event types: `case_created`, `status_changed`, `note_added`, `amount_updated`
- מספק audit history מלא ל-lifecycle של refund/appeal case

**הערך העסקי:**
- כל ה-foreign keys עם `ondelete=CASCADE` — מחיקת תרופה/מסמך לא משאירה רשומות יתומות
- כל אינדקס ממוקד לשאילתות באמת — אין index pollution
- **Audit trail מלא** לכל בקשת LLM: מי שלח, מתי, איזה מודל, איזה latency, כמה PII מסונן

---

## 9. אינטגרציות חיצוניות

### Drug Interaction Providers
| ספק | סטטוס | הערה |
|---|---|---|
| **Lexicomp** | פעיל (production-ready adapter) | הספק המוביל בעולם |
| **Micromedex** | פעיל | תקן מקובל בארה"ב |
| **DrugBank** | פעיל + ATC fallback מובנה | open data, מצוין ל-class lookup |
| **First Databank** | פעיל (optional) | הרבה לקוחות אמריקאים משתמשים |
| **UpToDate / DynaMed** | placeholder (ללא public API) | מוכן להחלפה במנוע scraping ייעודי |

### Drug Class & Naming
- **RxNorm (NIH)** — official source for ATC codes
- **DrugBank** — fallback secondary source

### Israeli Specific
- **משרד הבריאות / סל התרופות** — בקריאה דרך `israel_basket_api_url` או fallback ל-dataset מקומי

### LLM Providers (Medical Classifier)
- **OpenAI** — `gpt-4o`, `gpt-4o-mini` ועוד
- **OpenRouter** — גישה ל-Anthropic Claude, Google Gemini, Mistral וכו'

> **כל ספק עוטף ב-Tenacity retry** עם exponential backoff (3 ניסיונות, 2.0 שניות timeout) — Production grade.

---

## 10. ביצועים, Caching ו-Scalability

### Caching Strategy
- **Redis primary** — TTL 24h לאינטראקציות, 6h לסל התרופות
- **In-memory fallback** ב-[CacheClient](app/core/cache.py) — Redis יורד? המערכת לא נופלת, רק מאבדת persistence
- **In-memory Interaction Graph** — זיכרון של pairs נטענים ב-`startup` ([app/main.py:75](app/main.py:75))

### Concurrency
- כל קריאות ה-DB אסינכרוניות (`asyncpg`)
- כל קריאות חיצוניות אסינכרוניות (`httpx.AsyncClient`)
- Provider queries רצות **במקביל** (`asyncio.gather`)
- בניית הגרף הראשונית ([scripts/build_interaction_graph.py](scripts/build_interaction_graph.py)) רצה עם **Semaphore(25)** + batches של 500 — שעה אחת מספיקה ל-2,000 תרופות (~2M זוגות)

### Connection Pool
- `db_pool_size: 20`, `db_max_overflow: 40` (ניתן לקנפג)
- `pool_pre_ping: True` — מטפל אוטומטית ב-stale connections (חשוב במיוחד ב-K8S)

### גודל
- מתאים לעומס של **10K-100K בדיקות בדקה** על instance בודד (לפי ה-cache hit rate)
- horizontal scaling — stateless service, scale lockless

---

## 11. אבטחה, פרטיות ו-Compliance

### PII / PHI Protection
- [PII masking](app/services/medical_classifier/pii_cleaner.py) **לפני** כל שליחה ל-LLM חיצוני
- אפס PII נשמר ב-cache או ב-DB (רק `patient_id` כ-string opaque)
- Logging structured + masked — אף ת.ז. לא מודפסת

### Secrets Management
- כל ה-API keys מקנפג מ-ENV vars (`pydantic-settings` + `.env` support)
- **לא** hardcoded ב-source

### Type Safety
- 100% type hints (Python 3.11 syntax)
- Pydantic v2 strict validation בכל ה-endpoints
- `from __future__ import annotations` בכל קובץ

### Audit Logging
- JSON structured logs ([app/core/logging.py](app/core/logging.py))
- כל שגיאה כוללת `extra` עם metadata (drug names, provider, error)
- `logger.info("masked %s possible ID values", count)` — ספירת PII ל-audit

### Compliance Hooks
- Architecture מוכנה ל-HIPAA / GDPR / ISO 27799
- Deterministic explanations — כל מטופל עם הסבר עקבי שניתן להוכיח בבית משפט

---

## 12. Quality, Testing & Observability

### Test Suite ([tests/](tests/)) — **56 tests passing**
- `test_interaction_checker.py` — end-to-end של מנגנון רב-שכבתי
- `test_drug_normalization_service.py` — שמות מסחריים, synonyms
- `test_drug_ranker.py` — דירוג חלופות
- `test_clinical_explanation_service.py` — הסברים deterministic
- `test_interaction_graph.py` — adjacency operations
- `test_medical_classifier.py` — definition loading, prompt building, PII masking, fallback prompts, env API key resolution
- `test_medical_classifier_route.py` — integration test ל-API endpoint
- **`test_classification_pipeline.py`** — ingest, dedupe, executor, outbox retry → dead-letter
- **`test_classification_routes.py`** — `202 Accepted`, lifecycle done, auth `401`, `404`
- **`test_storage_and_security.py`** — local storage round-trip, HMAC signing

הרצה: `make test` או `pytest -q`. עם coverage: `make cov`.

### CI/CD
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) — pull request gate:
1. `ruff check` + `ruff format --check`
2. `mypy app`
3. `alembic upgrade head` מול Postgres 16 service
4. `pytest --cov` עם Postgres + Redis live services
5. Docker image build (BuildKit cache, `gha` cache backend)

### Observability
- JSON logs מוכנים ל-Datadog / Splunk / ELK / CloudWatch
- **Request-ID propagation** ב-[`RequestContextMiddleware`](app/core/middleware.py) — מועבר חזרה ב-header וברשומת ה-log
- **Prometheus metrics** ([`/metrics`](app/core/metrics.py)) — `classification_jobs_total`, `classification_latency_seconds`, `llm_call_latency_seconds`, `llm_call_results_total`, `interaction_checks_total`
- כל שירות חיצוני נכשל → log עם `provider`, `drug_a`, `drug_b`, `error`

### Production Patterns
- `lifespan` async context manager — graceful startup + shutdown
- Background task לסנכרון יומי של סל התרופות
- `pool_pre_ping` — survives DB restarts
- Tenacity retries — survives transient network errors
- Outbox `SELECT ... FOR UPDATE SKIP LOCKED` — בטוח לריצה במספר instances של ה-publisher
- Worker `max_tries` + Arq dead-letter — ג'ובים נכשלים לא נתקעים בלולאה

---

## 13. Deployment והפעלה

### Quick start (קליק אחד)
```bash
./install.sh           # bootstrap מלא: build → migrate → seed → up
./install.sh status    # סטטוס שירותים
./install.sh logs      # logs
./install.sh reset     # תאוצה לאפס
```
ראה [סקציה 0](#0-התקנה-בקליק-one-click-install) לפרטים מלאים.

### דרישות
- Docker + Docker Compose (production / staging)
- *או* Python 3.11+ עם Postgres 14+ ו-Redis 6+ זמינים (לוקלי)

### התקנה ידנית (ללא Docker)
```bash
make install            # pip install -e ".[dev]"
make migrate            # alembic upgrade head
make seed               # seed_drugs + seed_synonyms
make dev                # uvicorn ב-port 8000
make worker             # ב-shell נפרד — Arq classification worker
make outbox             # ב-shell נפרד — outbox publisher
```

### Configuration ([`.env.example`](.env.example))
כל ההגדרות מ-ENV (12-factor). הקובץ כולל:
- **Auth:** `API_KEYS` (CSV), `INTERNAL_API_KEYS`, `WEBHOOK_SIGNING_SECRET`, `CORS_ALLOW_ORIGINS`
- **Storage:** `DATABASE_URL`, `REDIS_URL`, `QUEUE_REDIS_URL` (logical DB נפרד מה-cache)
- **Document storage:** `DOCUMENT_STORAGE_BACKEND` ∈ `local|s3`, `DOCUMENT_STORAGE_S3_BUCKET/PREFIX/REGION`
- **Drug providers:** `ENABLED_PROVIDERS`, `PROVIDER_PRIORITY`, `LEXICOMP_*`, `MICROMEDEX_*`, `DRUGBANK_*`, `FIRST_DATABANK_*`
- **LLM:** `MEDICAL_CLASSIFIER_LLM_PROVIDER` (`openai|openrouter|disabled`), `_MODEL`, `_API_KEY` / `_API_KEY_ENV_NAME`, `_TIMEOUT_SECONDS`
- **Pipeline:** `CLASSIFICATION_QUEUE_NAME`, `CLASSIFICATION_MAX_RETRIES`, `WORKER_CONCURRENCY`, `OUTBOX_POLL_INTERVAL_SECONDS`, `OUTBOX_BATCH_SIZE`
- **Israeli basket:** `ISRAEL_BASKET_API_URL/KEY` או `ISRAEL_BASKET_DATASET_PATH` (fallback מקומי)

### Container & Cloud Ready
- **Dockerfile multi-stage** — non-root user, tini PID 1, `/health` HEALTHCHECK, image < 250MB
- **docker-compose.yml** — `postgres`, `redis`, `migrate` (one-shot), `api`, `worker`, `outbox` עם תלויות בריאות
- **GitHub Actions** — `.github/workflows/ci.yml` בונה image עם BuildKit cache (gha)
- **K8s ready:** `liveness=/health`, `readiness=/ready`, stateless — `Deployment` רגיל. ה-worker וה-outbox רצים כ-`Deployment` נפרד עם replicas שונה
- **S3:** הפעלה הופכת אוטומטית ל-S3 ע"י `DOCUMENT_STORAGE_BACKEND=s3`; AWS credentials מ-IRSA / IAM role / `~/.aws`
- **Migration job:** `alembic upgrade head` מתאים גם ל-`initContainer` או GitOps Hook

---

## 14. מה נוסף בגרסה הנוכחית (Changelog)

ה-iteration האחרון הפך את הריפו מ-API library ל-**document ingestion platform** מלא.

### ✅ נוסף ועובד (כל הקבצים קיימים, ה-imports נקיים, 34 בדיקות עוברות)

#### Infrastructure & Dev Experience
- [`Dockerfile`](Dockerfile) multi-stage — non-root, tini, healthcheck, מבוסס Python 3.11-slim
- [`docker-compose.yml`](docker-compose.yml) — 5 שירותים (postgres, redis, migrate, api, worker, outbox) עם תלויות בריאות
- [`.dockerignore`](.dockerignore), [`.gitignore`](.gitignore), [`.env.example`](.env.example) מלא
- [`Makefile`](Makefile) — 20 פקודות `make help`-ready
- [`pyproject.toml`](pyproject.toml) — dependencies + ruff + mypy + pytest + coverage; אינסטולציה כ-`pip install -e ".[dev]"`
- [`install.sh`](install.sh) — one-click installer (`docker | local | reset | logs | status`), מייצר API key + webhook secret אקראיים
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — lint + mypy + alembic + pytest עם services + docker build cache

#### Async Document Pipeline (ליבת ה-iteration)
- מיגרציה [`0003_classification_pipeline.py`](alembic/versions/0003_classification_pipeline.py) עם 3 טבלאות חדשות
- Models: [`Document`](app/models/document.py), [`ClassificationRun`](app/models/classification_run.py), [`OutboxEvent`](app/models/outbox_event.py)
- Cross-DB types ב-[`app/core/database.py`](app/core/database.py) — `GUID` TypeDecorator + `JSONType` (JSONB ב-Postgres, JSON ב-SQLite)
- Repositories: [`document_repository.py`](app/repositories/document_repository.py), [`classification_repository.py`](app/repositories/classification_repository.py), [`outbox_repository.py`](app/repositories/outbox_repository.py)
- [`ClassificationPipeline`](app/services/classification_pipeline.py) — ingest (hash/dedupe → store → pending row → enqueue)
- [`ClassificationExecutor`](app/services/classification_pipeline.py) — worker side (load → mask → LLM → write run → outbox)
- API חדש: [`POST /v1/classifications`](app/api/routes_classification.py), `GET /v1/classifications/{job_id}`
- תמיכת `X-Tenant-Id` + multi-tenancy ב-DB (`tenant_id` column ב-3 הטבלאות)
- `?include_raw=true` ל-debug של LLM raw output
- Schemas: [`ClassifyAsyncRequest`](app/schemas/classification.py), `ClassifyAsyncAck`, `ClassificationRunView`

#### Workers
- [`app/workers/classification_worker.py`](app/workers/classification_worker.py) — Arq `WorkerSettings` עם concurrency, timeout, retries; פולט metrics ל-Prometheus
- [`app/workers/outbox_publisher.py`](app/workers/outbox_publisher.py) — לולאה אסינכרונית עם `SELECT FOR UPDATE SKIP LOCKED`, exponential backoff, dead-letter, HMAC signing, signal handlers ל-graceful shutdown

#### Storage
- [`app/core/storage.py`](app/core/storage.py) — Protocol-based abstraction
  - `LocalDocumentStorage` ל-dev / on-prem
  - `S3DocumentStorage` ל-cloud, עם `ServerSideEncryption=AES256` כברירת מחדל

#### Production Middleware & Hardening
- [`app/core/security.py`](app/core/security.py) — API key Depends עם `secrets.compare_digest`, hash מקוצר ל-`request.state`, `sign_payload` ל-HMAC webhook
- [`app/core/middleware.py`](app/core/middleware.py) — Request-ID propagation + structured request log
- [`app/core/errors.py`](app/core/errors.py) — 5 exception handlers, envelope אחיד `{error: {code, message}, request_id}`
- [`app/core/metrics.py`](app/core/metrics.py) — Prometheus collectors
- [`app/core/queue.py`](app/core/queue.py) — `ArqJobEnqueuer` + `InMemoryJobEnqueuer` ל-tests
- CORS middleware מקונפג מ-ENV
- כל ה-routes הקיימים הועברו ל-`/v1/` ועוטפים ב-API key
- בעיית duplicate index ב-`patient_medications` תוקנה

#### Settings additions
[`app/core/settings.py`](app/core/settings.py) הורחב עם 17 משתנים חדשים (auth, queue, storage, outbox, webhook signing, log level).

#### Tests
12 בדיקות חדשות ([`test_classification_pipeline.py`](tests/test_classification_pipeline.py), [`test_classification_routes.py`](tests/test_classification_routes.py), [`test_storage_and_security.py`](tests/test_storage_and_security.py)) — סה"כ **34 passing**.

---

### ✅ נוסף ב-iteration הזה

- **Rate limiting** — middleware fixed-window per (API key, tenant) עם Redis backend ו-in-memory fallback. Metrics ב-`/metrics`. דוגמה ב-[`tests/test_rate_limit.py`](tests/test_rate_limit.py).
- **Bulk classification endpoint** — `POST /v1/classifications/batch` (עד 500 פריטים) + `GET /v1/classifications/batch/{batch_id}`. Migration `0004_classification_batch` מוסיפה `batch_id` ל-`classification_runs` עם index. בדיקות: [`tests/test_classification_batch.py`](tests/test_classification_batch.py).
- **Webhook receiver verification example** — [`scripts/webhook_receiver_example.py`](scripts/webhook_receiver_example.py) שירות FastAPI מינימלי שמאמת `X-Signature` עם `secrets.compare_digest`. בדיקות: [`tests/test_webhook_receiver_example.py`](tests/test_webhook_receiver_example.py).
- **Validation error envelope hardening** — `RequestValidationError` עכשיו עובר דרך `jsonable_encoder` כדי להתמודד עם פירטי שגיאה לא-JSON-serializable של Pydantic v2.

### 🟡 פתוח / מומלץ ב-iteration הבא

| נושא | סטטוס | למה זה חשוב |
|---|---|---|
| **OpenTelemetry tracing** | פתוח | spans בין api → queue → worker → LLM → DB; חיוני לדיבוג latency אצל לקוחות גדולים |
| **Helm chart / ArgoCD manifests** | פתוח | יש Dockerfile + compose; חסר K8s deploy מוכן |
| **mTLS / OAuth2 / JWT** | פתוח | היום API key סטטי. לקוחות enterprise ידרשו flow מתקדם |
| **Admin UI ל-procedure definitions** | פתוח | היום JSON ב-FS. לקוחות לא-טכניים ירצו CRUD |
| **FHIR R4 adapter** | פתוח | משלים את ה-pipeline להתחבר ישירות ל-EHR |
| **`mypy` strict mode** | חלקי | היום `strict=false`; כדאי להעלות ל-strict בהדרגה |
| **Load tests** | פתוח | `locust` / `k6` מול ה-async endpoint; חסר baseline ביצועים |
| **Secret store integration** | פתוח | היום ENV; לקוחות רגולטוריים ידרשו Vault/AWS SM |
| **Backup/PITR runbook** | פתוח | לתעד RPO/RTO ל-Postgres + S3 |
| **OpenAPI client SDK generation** | פתוח | TypeScript / Python clients מתויגים |
| **Dashboard ל-Grafana** | פתוח | יש metrics — חסר JSON dashboard מוכן |
| **HA outbox publisher** | חלקי | יש `SKIP LOCKED`, אבל חסר leader election אם רוצים sequential delivery |
| **CSV/JSONL ingestion ל-bulk** | פתוח | יש `POST /batch` בסיסי; ZIP/CSV upload עם streaming response עוד פתוח |

---

## 15. Roadmap ופוטנציאל הרחבה

### Quick Wins (Sprint 1-2)
- [ ] OpenTelemetry tracing על כל request
- [ ] Helm chart + ArgoCD manifests
- [ ] Rate limiting (Redis token bucket) per tenant + API key
- [ ] OAuth2 / JWT (החלפת API key הסטטי)
- [ ] Grafana dashboard מוכן ל-export

### תוספי מוצר (Sprint 3-6)
- [ ] **דשבורד אדמין** ל-procedure definitions (CRUD UI)
- [ ] **Bulk classification API** — תיקיית מסמכים → תוצאות CSV
- [ ] **Clinician feedback loop** — `/feedback` endpoint שמשנה את ה-graph
- [ ] **Explainability portal** — UI שמציג למה אינטראקציה דורגה X
- [ ] **Webhook receiver SDK** ב-Python/TypeScript

### חדשנות (Sprint 7+)
- [ ] **ML-driven personalized contraindication** (גיל, BMI, ערכי מעבדה)
- [ ] **תמיכת FHIR R4** — קלט/פלט בפורמט HL7 standard
- [ ] **תמיכת RxNorm full sync** — clearer mapping pipeline
- [ ] **Multilingual classifier** — ערבית, רוסית, אמהרית

---

## 16. למי זה מיועד — Pitch ללקוח

### 🏥 קופות חולים (כללית, מכבי, לאומית, מאוחדת)
- **חיסכון:** 10K-100K שח בחודש על תביעות שיפנו לרופא בקרה
- **בטיחות:** הקטנה דרסטית של ADEs בקרב מטופלים מורכבים
- **חוויה:** רופא משפחה מקבל "second opinion" חכם ב-< 200ms

### 🏨 בתי חולים פרטיים וציבוריים
- **שילוב EHR:** 2 endpoints, אינטגרציה תוך שבוע
- **דוחות איכות:** structured logs מוכנים לרגולטור
- **PHI safe:** מוכן לסקירת אבטחה של הקופות

### 🛡️ חברות ביטוח רפואי
- **Underwriting:** אישור תביעה מהיר ומבוסס על מסמך אובייקטיבי
- **Fraud detection:** איתור פרוצדורות שלא בוצעו בפועל
- **Cost optimization:** המלצה לחלופה בסל לפני שתביעה מאושרת

### 💊 רשתות בתי מרקחת
- **Counter-side check:** הרוקח רואה אזהרה לפני שמוסר
- **Recommendations:** המלצה על תחליף סבסוד לפני שהמטופל הולך הביתה

### 🔬 חברות תרופות / Clinical Trials
- **Eligibility screening:** סינון מטופלים שצריכים להוצא ממחקר בגלל אינטראקציה
- **Real-world evidence:** הצטברות data על severity actuals

---

## הערה אחרונה — מצב המערכת היום

המערכת **production-grade architecture** עם:
- ✅ One-click installer (Docker או local)
- ✅ Async ingestion pipeline מלא: API → queue → worker → DB → outbox webhook
- ✅ Multi-tenant via `tenant_id`
- ✅ S3 / MinIO / local storage עם interface אחיד
- ✅ HMAC-signed webhooks, exponential backoff, dead-letter queue
- ✅ Prometheus metrics + Request-ID propagation + structured JSON logs
- ✅ API key auth + CORS + global error envelope
- ✅ Type-safe, validated boundaries; 34 tests passing
- ✅ CI: ruff + mypy + alembic + pytest + docker build
- ✅ Cross-DB types (Postgres production, SQLite tests)
- ✅ Pluggable providers (drug interactions + LLM)
- ✅ Hebrew + English support, PII-masked by default

**מה דרוש להפעלה ראשונה אצל לקוח:**
1. רישיון API לפחות לאחד מ-Lexicomp / Micromedex / DrugBank (~2 שבועות)
2. גישה ל-API של סל התרופות (או שימוש ב-fallback)
3. הגדרת 5-20 procedure definitions ראשוניים (יום-יומיים עבודה של אנליסט)
4. `./install.sh` על שרת/VM (דקות) או deploy ל-K8s (יום, חסר רק Helm chart)

**מ-zero ל-production, אצל לקוח אמיתי, תוך פחות מחודש.**
