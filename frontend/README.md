# Frontend

واجهة Next.js لعرض المحادثة ولوحة الإدارة فوق واجهة الـ backend.

## التشغيل

ثبت الاعتماديات ثم شغّل الواجهة:

```bash
npm install
npm run dev
```

الواجهة تعمل افتراضيًا مع:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

إذا لم تضبط المتغير، سيُستخدم هذا العنوان تلقائيًا.

## الصفحات الأساسية

### `/`
صفحة المحادثة الرئيسية، وتدعم:
- التبديل بين `AI` و`بدون AI`
- تنسيق markdown للردود
- زر نسخ
- typing animation
- خلاصة للمفهوم والاقتباسات والعلاقات

### `/admin`
لوحة متابعة تشغيلية تعرض:
- رفع ملف `TTL`
- إعادة الفهرسة
- إحصائيات مختصرة
- `database-audit`
- تغطية embeddings
- تغطية بيانات المفاهيم
- حالة `documents`

## ملفات مهمة

- `app/page.tsx`: واجهة المحادثة
- `app/admin/page.tsx`: لوحة الإدارة
- `components/chat-message.tsx`: فقاعة الرسائل
- `components/markdown-message.tsx`: تنسيق markdown
- `lib/api.ts`: جميع روابط الـ backend

## التحقق

```bash
npm run lint
npm run build
```
