// Path packages (spec 1.0): export with a preview, upload, preview of an import, import, cancel.
// The JSON calls go through the typed client; the download and the upload are raw requests (a file in
// either direction) with the same CSRF header and session-lost handling.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { sessionLost } from "../auth/session";
import { api, ApiError, CSRF_HEADER, unwrap, type Schemas } from "../api/client";
import { keys } from "../api/hooks";

export type ExportIn = Schemas["ExportIn"];
export type ExportProfile = ExportIn["profile"];
export type ExportComponent = NonNullable<ExportIn["components"]>[number];
export type ExportPreview = Schemas["ExportPreviewOut"];
export type PackagePreview = Schemas["PackagePreviewOut"];
export type PackageUpload = Schemas["PackageUploadOut"];
export type ImportMode = Schemas["ImportIn"]["mode"];

/** The parts a custom package can carry, in the order the dialog lists them. */
export const COMPONENTS: ExportComponent[] = ["curriculum", "lessons", "items", "renditions.video", "sources"];

/** Standard-format copies a package can carry under `standard/`. */
export const FORMATS = ["csv", "anki-apkg", "moodle-xml", "readings", "mp4-webvtt", "bibtex", "csl-json"] as const;
export type ExportFormat = (typeof FORMATS)[number];

export function useExportPreview(pathId: string, body: ExportIn, enabled: boolean) {
  return useQuery({
    queryKey: ["paths", pathId, "export-preview", body] as const,
    queryFn: () =>
      unwrap(api.POST("/api/paths/{path_id}/export-preview", { params: { path: { path_id: pathId } }, body })),
    enabled,
    placeholderData: (previous) => previous,
    staleTime: 0,
  });
}

/** The file name from a Content-Disposition header (RFC 6266 `filename*` first). */
export function dispositionName(header: string | null): string | null {
  if (!header) return null;
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      /* fall through to the plain name */
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/.exec(header);
  return plain?.[1]?.trim() || null;
}

async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    const body = (await response.json()) as { detail?: unknown };
    detail = body?.detail ?? null;
  } catch {
    /* not JSON */
  }
  return new ApiError(response.status, detail);
}

export type DownloadProgress = { received: number; total: number | null };

/**
 * Asks the server for the package and saves it through a blob URL and `<a download>`.
 * `onProgress` gets null while the server builds the package, then the bytes received.
 */
export async function downloadPackage(
  pathId: string,
  body: ExportIn,
  onProgress: (p: DownloadProgress | null) => void,
): Promise<string> {
  onProgress(null);
  const url = new URL(`/api/paths/${encodeURIComponent(pathId)}/export`, location.origin);
  const response = await globalThis.fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", [CSRF_HEADER]: "1" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  if (response.status === 401) sessionLost();
  if (!response.ok) throw await errorFrom(response);
  const name = dispositionName(response.headers.get("Content-Disposition")) ?? "path.yuo.zip";
  const length = Number(response.headers.get("Content-Length"));
  const total = Number.isFinite(length) && length > 0 ? length : null;

  let blob: Blob;
  if (response.body) {
    const reader = response.body.getReader();
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    let received = 0;
    onProgress({ received, total });
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value as Uint8Array<ArrayBuffer>);
      received += value.byteLength;
      onProgress({ received, total });
    }
    blob = new Blob(chunks, { type: "application/zip" });
  } else {
    blob = await response.blob();
    onProgress({ received: blob.size, total });
  }

  const href = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.rel = "noopener";
    a.style.display = "none";
    document.body.append(a);
    a.click();
    a.remove();
  } finally {
    // the click has handed the blob to the browser's download; free it once that has started
    setTimeout(() => URL.revokeObjectURL(href), 10_000);
  }
  return name;
}

/** Thrown when an upload cannot reach the server at all. */
export class UploadNetworkError extends Error {
  constructor() {
    super("network error");
    this.name = "UploadNetworkError";
  }
}

export type Upload = { promise: Promise<PackageUpload>; abort: () => void };

/**
 * Uploads a package file as the raw request body. XMLHttpRequest, because fetch has no upload
 * progress; `onProgress` gets the fraction sent (0 to 1) when the browser knows it.
 */
export function uploadPackage(file: Blob, onProgress: (fraction: number | null) => void): Upload {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<PackageUpload>((resolve, reject) => {
    xhr.open("POST", "/api/packages");
    xhr.setRequestHeader("Content-Type", "application/zip");
    xhr.setRequestHeader(CSRF_HEADER, "1");
    xhr.responseType = "text";
    xhr.upload.onprogress = (e) => onProgress(e.lengthComputable && e.total > 0 ? e.loaded / e.total : null);
    xhr.onerror = () => reject(new UploadNetworkError());
    xhr.onabort = () => reject(new DOMException("upload cancelled", "AbortError"));
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText) as unknown;
      } catch {
        /* not JSON */
      }
      if (xhr.status === 401) sessionLost();
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : null;
        reject(new ApiError(xhr.status, detail));
        return;
      }
      resolve(data as PackageUpload);
    };
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}

export function useImportPackage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ token, mode }: { token: string; mode: ImportMode }) =>
      unwrap(api.POST("/api/packages/{token}/import", { params: { path: { token } }, body: { mode } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.paths }),
  });
}

/** Removes an upload from the server (nothing was imported). Best effort: failures are ignored. */
export async function dropUpload(token: string): Promise<void> {
  try {
    await api.DELETE("/api/packages/{token}", { params: { path: { token } } });
  } catch {
    /* best effort: the upload stays on the server until it is removed there */
  }
}
