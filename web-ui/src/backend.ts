import { aesApiBaseUrl } from "./config";
import type { BackendLogResponse, ModelCatalog } from "./types";

export async function loadModelCatalog(): Promise<ModelCatalog> {
  const response = await fetch(`${aesApiBaseUrl}/api/models`, {
    credentials: "include",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await responseMessage(response, "Model catalog request failed"));
  }
  const catalog = (await response.json()) as ModelCatalog;
  if (!catalog.default_model || !Array.isArray(catalog.models)) {
    throw new Error("AES returned an invalid model catalog.");
  }
  return catalog;
}

export async function loadBackendLogs(
  after: number,
  limit = 400,
): Promise<BackendLogResponse> {
  const query = new URLSearchParams({
    after: String(Math.max(0, after)),
    limit: String(limit),
  });
  const response = await fetch(`${aesApiBaseUrl}/api/logs?${query}`, {
    credentials: "include",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await responseMessage(response, "Backend log request failed"));
  }
  return (await response.json()) as BackendLogResponse;
}

async function responseMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail) {
      return payload.detail;
    }
  } catch {
    // Use the bounded fallback below for non-JSON proxy responses.
  }
  return `${fallback}: ${response.status}`;
}
