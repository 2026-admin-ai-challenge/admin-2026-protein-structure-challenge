import type { Quota, Submission } from "../types";

const CSRF_HEADER = { "X-Requested-With": "ADMIN-Challenge" };

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    const context = [status > 0 ? `HTTP ${status}` : "", code ? `오류 코드: ${code}` : ""]
      .filter(Boolean)
      .join(" · ");
    super(context ? `${message}\n[${context}]` : message);
    this.name = "ApiError";
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
  // FastAPI validation failures contain one entry per invalid field. Only show
  // the location and message; input/ctx can contain passwords or other secrets.
  const validation = Array.isArray(data.detail)
    ? data.detail.flatMap((entry: unknown) => {
        if (!entry || typeof entry !== "object") return [];
        const item = entry as { loc?: unknown; msg?: unknown };
        if (typeof item.msg !== "string") return [];
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => typeof part === "string" || typeof part === "number").join(".")
          : "";
        return [location ? `${location}: ${item.msg}` : item.msg];
      }).join("\n")
    : "";
  return new ApiError(
    typeof data.detail === "string" && data.detail.trim()
      ? data.detail
      : validation ? `입력값을 확인해 주세요.\n${validation}` : fallback,
    status,
    typeof data.code === "string" ? data.code : undefined,
  );
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      ...options,
      headers: {
        ...CSRF_HEADER,
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(
      "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도하세요.",
      0,
      "network",
    );
  }
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
