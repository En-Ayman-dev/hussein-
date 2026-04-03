# Arabic Ontology Chat API - Backend

واجهة FastAPI لمعالجة ملف الأنطولوجيا `TTL`، تخزينه في PostgreSQL/pgvector، ثم تقديم إجابات عربية عبر مسارين:

- `AI`: تحليل + مطابقة + علاقات + توليد عبر OpenAI عند توفر المفتاح.
- `without_ai`: نفس الاستدلال المحلي بدون أي طلبات إلى OpenAI.

## التشغيل

### المتطلبات
- Python 3.10+
- PostgreSQL مع `pgvector`
- Redis اختياري للكاش وrate limiting
- مفتاح OpenAI اختياري لمسار `AI` والـ embeddings

### الإعداد
انسخ `.env.example` إلى `.env` ثم اضبط القيم:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/ontology_db
OPENAI_API_KEY=your_openai_api_key_here
REDIS_URL=redis://localhost:6379
```

شغّل الخادم من المسار الرسمي:

```bash
python run.py
```

## المكونات الأساسية

- `processing/ttl_parser.py`: استخراج `concepts`, `synonyms`, `relations` من `TTL`
- `processing/text_normalizer.py`: تطبيع النص العربي
- `core/models.py`: جداول `concepts`, `concept_synonyms`, `concept_relations`, `documents`
- `services/embedding_service.py`: embeddings للمفاهيم والمرادفات والعلاقات والوثائق
- `processing/query_analyzer.py`: تصنيف نية السؤال
- `processing/concept_matcher.py`: exact/synonym/full-text/vector matching
- `processing/relation_expander.py`: توسيع العلاقات بحسب النية والعمق
- `generation/answer_composer.py`: اختيار template أو LLM
- `generation/answer_validator.py`: فحص grounding وإعادة توليد مشروطة
- `app/security.py`: sanitization + rate limiting

## المسارات الحالية

### `POST /api/chat/query`
المسار الكامل مع OpenAI عند توفر المفتاح.

### `POST /api/chat/query-without-ai`
مسار محلي بالكامل، لا يستخدم OpenAI ولا vector search.

### `POST /api/ontology/upload`
يرفع ملف `TTL` ويخزن:
- المفاهيم
- المرادفات
- العلاقات

إذا كان `generate_embeddings=true` ومفتاح OpenAI متاحًا، تُولَّد embeddings كذلك.

### `POST /api/ontology/reindex`
يعيد بناء embeddings للجداول المدعومة:
- `concepts`
- `concept_synonyms`
- `concept_relations`

جدول `documents` يبقى خارج ingest الحالي، لذلك يظهر دائمًا:

```json
{
  "status": "not_ingested_from_current_ttl"
}
```

### `GET /api/stats`
ملخص سريع يشمل:
- counts
- concept coverage
- embedding coverage
- unresolved relation endpoints

### `GET /api/debug/database-audit`
تشخيص مفصل لقاعدة البيانات الحالية:
- fingerprint آمن
- row counts
- concept coverage
- embedding coverage
- unresolved relation endpoints
- documents status

### `GET /api/health`
فحص صحة الخدمات والسكيمة.

## الحماية الحالية

- تنظيف السؤال قبل المعالجة:
  - trim
  - collapse whitespace
  - إزالة control chars وnull bytes
  - رفض HTML الخام
- rate limiting:
  - `/api/chat/query`: 30 طلبًا/دقيقة لكل IP
  - `/api/chat/query-without-ai`: 30 طلبًا/دقيقة لكل IP
  - `/api/ontology/upload`: 3 طلبات/10 دقائق لكل IP
  - `/api/ontology/reindex`: طلبان/30 دقيقة لكل IP
  - `/api/stats`: 60 طلبًا/دقيقة لكل IP
  - `/api/debug/database-audit`: 60 طلبًا/دقيقة لكل IP

## قاعدة البيانات الحالية

المصدر الوحيد للبيانات هو `../unified_ontology.ttl`.

الحالة المقصودة:
- `concepts`, `concept_synonyms`, `concept_relations`: مُغذاة من `TTL`
- `documents`: موجودة سكيميًا فقط، وغير مُغذاة من المصدر الحالي

قد تبقى بعض `source_concept_id/target_concept_id = NULL` في العلاقات عندما تشير بعض الـ URIs إلى أطراف غير معرّفة كمفاهيم مستقلة داخل `TTL`. هذا سلوك صحيح وليس تلفًا في البيانات.

## التحقق

فحوص التطوير الأساسية:

```bash
python -m unittest discover backend/tests
python -m py_compile app/main.py core/models.py processing/ttl_parser.py processing/query_analyzer.py processing/concept_matcher.py processing/relation_expander.py generation/answer_composer.py generation/answer_generator.py generation/answer_validator.py services/openai_client.py services/embedding_service.py
```
