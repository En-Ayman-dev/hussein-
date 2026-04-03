"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  getDatabaseAuditApiUrl,
  getReindexApiUrl,
  getStatsApiUrl,
  getUploadApiUrl,
} from "@/lib/api";

const UPLOAD_ENDPOINT = getUploadApiUrl();
const REINDEX_ENDPOINT = getReindexApiUrl();
const STATS_ENDPOINT = getStatsApiUrl();
const AUDIT_ENDPOINT = getDatabaseAuditApiUrl();

type NumericMap = Record<string, number>;

type Stats = {
  avg_confidence: number;
  avg_processing_time: number;
  concept_count: number;
  concept_coverage: NumericMap;
  document_count: number;
  documents_status: string;
  embedding_count: number;
  embedding_coverage: NumericMap;
  relation_count: number;
  synonym_count: number;
  total_queries: number;
  unresolved_relation_endpoints: NumericMap;
};

type AuditResponse = {
  concept_coverage: NumericMap;
  database: {
    fingerprint: {
      database?: string | null;
      driver?: string | null;
      host?: string | null;
      port?: number | null;
    };
    schema_warnings: string[];
  };
  documents: {
    row_count: number;
    status: string;
  };
  embedding_coverage: NumericMap;
  row_counts: NumericMap;
  unresolved_relation_endpoints: NumericMap;
};

type EmbeddingSummary = {
  concepts?: NumericMap;
  documents?: NumericMap & { status?: string };
  relations?: NumericMap;
  synonyms?: NumericMap;
  totals?: NumericMap;
};

type UploadResponse = {
  data: {
    concepts_created: number;
    concepts_embeddings_processed: number;
    concepts_embeddings_stored: number;
    concepts_stored: number;
    concepts_updated: number;
    documents_embeddings_processed: number;
    documents_embeddings_stored: number;
    embedding_error: string | null;
    embedding_status: string;
    embedding_summary: EmbeddingSummary;
    embeddings_generated: number;
    embeddings_stored: number;
    relations_embeddings_processed: number;
    relations_embeddings_stored: number;
    relations_stored: number;
    synonyms_embeddings_processed: number;
    synonyms_embeddings_stored: number;
    synonyms_stored: number;
    undefined_relation_endpoints: NumericMap;
    warnings: string[];
  };
  message: string;
  status: string;
};

type ReindexResponse = {
  concepts_embeddings_stored: number;
  concepts_processed: number;
  documents_embeddings_stored: number;
  documents_processed: number;
  embedding_summary: EmbeddingSummary;
  embeddings_generated: number;
  embeddings_skipped: number;
  embeddings_stored: number;
  relations_embeddings_stored: number;
  relations_processed: number;
  status: string;
  synonyms_embeddings_stored: number;
  synonyms_processed: number;
  undefined_relation_endpoints: NumericMap;
};

function renderMetricCards(items: Array<{ label: string; value: number | string }>) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div
          key={item.label}
          className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-4"
        >
          <p className="text-xs font-semibold tracking-[0.16em] text-slate-500">
            {item.label}
          </p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{item.value}</p>
        </div>
      ))}
    </div>
  );
}

function renderNumberList(title: string, values: NumericMap, emptyLabel = "لا توجد بيانات.") {
  const entries = Object.entries(values);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      {entries.length > 0 ? (
        <ul className="mt-4 space-y-2 text-sm text-slate-700">
          {entries.map(([key, value]) => (
            <li key={key} className="flex items-center justify-between gap-4 border-b border-slate-100 pb-2 last:border-b-0 last:pb-0">
              <span className="text-slate-500">{key}</span>
              <span className="font-medium text-slate-900">{value}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-slate-500">{emptyLabel}</p>
      )}
    </section>
  );
}

export default function AdminPage() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResponse["data"] | null>(null);

  const [reindexing, setReindexing] = useState(false);
  const [reindexMessage, setReindexMessage] = useState<string | null>(null);
  const [reindexResult, setReindexResult] = useState<ReindexResponse | null>(null);

  const [stats, setStats] = useState<Stats | null>(null);
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const [loadingDashboard, setLoadingDashboard] = useState(false);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  async function loadDashboard() {
    setLoadingDashboard(true);
    setDashboardError(null);

    try {
      const [statsResponse, auditResponse] = await Promise.all([
        fetch(STATS_ENDPOINT),
        fetch(AUDIT_ENDPOINT),
      ]);

      if (!statsResponse.ok) {
        throw new Error(`Stats fetch failed: ${statsResponse.status}`);
      }
      if (!auditResponse.ok) {
        throw new Error(`Audit fetch failed: ${auditResponse.status}`);
      }

      const [statsPayload, auditPayload] = (await Promise.all([
        statsResponse.json(),
        auditResponse.json(),
      ])) as [Stats, AuditResponse];

      setStats(statsPayload);
      setAudit(auditPayload);
    } catch (error) {
      const message = error instanceof Error ? error.message : "حدث خطأ غير معروف.";
      setDashboardError(message);
      setStats(null);
      setAudit(null);
    } finally {
      setLoadingDashboard(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setUploadMessage("يرجى اختيار ملف TTL أولاً.");
      return;
    }

    setUploading(true);
    setUploadMessage(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(UPLOAD_ENDPOINT, {
        method: "POST",
        body: formData,
      });

      const payload = (await response.json()) as UploadResponse | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload && payload.detail ? payload.detail : `Upload failed: ${response.status}`);
      }

      const result = (payload as UploadResponse).data;
      setUploadResult(result);
      setUploadMessage(
        `تم رفع الملف بنجاح: ${result.concepts_stored} مفهوم، ${result.synonyms_stored} مرادف، ${result.relations_stored} علاقة.`
      );
      setFile(null);
      await loadDashboard();
    } catch (error) {
      const message = error instanceof Error ? error.message : "حدث خطأ أثناء رفع الملف.";
      setUploadMessage(`خطأ: ${message}`);
      setUploadResult(null);
    } finally {
      setUploading(false);
    }
  }

  async function handleReindex() {
    setReindexing(true);
    setReindexMessage(null);

    try {
      const response = await fetch(REINDEX_ENDPOINT, {
        method: "POST",
      });

      const payload = (await response.json()) as ReindexResponse | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload && payload.detail ? payload.detail : `Reindex failed: ${response.status}`);
      }

      const result = payload as ReindexResponse;
      setReindexResult(result);
      setReindexMessage(
        `إعادة الفهرسة اكتملت: ${result.embeddings_stored} embedding مخزنة، مع ${result.embeddings_skipped} عناصر متجاوزة.`
      );
      await loadDashboard();
    } catch (error) {
      const message = error instanceof Error ? error.message : "حدث خطأ أثناء إعادة الفهرسة.";
      setReindexMessage(`خطأ: ${message}`);
      setReindexResult(null);
    } finally {
      setReindexing(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 p-4 text-slate-900 sm:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="rounded-[30px] border border-white/75 bg-white/82 px-6 py-5 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl">
          <h1 className="text-2xl font-semibold text-slate-950">لوحة الإدارة</h1>
          <p className="mt-2 text-sm leading-7 text-slate-500">
            هذه الصفحة تعكس حالة قاعدة البيانات الفعلية، وتعرض تفاصيل الرفع، الفهرسة، والتغطية بدل الاكتفاء بعدادات سطحية.
          </p>
        </header>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="rounded-[30px] border border-white/75 bg-white/82 p-6 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl">
            <h2 className="text-xl font-semibold text-slate-950">رفع ملف TTL</h2>
            <form onSubmit={handleUpload} className="mt-4 space-y-4">
              <input
                type="file"
                accept=".ttl"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
                disabled={uploading}
                className="block w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
              />
              <button
                type="submit"
                disabled={!file || uploading}
                className="rounded-full bg-[linear-gradient(135deg,#0f172a,#0369a1)] px-5 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {uploading ? "جاري الرفع..." : "رفع TTL"}
              </button>
            </form>

            {uploadMessage ? (
              <p className="mt-4 text-sm leading-7 text-slate-700">{uploadMessage}</p>
            ) : null}

            {uploadResult ? (
              <div className="mt-5 space-y-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                <p className="text-sm font-semibold text-slate-900">آخر نتيجة رفع</p>
                <ul className="space-y-2 text-sm text-slate-700">
                  <li>المفاهيم المنشأة: {uploadResult.concepts_created}</li>
                  <li>المفاهيم المحدثة: {uploadResult.concepts_updated}</li>
                  <li>المرادفات المخزنة: {uploadResult.synonyms_stored}</li>
                  <li>العلاقات المخزنة: {uploadResult.relations_stored}</li>
                  <li>حالة embeddings: {uploadResult.embedding_status}</li>
                  <li>عدد التحذيرات: {uploadResult.warnings.length}</li>
                </ul>
                {uploadResult.embedding_error ? (
                  <p className="text-sm text-red-600">{uploadResult.embedding_error}</p>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="rounded-[30px] border border-white/75 bg-white/82 p-6 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl">
            <h2 className="text-xl font-semibold text-slate-950">إعادة الفهرسة</h2>
            <p className="mt-2 text-sm leading-7 text-slate-500">
              يعيد هذا الإجراء بناء embeddings للمفاهيم والمرادفات والعلاقات فقط. الوثائق تبقى خارج ingest الحالي.
            </p>
            <button
              type="button"
              onClick={() => void handleReindex()}
              disabled={reindexing}
              className="mt-4 rounded-full bg-emerald-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {reindexing ? "جاري إعادة الفهرسة..." : "بدء إعادة الفهرسة"}
            </button>

            {reindexMessage ? (
              <p className="mt-4 text-sm leading-7 text-slate-700">{reindexMessage}</p>
            ) : null}

            {reindexResult ? (
              <div className="mt-5 space-y-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                <p className="text-sm font-semibold text-slate-900">آخر نتيجة فهرسة</p>
                <ul className="space-y-2 text-sm text-slate-700">
                  <li>المفاهيم المعالجة: {reindexResult.concepts_processed}</li>
                  <li>المرادفات المعالجة: {reindexResult.synonyms_processed}</li>
                  <li>العلاقات المعالجة: {reindexResult.relations_processed}</li>
                  <li>الوثائق المعالجة: {reindexResult.documents_processed}</li>
                  <li>Embeddings المخزنة: {reindexResult.embeddings_stored}</li>
                  <li>Embeddings المتجاوزة: {reindexResult.embeddings_skipped}</li>
                </ul>
              </div>
            ) : null}
          </div>
        </section>

        {loadingDashboard ? (
          <section className="rounded-[30px] border border-white/75 bg-white/82 px-6 py-8 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl">
            <p className="text-sm text-slate-500">جارٍ تحميل لوحة المتابعة...</p>
          </section>
        ) : dashboardError ? (
          <section className="rounded-[30px] border border-red-200 bg-red-50 px-6 py-8 shadow-sm">
            <p className="text-sm text-red-700">خطأ في تحميل بيانات الإدارة: {dashboardError}</p>
          </section>
        ) : stats && audit ? (
          <div className="space-y-6">
            <section className="rounded-[30px] border border-white/75 bg-white/82 p-6 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl">
              <h2 className="text-xl font-semibold text-slate-950">ملخص سريع</h2>
              <div className="mt-5">
                {renderMetricCards([
                  { label: "عدد المفاهيم", value: stats.concept_count },
                  { label: "عدد العلاقات", value: stats.relation_count },
                  { label: "عدد المرادفات", value: stats.synonym_count },
                  { label: "عدد الوثائق", value: stats.document_count },
                  { label: "Embeddings المفاهيم", value: stats.embedding_count },
                  { label: "حالة الوثائق", value: stats.documents_status },
                  { label: "متوسط الزمن", value: stats.avg_processing_time },
                  { label: "متوسط الثقة", value: stats.avg_confidence },
                ])}
              </div>
            </section>

            <section className="grid gap-6 xl:grid-cols-2">
              {renderNumberList("عدد الصفوف الفعلي", audit.row_counts)}
              {renderNumberList("تغطية embeddings", audit.embedding_coverage)}
              {renderNumberList("تغطية بيانات المفاهيم", audit.concept_coverage)}
              {renderNumberList("النهايات غير المعرفة في العلاقات", audit.unresolved_relation_endpoints)}
            </section>

            <section className="grid gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-lg font-semibold text-slate-950">حالة قاعدة البيانات</h2>
                <ul className="mt-4 space-y-2 text-sm text-slate-700">
                  <li>Driver: {audit.database.fingerprint.driver || "غير معروف"}</li>
                  <li>Host: {audit.database.fingerprint.host || "غير معروف"}</li>
                  <li>Port: {audit.database.fingerprint.port || "غير معروف"}</li>
                  <li>Database: {audit.database.fingerprint.database || "غير معروف"}</li>
                  <li>حالة documents: {audit.documents.status}</li>
                  <li>صفوف documents: {audit.documents.row_count}</li>
                </ul>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-lg font-semibold text-slate-950">تحذيرات السكيمة</h2>
                {audit.database.schema_warnings.length > 0 ? (
                  <ul className="mt-4 space-y-2 text-sm text-slate-700">
                    {audit.database.schema_warnings.map((warning) => (
                      <li key={warning} className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
                        {warning}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-emerald-700">لا توجد تحذيرات سكيمة حالياً.</p>
                )}
              </div>
            </section>
          </div>
        ) : null}
      </div>
    </main>
  );
}
