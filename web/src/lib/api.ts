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
