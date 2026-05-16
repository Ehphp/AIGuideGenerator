"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Recorder } from "@/components/recorder/Recorder";
import { Uploader } from "@/components/uploader/Uploader";
import { createSession, uploadMedia } from "@/lib/apiClient";
import type { RecordedMedia } from "@/hooks/useScreenRecorder";

type Mode = "record" | "upload";

export default function NewSessionPage() {
    const router = useRouter();
    const [mode, setMode] = useState<Mode>("record");
    const [title, setTitle] = useState("");
    const [recorded, setRecorded] = useState<RecordedMedia | null>(null);
    const [picked, setPicked] = useState<File | null>(null);
    const [submitting, setSubmitting] = useState(false);
    const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(
        null
    );
    const [err, setErr] = useState<string | null>(null);

    const canSubmit =
        !submitting && (mode === "record" ? !!recorded : !!picked);

    const handleSubmit = async () => {
        setErr(null);
        setSubmitting(true);
        setProgress(null);
        try {
            const session = await createSession(
                mode === "record" ? "recorded" : "uploaded",
                title.trim() || undefined
            );

            let blob: Blob;
            let filename: string;
            let mime: string;
            if (mode === "record") {
                if (!recorded) throw new Error("No recording available");
                blob = recorded.blob;
                const ext = recorded.mimeType.includes("webm") ? "webm" : "bin";
                filename = `recording.${ext}`;
                mime = recorded.mimeType;
            } else {
                if (!picked) throw new Error("No file picked");
                blob = picked;
                filename = picked.name;
                mime = picked.type || "application/octet-stream";
            }

            await uploadMedia(session.id, blob, filename, mime, (loaded, total) =>
                setProgress({ loaded, total })
            );
            router.push(`/sessions/${session.id}`);
        } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
            setSubmitting(false);
        }
    };

    return (
        <main className="container mx-auto flex max-w-3xl flex-col gap-6 px-4 py-12">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold tracking-tight">New session</h1>
                <Link href="/" className="text-sm text-muted-foreground hover:underline">
                    ← Back
                </Link>
            </div>

            <label className="flex flex-col gap-1">
                <span className="text-sm font-medium">Title (optional)</span>
                <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g. Reset a user password in the admin portal"
                    className="rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    disabled={submitting}
                />
            </label>

            <div className="flex gap-2 border-b border-border">
                <button
                    type="button"
                    onClick={() => setMode("record")}
                    disabled={submitting}
                    className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${mode === "record"
                            ? "border-foreground text-foreground"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                >
                    Record screen
                </button>
                <button
                    type="button"
                    onClick={() => setMode("upload")}
                    disabled={submitting}
                    className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${mode === "upload"
                            ? "border-foreground text-foreground"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                >
                    Upload file
                </button>
            </div>

            {mode === "record" ? (
                <Recorder disabled={submitting} onRecorded={setRecorded} />
            ) : (
                <Uploader disabled={submitting} onPicked={setPicked} />
            )}

            {err && (
                <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
                    {err}
                </div>
            )}

            {progress && progress.total > 0 && (
                <div className="flex flex-col gap-1">
                    <div className="text-xs text-muted-foreground">
                        Uploading… {Math.round((progress.loaded / progress.total) * 100)}%
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded bg-muted">
                        <div
                            className="h-full bg-foreground transition-all"
                            style={{
                                width: `${Math.min(100, (progress.loaded / progress.total) * 100)}%`,
                            }}
                        />
                    </div>
                </div>
            )}

            <div className="flex items-center gap-3">
                <button
                    type="button"
                    disabled={!canSubmit}
                    onClick={() => void handleSubmit()}
                    className="rounded bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
                >
                    {submitting ? "Uploading…" : "Create & upload"}
                </button>
                <Link
                    href="/"
                    className="text-sm text-muted-foreground hover:underline"
                >
                    Cancel
                </Link>
            </div>
        </main>
    );
}
