# Backend

الواجهة الخلفية للمشروع مبنية بـ `FastAPI`، وهي المسؤولة عن:
- استيعاب الأنطولوجيا من ملف `TTL`
- تخزينها في `PostgreSQL/pgvector`
- تحليل الأسئلة العربية
- مطابقة المفاهيم والعلاقات
- توليد الإجابات في وضعي `AI` و`without_ai`
- توفير مسارات التشغيل والإدارة والفحص

---

## المسؤوليات الأساسية

الخدمة الخلفية تنفذ أربع وظائف رئيسية:

1. **Ingestion**
   - قراءة ملف `TTL`
   - استخراج المفاهيم والمرادفات والعلاقات
   - تنفيذ upsert داخل قاعدة البيانات

2. **Retrieval**
   - تحليل intent للسؤال
   - مطابقة المفهوم الأنسب
   - توسيع العلاقات المرتبطة بالسؤال

3. **Answering**
   - توليد جواب محلي في `without_ai`
   - أو تجهيز سياق grounded وتمريره إلى OpenAI في `AI`

4. **Operations**
   - فحص الصحة
   - إحصائيات سريعة
   - audit لقاعدة البيانات
   - إعادة الفهرسة للـ embeddings

---

## البنية الحالية

```text
app/
  main.py        نقاط النهاية ومنطق التشغيل المركزي
  security.py    sanitization + rate limiting

core/
  models.py      جداول قاعدة البيانات

processing/
  ttl_parser.py
  text_normalizer.py
  query_analyzer.py
  concept_matcher.py
  relation_expander.py
  runtime_ontology_cache.py

generation/
  answer_generator.py
  answer_composer.py
  answer_validator.py

services/
  openai_client.py
  embedding_service.py

tests/
  test_integration_api.py
  test_logic_units.py
```

---

## التشغيل المحلي

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

المدخل الرسمي للتشغيل المحلي هو:
- `run.py`

المدخل المخصص لأسلوب serverless/python export هو:
- `api/index.py`

---

## المتطلبات

- Python 3.10+
- PostgreSQL
- امتداد `pgvector`
- Redis اختياري
- `OPENAI_API_KEY` اختياري

---

## المتغيرات البيئية

يعتمد الباك على القيم التالية:

### أساسية
- `DATABASE_URL`
- `CORS_ALLOWED_ORIGINS`

### اختيارية
- `OPENAI_API_KEY`
- `REDIS_URL`
- `CORS_ALLOWED_ORIGIN_REGEX`
- `PORT`
- `ENABLE_AI_REGENERATION`
- `AI_MAX_REGENERATION_ATTEMPTS`

راجع المثال في:
- [`backend/.env.example`](./.env.example)

---

## قاعدة البيانات

## الجداول الفعلية

### `concepts`
تخزن:
- `uri`
- `labels`
- `definition`
- `quote`
- `actions`
- `importance`
- `embedding`

### `concept_synonyms`
تخزن:
- `subject_uri`
- `predicate`
- `object_value`
- `concept_id`
- `embedding`

### `concept_relations`
تخزن:
- `type`
- `source_uri`
- `target_uri`
- `source_concept_id`
- `target_concept_id`
- `embedding`

### `documents`
موجودة سكيميًا، لكنها غير مغذاة من الـ `TTL` الحالي.

## ملاحظات مهمة
- أبعاد الـ embeddings الحالية: `1536`
- بعض foreign keys في العلاقات قد تبقى فارغة بشكل صحيح إذا كان الـ URI غير معرف كمفهوم مستقل في المصدر
- `documents` ليست خطأ تشغيلًا، بل حالة مقصودة في هذا الإصدار من النظام

---

## دورة معالجة السؤال

المسار المركزي موجود في:
- `app/main.py`

والمراحل الحالية هي:

1. `sanitize`
2. `cache lookup`
3. `intent analysis`
4. `concept matching`
5. `relation expansion`
6. `answer composition`
7. `validation`
8. `cache store`

ويتم تسجيل timings لكل مرحلة داخل اللوج.

---

## وضعا الإجابة

## `AI`
هذا المسار:
- يحلل السؤال محليًا
- يسترجع المفهوم والعلاقات محليًا
- يجهز سياقًا structured
- يرسل هذا السياق إلى OpenAI عند توفر المفتاح

### ملاحظات
- regeneration معطل افتراضيًا
- يمكن تفعيله فقط من البيئة
- retrieval المحلي يعمل قبله، لذلك الجواب ليس حرًا بالكامل بل grounded بالسياق

## `without_ai`
هذا المسار:
- لا يرسل أي طلبات إلى OpenAI
- لا يستخدم vector search
- يعتمد فقط على:
  - تحليل النية محليًا
  - المطابقة المحلية
  - العلاقات
  - القوالب

هذا المسار هو البديل التشغيلي الكامل عندما تكون الأولوية:
- للسرعة
- للحتمية
- لعدم استهلاك أي توكنات

---

## الاسترجاع والمطابقة

المطابقة الحالية لا تعتمد على full scans تقليدية لكل طلب، بل على:
- snapshot محلي
- فهارس في الذاكرة
- exact match
- synonym match
- lexical/full-text style matching
- phrase fallback

الملف المسؤول:
- `processing/concept_matcher.py`

أما العلاقات فتُدار من:
- `processing/relation_expander.py`

وهي مبنية حاليًا على graph محلي في الذاكرة.

---

## الـ API الحالية

## `POST /api/chat/query`
مسار الدردشة في وضع `AI`.

### Request body
```json
{
  "question": "ما هو القرآن؟",
  "use_embeddings": false,
  "max_relations": 8,
  "max_depth": 2
}
```

### Response fields
- `answer`
- `confidence`
- `intent`
- `mode`
- `sources`
- `token_usage`
- `processing_time`
- `validation_score`
- `method`
- `matched_concept`
- `top_concepts`
- `top_quotes`
- `quote`
- `relations`
- `relation_details`

## `POST /api/chat/query-without-ai`
نفس shape الاستجابة تقريبًا، لكن:
- `mode = without_ai`
- بلا OpenAI

## `POST /api/ontology/upload`
يرفع ملف `TTL`، يحدّث الجداول، ويحدث snapshot التشغيل.  
يدعم:
- `generate_embeddings=true|false`

## `POST /api/ontology/reindex`
يعيد بناء embeddings للجداول المدعومة.

## `GET /api/stats`
يعيد:
- counts
- concept coverage
- embedding coverage
- documents status
- unresolved relation endpoints

## `GET /api/health`
يفحص:
- database
- redis
- openai configuration
- embeddings availability
- schema warnings

## `GET /api/debug/database-audit`
يعطي تقريرًا تفصيليًا عن حالة قاعدة البيانات.

---

## الحماية الحالية

الملف:
- `app/security.py`

ويغطي:

### Sanitization
- trim
- collapse whitespace
- إزالة control chars
- إزالة null bytes
- رفض HTML الخام
- رفض الأسئلة الفارغة بعد التنظيف
- الحد الأقصى للسؤال: `500` حرف

### Rate limiting
- `/api/chat/query`: `30` طلبًا/دقيقة/IP
- `/api/chat/query-without-ai`: `30` طلبًا/دقيقة/IP
- `/api/ontology/upload`: `3` طلبات/10 دقائق/IP
- `/api/ontology/reindex`: `2` طلبان/30 دقيقة/IP
- `/api/stats`: `60` طلبًا/دقيقة/IP
- `/api/debug/database-audit`: `60` طلبًا/دقيقة/IP

ويستخدم:
- Redis إن توفر
- أو fallback داخل الذاكرة

---

## الـ embeddings

الخدمة:
- `services/embedding_service.py`

الاستخدام الحالي:
- embeddings للمفاهيم
- embeddings للمرادفات
- embeddings للعلاقات
- بنية جاهزة للوثائق

### ملاحظة مهمة
وجود embeddings في القاعدة لا يعني أن كل مسار يستخدمها.

بشكل فعلي:
- `without_ai` لا يستخدمها
- `AI` فقط هو الذي يمكنه الاستفادة منها عندما يطلب ذلك المنطق أو إعداد الاستعلام

---

## ملاحظات تشغيلية مهمة

- إعادة الفهرسة الكاملة عملية maintenance، وليست جزءًا من التدفق الطبيعي للدردشة.
- العمليات الثقيلة يفضل تشغيلها محليًا ضد قاعدة البيانات المستهدفة، لا من بيئة serverless محدودة الزمن.
- `/api/stats` يحتوي بعض الحقول المحجوزة لقياس الاستخدام، لكنها ليست tracked فعليًا بعد:
  - `total_queries`
  - `avg_processing_time`
  - `avg_confidence`

---

## الاختبارات الحالية

```bash
cd backend
python -m unittest discover tests
python -m py_compile app/main.py core/models.py processing/ttl_parser.py processing/query_analyzer.py processing/concept_matcher.py processing/relation_expander.py generation/answer_composer.py generation/answer_generator.py generation/answer_validator.py services/openai_client.py services/embedding_service.py
```

الاختبارات الحالية تغطي:
- parser counts
- shape نقاط النهاية
- rate limiting
- sanitization
- عدم استخدام OpenAI في `without_ai`
- relation expansion logic
- validation logic
- answer composition/generation logic
- idempotent TTL upload

---

## صيانة وتشخيص

توجد أدوات فحص محلية إضافية داخل `backend/` مثل:
- `inspect_sql.py`
- `inspect_ttl.py`
- `count_rows.py`
- `drop_tables.py`

هذه ليست جزءًا من مسار الإنتاج الأساسي، لكنها مفيدة للتشخيص المحلي والصيانة.
