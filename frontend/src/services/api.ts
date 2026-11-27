// All requests go to same-origin /api, rewritten by Next.js to the FastAPI backend.
// The session lives in an httpOnly cookie set by the backend; no token is stored in the browser.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", cache: "no-store", ...init });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    window.location.href = "/login";
  }
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* body is not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  form: <T>(path: string, data: FormData) => request<T>(path, { method: "POST", body: data }),
};

export const documentUrl = (id: string) => `/api/documents/${id}/file`;
