import type { Quota, Submission } from "../types";

const CSRF_HEADER = { "X-Requested-With": "ADMIN-Challenge" };

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function failure(status: number, body: unknown) {
  const data = (body ?? {}) as { detail?: unknown; code?: unknown };
  // Without a message from the API, a 5xx is the server's side (e.g. the gateway's
  // 502 page while the API restarts), not something the user typed.
  const fallback =
    status >= 500
      ? "서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도하세요."
      : "요청 정보를 확인해 주세요.";
  return new ApiError(
    typeof data.detail === "string" ? data.detail : fallback,
    status,
    typeof data.code === "string" ? data.code : undefined,
  );
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      ...CSRF_HEADER,
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw failure(response.status, body);
  return body as T;
}

export const send = <T = unknown>(
  path: string,
  body?: object,
  method: "POST" | "PATCH" = "POST",
) => api<T>(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });

// fetch() cannot report upload progress, so the ZIP goes through XMLHttpRequest.
// The body is the raw file; its name travels in the X-Filename header.
export function uploadZip(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<Submission & Quota> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/submissions");
    request.setRequestHeader("X-Requested-With", "ADMIN-Challenge");
    request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    request.setRequestHeader("Content-Type", "application/zip");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(request.responseText);
      } catch {}
      if (request.status >= 200 && request.status < 300)
        resolve(body as Submission & Quota);
      else reject(failure(request.status, body));
    };
    request.onerror = () =>
      reject(
        new ApiError(
          "업로드 중 연결이 끊어졌습니다. 파일 크기와 네트워크를 확인한 뒤 다시 시도하세요.",
          0,
          "network",
        ),
      );
    request.send(file);
  });
}
