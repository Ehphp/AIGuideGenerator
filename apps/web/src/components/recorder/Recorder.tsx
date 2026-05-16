"use client";

import { useEffect, useRef } from "react";
import { Circle, Square } from "lucide-react";
import { useScreenRecorder } from "@/hooks/useScreenRecorder";
import type { RecordedMedia } from "@/hooks/useScreenRecorder";

function formatElapsed(ms: number): string {
    const total = Math.floor(ms / 1000);
    const m = Math.floor(total / 60)
        .toString()
        .padStart(2, "0");
    const s = (total % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
}

export interface RecorderProps {
    disabled?: boolean;
    onRecorded: (media: RecordedMedia) => void;
}

export function Recorder({ disabled, onRecorded }: RecorderProps) {
    const r = useScreenRecorder();
    const videoRef = useRef<HTMLVideoElement | null>(null);

    // Attach preview stream.
    useEffect(() => {
        const v = videoRef.current;
        if (!v) return;
        if (r.previewStream) {
            v.srcObject = r.previewStream;
            v.muted = true;
            v.play().catch(() => {
                /* autoplay may be blocked; ignore */
            });
        } else {
            v.srcObject = null;
        }
    }, [r.previewStream]);

    // Notify parent once we have a finalized recording.
    useEffect(() => {
        if (r.state === "ready" && r.recorded) {
            onRecorded(r.recorded);
        }
    }, [r.state, r.recorded, onRecorded]);

    if (!r.isSupported) {
        return (
            <div className="rounded border border-border bg-muted p-4 text-sm text-muted-foreground">
                Screen recording is not supported in this browser. Try a recent Chrome,
                Edge or Firefox.
            </div>
        );
    }

    const isRecording = r.state === "recording" || r.state === "stopping";
    const isBusy =
        r.state === "requesting" || r.state === "recording" || r.state === "stopping";

    return (
        <div className="flex flex-col gap-3">
            <div className="aspect-video w-full overflow-hidden rounded border border-border bg-black">
                {r.previewStream ? (
                    <video
                        ref={videoRef}
                        className="h-full w-full object-contain"
                        playsInline
                    />
                ) : (
                    <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
                        {r.state === "ready"
                            ? "Recording finished. Preview ended."
                            : "Preview will appear here once recording starts."}
                    </div>
                )}
            </div>

            <div className="flex items-center gap-3">
                {!isRecording ? (
                    <button
                        type="button"
                        disabled={disabled || isBusy}
                        onClick={() => void r.start()}
                        className="inline-flex items-center gap-2 rounded bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                    >
                        <Circle className="h-4 w-4 fill-current" />
                        {r.state === "requesting" ? "Requesting…" : "Start recording"}
                    </button>
                ) : (
                    <button
                        type="button"
                        onClick={r.stop}
                        className="inline-flex items-center gap-2 rounded bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90"
                    >
                        <Square className="h-4 w-4 fill-current" />
                        Stop
                    </button>
                )}

                <div className="text-sm tabular-nums text-muted-foreground">
                    {formatElapsed(r.elapsedMs)}
                </div>

                {r.state === "ready" && r.recorded && (
                    <button
                        type="button"
                        onClick={r.reset}
                        className="ml-auto rounded border border-border px-3 py-2 text-sm hover:bg-muted"
                    >
                        Discard & re-record
                    </button>
                )}
            </div>

            {r.error && (
                <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
                    {r.error}
                </div>
            )}

            {r.state === "ready" && r.recorded && (
                <div className="rounded border border-border bg-muted p-3 text-sm">
                    Recorded {(r.recorded.sizeBytes / (1024 * 1024)).toFixed(1)} MB ·{" "}
                    {formatElapsed(r.recorded.durationMs)} · {r.recorded.mimeType}
                </div>
            )}
        </div>
    );
}
