import type { Guide, Session, SourceType } from "./types";

const API_BASE =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function handle<T>(res: Response): Promise<T> {
    if (!res.ok) {
        let detail: unknown;
        try {
            detail = await res.json();
        } catch {
            detail = await res.text().catch(() => "");
        }
        let msg = `HTTP ${res.status}`;
        if (detail && typeof detail === "object" && "detail" in detail) {
            msg = String((detail as { detail: unknown }).detail);
        } else if (typeof detail === "string" && detail) {
            msg = detail;
        }
        throw new Error(msg);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
}

export const apiBase = API_BASE;

export async function createSession(
    source_type: SourceType,
    title?: string
): Promise<Session> {
    const res = await fetch(`${API_BASE}/api/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_type, title: title ?? null }),
    });
    return handle<Session>(res);
}

export async function uploadMedia(
    id: string,
    file: Blob,
    filename: string,
    contentType: string,
    onProgress?: (loaded: number, total: number) => void
): Promise<Session> {
    // Use XMLHttpRequest so we can report progress.
    return new Promise<Session>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${API_BASE}/api/v1/sessions/${id}/media`);
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total);
        };
        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    resolve(JSON.parse(xhr.responseText) as Session);
                } catch (e) {
                    reject(e);
                }
            } else {
                let msg = `HTTP ${xhr.status}`;
                try {
                    const j = JSON.parse(xhr.responseText);
                    if (j && j.detail) msg = String(j.detail);
                } catch {
                    /* ignore */
                }
                reject(new Error(msg));
            }
        };
        xhr.onerror = () => reject(new Error("Network error"));
        xhr.onabort = () => reject(new Error("Upload aborted"));

        const fd = new FormData();
        const f =
            file instanceof File ? file : new File([file], filename, { type: contentType });
        fd.append("file", f);
        xhr.send(fd);
    });
}

export async function listSessions(): Promise<Session[]> {
    const res = await fetch(`${API_BASE}/api/v1/sessions`, { cache: "no-store" });
    return handle<Session[]>(res);
}

export async function getSession(id: string): Promise<Session> {
    const res = await fetch(`${API_BASE}/api/v1/sessions/${id}`, {
        cache: "no-store",
    });
    return handle<Session>(res);
}

export async function deleteSession(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/v1/sessions/${id}`, {
        method: "DELETE",
    });
    await handle<void>(res);
}

export async function retrySession(id: string): Promise<unknown> {
    const res = await fetch(`${API_BASE}/api/v1/sessions/${id}/retry`, {
        method: "POST",
    });
    return handle<unknown>(res);
}

export async function reprocessSession(id: string): Promise<unknown> {
    const res = await fetch(`${API_BASE}/api/v1/sessions/${id}/reprocess`, {
        method: "POST",
    });
    return handle<unknown>(res);
}

export async function updateGuideContent(
    id: string,
    guide: Guide
): Promise<Session> {
    const res = await fetch(`${API_BASE}/api/v1/sessions/${id}/guide`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ guide }),
    });
    return handle<Session>(res);
}

export function getGuideExportUrl(sessionId: string): string {
    return `${API_BASE}/api/v1/sessions/${sessionId}/export.docx`;
}
