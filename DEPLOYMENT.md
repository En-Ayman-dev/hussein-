# Deployment Guide

هذا الملف يوثق خيارات نشر المشروع كما يدعمها المستودع الحالي، مع التركيز على المسارات المناسبة فعليًا لهذا النظام، لا على حلول نظرية عامة.

الهدف من هذا الدليل:
- اختيار بنية نشر مناسبة
- فهم القيود التشغيلية
- ضبط المتغيرات البيئية اللازمة
- تنفيذ النشر دون تسريب أسرار أو ربط المشروع بمسار غير مناسب

---

## 1. ملامح المشروع التي تؤثر على قرار النشر

هذا المشروع ليس مجرد واجهة Next.js عادية، بل يتكون من:

- **Frontend**
  - `Next.js`
  - واجهة دردشة + لوحة إدارة

- **Backend**
  - `FastAPI`
  - parsing للـ TTL
  - retrieval pipeline
  - AI / without_ai modes
  - upload + reindex + audit endpoints

- **Database**
  - `PostgreSQL`
  - `pgvector`

- **Optional cache**
  - `Redis`

بالتالي لا يوجد “نشر واحد مثالي لكل الطبقات”، بل يوجد مسار موصى به ومسار بديل حسب طبيعة التشغيل.

---

## 2. ملف النشر الموصى به

## الخيار الموصى به اقتصاديًا

### Frontend
- `Vercel`

### Backend
- `Vercel` كمشروع Python منفصل أو خدمة منفصلة

### Database
- `Supabase PostgreSQL`

### Cache
- اختياري
- إذا لم يوجد Redis، فالمشروع يعمل مع fallback داخل الذاكرة

## لماذا هذا الخيار مناسب
- الواجهة أصلًا `Next.js`
- الباك يمكن تشغيله كوظيفة Python
- PostgreSQL الخارجي يناسب الحالة الحالية
- مناسب للتشغيل السريع والتكلفة المنخفضة

## القيد المهم
هذا المسار ممتاز لتشغيل:
- chat endpoints
- stats
- audit
- الواجهة

لكنه ليس الخيار الأفضل لتشغيل عمليات maintenance الثقيلة داخل بيئة serverless، مثل:
- full reindex على بيانات كبيرة
- أي عملية طويلة قد تتجاوز حدود زمن التنفيذ

لهذا السبب:
- يفضل تنفيذ reindex الثقيل محليًا ضد قاعدة البيانات المستهدفة
- أو استخدام بيئة backend طويلة العمر إذا تحولت الأعمال الثقيلة إلى جزء دوري من التشغيل

---

## 3. الخيار البديل

المستودع يحتوي أيضًا:
- `render.yaml`

وهذا يمثل خيارًا بديلاً عندما تكون الأولوية:
- backend طويل العمر
- Redis مدعوم رسميًا
- تشغيل maintenance operations على الخادم نفسه بسهولة أكبر

## ملاحظة مهمة
`render.yaml` الموجود في المستودع ليس خيارًا مجانيًا صرفًا بالضرورة، بل blueprint تشغيلي بديل.  
إذا كانت الأولوية الحالية هي التكلفة المنخفضة أو التير المجاني، فالمسار الموصى به أعلاه هو الأنسب.

---

## 4. النشر الموصى به خطوة بخطوة

## المرحلة 1: تجهيز قاعدة البيانات

أنشئ مشروع PostgreSQL مناسبًا وفعّل `pgvector`.

المتغير المطلوب في الباك:

```env
DATABASE_URL=postgresql://...
```

## المرحلة 2: نشر الـ backend

المجلد المعني:
- `backend/`

ملفات مهمة لهذا المسار:
- `backend/run.py`
- `backend/api/index.py`

المتغيرات الأساسية:

```env
DATABASE_URL=postgresql://...
CORS_ALLOWED_ORIGINS=https://your-frontend-domain
```

المتغيرات الاختيارية:

```env
OPENAI_API_KEY=...
REDIS_URL=redis://...
CORS_ALLOWED_ORIGIN_REGEX=^https://.*\\.vercel\\.app$
ENABLE_AI_REGENERATION=false
AI_MAX_REGENERATION_ATTEMPTS=1
```

## المرحلة 3: نشر الـ frontend

المجلد المعني:
- `frontend/`

المتغير الأساسي:

```env
NEXT_PUBLIC_API_BASE_URL=https://your-backend-domain
```

## المرحلة 4: تحميل البيانات

بعد تشغيل الباك وربطه بالقاعدة:

1. ارفع ملف `TTL`
2. تأكد من امتلاء:
   - `concepts`
   - `concept_synonyms`
   - `concept_relations`
3. اترك `documents` فارغًا، فهذا متوقع

## المرحلة 5: إعادة الفهرسة عند الحاجة

إذا كنت تريد embeddings:
- نفّذ `reindex` فقط عندما يكون `OPENAI_API_KEY` موجودًا
- ويفضل تنفيذ العملية الثقيلة محليًا ضد قاعدة البيانات المستهدفة، خصوصًا في بيئات serverless

---

## 5. المتغيرات البيئية حسب الطبقة

## Backend

### مطلوبة
- `DATABASE_URL`
- `CORS_ALLOWED_ORIGINS`

### اختيارية
- `OPENAI_API_KEY`
- `REDIS_URL`
- `CORS_ALLOWED_ORIGIN_REGEX`
- `ENABLE_AI_REGENERATION`
- `AI_MAX_REGENERATION_ATTEMPTS`

## Frontend

### مطلوبة
- `NEXT_PUBLIC_API_BASE_URL`

### بديل fallback
- `NEXT_PUBLIC_CHAT_API_URL`

---

## 6. ما الذي يجب نشره وما الذي لا يجب نشره

## يجب نشره
- كود `backend`
- كود `frontend`
- ملفات التوثيق العامة
- ملف الأنطولوجيا إذا كان جزءًا من المستودع العام المقصود

## لا يجب نشره
- أي ملف `.env`
- أي secrets أو tokens
- أي روابط قواعد بيانات خاصة
- أي مفاتيح OpenAI أو Redis أو مفاتيح منصات النشر
- ملفات dump خاصة أو سجلات تشغيل حساسة

---

## 7. التحقق بعد النشر

## Backend
تحقق من:
- `GET /api/health`
- `GET /api/stats`
- `GET /api/debug/database-audit`

## Frontend
تحقق من:
- تحميل الصفحة الرئيسية
- عمل وضعي `AI` و`without_ai`
- وصول الطلبات إلى الباك
- ظهور لوحة الاستكشاف
- عمل `/admin`

## Database
تحقق من:
- امتلاء `concepts`
- امتلاء `concept_synonyms`
- امتلاء `concept_relations`
- بقاء `documents` في الحالة المقصودة

---

## 8. ملاحظات تشغيلية مهمة

### 1. `without_ai` لا يحتاج embeddings
إذا كان المطلوب فقط تشغيل `without_ai` بكفاءة:
- لا تعتبر reindex شرطًا أوليًا

### 2. `AI` يحتاج `OPENAI_API_KEY`
وجود زر `AI` في الواجهة لا يكفي وحده.  
يجب أن يكون المفتاح مضبوطًا في backend environment.

### 3. إعادة الفهرسة ليست خطوة نشر إلزامية
نفذها فقط إذا كنت تحتاج embeddings فعليًا.

### 4. Redis اختياري
إذا لم يكن Redis موجودًا:
- الكاش وrate limiting سيعملان محليًا داخل العملية
- لكنه ليس بديلًا كاملاً لطبقة cache مشتركة بين instances متعددة

### 5. CORS يجب ضبطه بدقة
خصوصًا في النشر العام، حتى لا يتم رفض الطلبات أو فتح المجال بشكل أوسع من اللازم.

---

## 9. استخدام `render.yaml`

الملف:
- [`render.yaml`](./render.yaml)

يوفر blueprint بديلًا يحتوي:
- Web service للـ backend
- Redis/KeyValue
- Postgres

استخدمه فقط إذا كان هذا المسار يناسب:
- ميزانية المشروع
- الحاجة إلى خدمة backend أطول عمرًا
- الحاجة إلى تشغيل maintenance مباشرة على الخادم

---

## 10. الخلاصة

إذا كانت الأولوية الحالية:
- سرعة بدء التشغيل
- تقليل التكلفة
- فصل الواجهة والباك بطريقة بسيطة

فالمسار الأنسب هو:
- `Frontend`: Vercel
- `Backend`: Vercel Python deployment
- `Database`: PostgreSQL خارجي يدعم `pgvector`

أما إذا أصبحت العمليات الثقيلة أو إدارة البنية أهم من البساطة، فحينها يمكن نقل الـ backend إلى مسار أطول عمرًا مثل المسار الذي يخدمه `render.yaml`.
