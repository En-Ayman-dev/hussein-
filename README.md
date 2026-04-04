# Hussein

نظام دردشة معرفي عربي مبني فوق أنطولوجيا بصيغة `TTL`، يقدّم استرجاعًا معرفيًا موجّهًا للمفاهيم والعلاقات، مع مسارين للإجابة:

- `AI`: استرجاع محلي مضبوط بالسياق ثم توليد جواب عربي ثري عند توفر مفتاح OpenAI.
- `without_ai`: مسار محلي بالكامل يعتمد على القاعدة والمطابقة والعلاقات والقوالب، بدون أي نداءات إلى نماذج AI.

المشروع مصمم ليجمع بين:
- وضوح الاسترجاع المعرفي
- قابلية التشغيل بدون AI
- واجهة دردشة عربية حديثة
- لوحة تشغيل وإدارة للأنطولوجيا

---

## نظرة سريعة

### ما الذي يقدمه المشروع
- استيعاب ملف أنطولوجيا `TTL` وتحويله إلى بنية قابلة للاستعلام.
- مطابقة الأسئلة العربية مع المفاهيم والمرادفات والعلاقات.
- توسعة السياق عبر العلاقات المرتبطة بالمفهوم بحسب نوع السؤال.
- إجابات عربية منظمة في وضعين مستقلين: `AI` و`without_ai`.
- لوحة استكشاف معرفي تفاعلية داخل الواجهة.
- لوحة إدارة لرفع الأنطولوجيا، إعادة الفهرسة، ومراجعة حالة قاعدة البيانات.

### لماذا يوجد مساران للإجابة
- `AI` مناسب عندما يكون المطلوب تفسيرًا أوسع وتحليلًا أكثر سلاسة.
- `without_ai` مناسب عندما تكون الأولوية للسرعة، الحتمية، وعدم استهلاك أي توكنات خارجية.

---

## المعمارية باختصار

```text
unified_ontology.ttl
        |
        v
TTL Parser + Normalization
        |
        v
PostgreSQL / pgvector
        |
        +--> In-memory runtime snapshot
        |
        v
FastAPI retrieval pipeline
  - intent analysis
  - concept matching
  - relation expansion
  - answer composition
        |
        +--> AI mode
        +--> without_ai mode
        |
        v
Next.js chat UI + admin dashboard
```

---

## مكونات المشروع

### Backend
- `FastAPI`
- `SQLAlchemy`
- `PostgreSQL`
- `pgvector`
- `Redis` اختياري للكاش والـ rate limiting
- `OpenAI` اختياري لمسار `AI` والـ embeddings

### Frontend
- `Next.js`
- `React`
- `TypeScript`
- `Tailwind CSS`

---

## هيكل المستودع

```text
backend/   API, retrieval pipeline, ingestion, validation, embeddings
frontend/  Chat UI, insight panel, admin dashboard
unified_ontology.ttl
DEPLOYMENT.md
توثيق المشروع الفعلي.md
```

---

## التشغيل المحلي

## 1. تشغيل الـ backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

### الحد الأدنى من الإعداد
أنشئ ملف `backend/.env` اعتمادًا على `backend/.env.example`.

المتغيرات الأهم:
- `DATABASE_URL`
- `OPENAI_API_KEY` اختياري
- `REDIS_URL` اختياري
- `CORS_ALLOWED_ORIGINS`

## 2. تشغيل الـ frontend

```bash
cd frontend
npm install
npm run dev
```

### متغير البيئة الأساسي
أنشئ `frontend/.env.local` إذا لزم:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

## أهم الصفحات

### `/`
واجهة المحادثة الرئيسية، وتدعم:
- التبديل بين `AI` و`بدون AI`
- تنسيق Markdown
- اقتراحات أسئلة حسب الوضع
- مؤشر كتابة وتمييز بصري بين المسارين
- لوحة استكشاف معرفي تفاعلية

### `/admin`
لوحة الإدارة، وتدعم:
- رفع ملف `TTL`
- إعادة الفهرسة
- مراجعة الإحصائيات
- فحص قاعدة البيانات عبر `database-audit`

---

## أهم مسارات الـ API

- `POST /api/chat/query`
- `POST /api/chat/query-without-ai`
- `POST /api/ontology/upload`
- `POST /api/ontology/reindex`
- `GET /api/stats`
- `GET /api/health`
- `GET /api/debug/database-audit`

---

## التشغيل المعرفي

المشروع لا يتعامل مع الجواب كنص حر فقط، بل يمر عبر مراحل واضحة:

1. تنظيف السؤال والتحقق منه.
2. تحليل intent للسؤال.
3. مطابقة المفهوم الأنسب.
4. توسعة العلاقات المرتبطة بالمفهوم.
5. توليد الجواب:
   - محليًا في `without_ai`
   - أو عبر LLM مضبوط بالسياق في `AI`
6. التحقق من grounding قبل إعادة النتيجة.

---

## ملاحظات تشغيلية مهمة

- جدول `documents` موجود في السكيمة لكنه غير مغذى من مصدر الـ `TTL` الحالي.
- بعض العلاقات قد تشير إلى أطراف غير معرفة كمفاهيم مستقلة، ولذلك قد تبقى بعض foreign keys فارغة بشكل صحيح.
- `without_ai` لا يستخدم OpenAI إطلاقًا.
- إعادة بناء embeddings عملية تشغيلية مستقلة، وليست شرطًا لعمل `without_ai`.
- العمليات الثقيلة مثل إعادة الفهرسة الكاملة يفضل تنفيذها محليًا ضد قاعدة البيانات المستهدفة، لا عبر بيئة serverless محدودة.

---

## التحقق الأساسي

### Backend
```bash
cd backend
python -m unittest discover tests
python -m py_compile app/main.py
```

### Frontend
```bash
cd frontend
npm run lint
npm run build
```

---

## التوثيق

- [DEPLOYMENT.md](./DEPLOYMENT.md): توثيق النشر والخيارات التشغيلية.
- [backend/README.md](./backend/README.md): توثيق الخدمة الخلفية.
- [frontend/README.md](./frontend/README.md): توثيق الواجهة الأمامية.
- [توثيق المشروع الفعلي.md](./توثيق%20المشروع%20الفعلي.md): المرجع التفصيلي الشامل للحالة الحالية والمعمارية.

---

## ملاحظات أمنية

- لا تحفظ أي مفاتيح أو روابط خاصة أو بيانات بيئة حقيقية داخل المستودع.
- استخدم ملفات `.env` محلية أو متغيرات بيئة في منصة النشر.
- راجع CORS وRate Limiting قبل أي نشر عام.

---

## الرخصة

لا توجد رخصة منشورة حاليًا داخل المستودع. إذا كان المشروع سيصبح عامًا لفريق أوسع أو للاستخدام الخارجي، يفضل إضافة `LICENSE` واضحة.
