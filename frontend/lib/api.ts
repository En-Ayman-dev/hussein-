const DEFAULT_API_BASE_URL = "http://localhost:8000";

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/api\/chat\/query\/?$/, "").replace(/\/$/, "");
}

export function getApiBaseUrl(): string {
  const configuredUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.NEXT_PUBLIC_CHAT_API_URL ||
    DEFAULT_API_BASE_URL;

  return normalizeBaseUrl(configuredUrl);
}

export function getChatApiUrl(): string {
  return `${getApiBaseUrl()}/api/chat/query`;
}

export function getChatWithoutAiApiUrl(): string {
  return `${getApiBaseUrl()}/api/chat/query-without-ai`;
}

export function getUploadApiUrl(): string {
  return `${getApiBaseUrl()}/api/ontology/upload`;
}

export function getReindexApiUrl(): string {
  return `${getApiBaseUrl()}/api/ontology/reindex`;
}

export function getStatsApiUrl(): string {
  return `${getApiBaseUrl()}/api/stats`;
}

export function getDatabaseAuditApiUrl(): string {
  return `${getApiBaseUrl()}/api/debug/database-audit`;
}
