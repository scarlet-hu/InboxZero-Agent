// Thin fetch wrapper that always sends the session cookie. The backend's
// CORS middleware echoes Access-Control-Allow-Credentials, which is what
// makes credentials: "include" actually deliver the cookie cross-origin.

export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const resp = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new ApiError(resp.status, detail);
  }

  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

export const loginUrl = () => `${BACKEND_URL}/auth/login`;
export const demoLoginUrl = () => `${BACKEND_URL}/auth/demo-login`;

// ---------------------------------------------------------------------------
// Draft review-approve HITL surface
// ---------------------------------------------------------------------------

export interface DraftContent {
  draft_id: string;
  to: string;
  subject: string;
  body: string;
}

export function getDraft(draftId: string): Promise<DraftContent> {
  return api<DraftContent>(`/agent/drafts/${encodeURIComponent(draftId)}`);
}

export function updateDraft(
  draftId: string,
  payload: { subject: string; body: string },
): Promise<DraftContent> {
  return api<DraftContent>(`/agent/drafts/${encodeURIComponent(draftId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function sendDraft(draftId: string): Promise<void> {
  return api<void>(`/agent/drafts/${encodeURIComponent(draftId)}/send`, {
    method: "POST",
  });
}

export function discardDraft(draftId: string): Promise<void> {
  return api<void>(`/agent/drafts/${encodeURIComponent(draftId)}`, {
    method: "DELETE",
  });
}
