# Hussein

مشروع دردشة معرفية عربي مبني فوق أنطولوجيا `TTL`، ويقدّم مسارين للاستجابة:

- `AI`: استدلال محلي + توليد عبر OpenAI عند توفر المفتاح.
- `without_ai`: استدلال محلي كامل بدون إرسال أي طلبات إلى نماذج AI.

البيانات المصدرية الحالية موجودة في [unified_ontology.ttl](./unified_ontology.ttl)، وتُغذّي قاعدة البيانات عبر مسار ingest في الباك.

## هيكل المشروع

- [backend](./backend): FastAPI + PostgreSQL/pgvector + منطق الاستدلال والـ ingestion
- [frontend](./frontend): Next.js لواجهة المحادثة ولوحة الإدارة
- [DEPLOYMENT.md](./DEPLOYMENT.md): خطة النشر المقترحة على Vercel + Render
- [خطة التنفيذ الكاملة.md](./خطة التنفيذ الكاملة.md): مرجع التخطيط والتنفيذ للمشروع

## المتطلبات

- Python 3.10+
- PostgreSQL مع `pgvector`
- Node.js 20+ و `npm`
- Redis اختياري للكاش والـ rate limiting
- مفتاح OpenAI اختياري لمسار `AI` ولتوليد embeddings

## التشغيل السريع

### 1. تجهيز الباك

من داخل [backend](./backend):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

أنشئ ملف `backend/.env` اعتمادًا على `.env.example`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/ontology_db
OPENAI_API_KEY=your_openai_api_key_here
REDIS_URL=redis://localhost:6379
```

ثم شغّل الخادم:

```bash
cd backend
python run.py
```

### 2. تجهيز الفرونت

من داخل [frontend](./frontend):

```bash
npm install
npm run dev
```

إذا أردت تحديد عنوان الباك صراحة:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## المسارات الأساسية

- `POST /api/chat/query`: المحادثة مع `AI` عند توفر المفتاح
- `POST /api/chat/query-without-ai`: محادثة محلية بالكامل بدون OpenAI
- `POST /api/ontology/upload`: رفع ملف `TTL` وإعادة تغذية الجداول
- `POST /api/ontology/reindex`: إعادة بناء embeddings المدعومة
- `GET /api/stats`: إحصائيات التشغيل والتغطية
- `GET /api/debug/database-audit`: تشخيص كامل لحالة قاعدة البيانات
- `GET /api/health`: فحص الصحة

## الصفحات الأساسية

- `/`: واجهة المحادثة الرئيسية
- `/admin`: لوحة الإدارة ورفع `TTL` ومتابعة الإحصائيات و`database-audit`

## ملاحظات تشغيلية

- جدول `documents` موجود في السكيمة لكنه غير مُغذى من `TTL` الحالي عمدًا.
- بعض العلاقات قد تحتوي `source_concept_id` أو `target_concept_id` بقيمة `NULL` عندما يشير `TTL` إلى أطراف غير معرّفة كمفاهيم مستقلة. هذا سلوك صحيح.
- مسار `without_ai` لا ينبغي أن يرسل أي طلبات إلى OpenAI، ويعتمد فقط على التحليل المحلي والمطابقة النصية والعلاقات.

## التحقق

### Backend

```bash
cd backend
python -m unittest discover tests
python -m py_compile app/main.py core/models.py processing/ttl_parser.py processing/query_analyzer.py processing/concept_matcher.py processing/relation_expander.py generation/answer_composer.py generation/answer_generator.py generation/answer_validator.py services/openai_client.py services/embedding_service.py
```

### Frontend

```bash
cd frontend
npm run lint
npm run build
```

## توثيق فرعي

- [backend/README.md](./backend/README.md)
- [frontend/README.md](./frontend/README.md)
