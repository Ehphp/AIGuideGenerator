"use client";

import { useEffect, useMemo, useState } from "react";
import { apiBase } from "@/lib/apiClient";

interface TranscribeArtifact {
    path?: string;
    language?: string | null;
    segment_count?: number | null;
}

interface TranscriptSegment {
    start: number;
    end: number;
    text: string;
}

interface TranscribeJson {
    text?: string;
    language?: string | null;
    engine?: string | null;
    model?: string | null;
    segments?: TranscriptSegment[];
}

interface Props {
    artifact: TranscribeArtifact | null | undefined;
}

function fmtTime(sec: number): string {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
}

export function TranscriptPanel({ artifact }: Props) {
    const path = artifact?.path;
    const [data, setData] = useState<TranscribeJson | null>(null);
    const [err, setErr] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [view, setView] = useState<"text" | "segments">("text");
    const [open, setOpen] = useState(true);

    useEffect(() => {
        if (!path) return;
        let cancelled = false;
        setLoading(true);
        setErr(null);
        fetch(`${apiBase}/files/${path}`)
            .then(async (r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return (await r.json()) as TranscribeJson;
            })
            .then((j) => {
                if (!cancelled) setData(j);
            })
            .catch((e: unknown) => {
                if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [path]);

    const textLen = data?.text?.length ?? 0;
    const segCount = data?.segments?.length ?? 0;
    const totalDuration = useMemo(() => {
        if (!data?.segments?.length) return null;
        return data.segments[data.segments.length - 1]?.end ?? null;
    }, [data]);

    if (!path) return null;

    return (
        <div className="rounded border border-border">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex w-full items-center justify-between border-b border-border px-4 py-3 text-left"
            >
                <div className="flex items-center gap-3">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Trascrizione
                    </h3>
                    {data && (
                        <span className="text-xs text-muted-foreground">
                            {textLen.toLocaleString()} caratteri · {segCount} segmenti
                            {data.language ? ` · ${data.language}` : ""}
                            {data.model ? ` · ${data.engine ?? "stt"}/${data.model}` : ""}
                            {totalDuration !== null ? ` · ${fmtTime(totalDuration)}` : ""}
                        </span>
                    )}
                </div>
                <span className="text-xs text-muted-foreground">{open ? "▲" : "▼"}</span>
            </button>

            {open && (
                <div className="flex flex-col gap-3 p-4">
                    {loading && (
                        <p className="text-xs text-muted-foreground">Caricamento…</p>
                    )}
                    {err && (
                        <p className="text-xs text-red-700">Errore: {err}</p>
                    )}
                    {data && (
                        <>
                            <div className="flex gap-1 text-xs">
                                <button
                                    type="button"
                                    onClick={() => setView("text")}
                                    className={`rounded px-2 py-1 ${view === "text"
                                            ? "bg-foreground text-background"
                                            : "border border-border text-muted-foreground hover:bg-muted"
                                        }`}
                                >
                                    Testo completo
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setView("segments")}
                                    className={`rounded px-2 py-1 ${view === "segments"
                                            ? "bg-foreground text-background"
                                            : "border border-border text-muted-foreground hover:bg-muted"
                                        }`}
                                >
                                    Segmenti ({segCount})
                                </button>
                                <a
                                    href={`${apiBase}/files/${path}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="ml-auto rounded border border-border px-2 py-1 text-muted-foreground hover:bg-muted"
                                >
                                    JSON ↗
                                </a>
                            </div>

                            {view === "text" && (
                                <div className="max-h-96 overflow-y-auto rounded bg-muted/40 p-3 text-sm leading-relaxed">
                                    {data.text ? (
                                        <p className="whitespace-pre-wrap break-words">
                                            {data.text}
                                        </p>
                                    ) : (
                                        <p className="text-muted-foreground">
                                            (testo vuoto — vedi i segmenti)
                                        </p>
                                    )}
                                </div>
                            )}

                            {view === "segments" && (
                                <div className="max-h-96 overflow-y-auto rounded border border-border">
                                    <ol className="divide-y divide-border">
                                        {(data.segments ?? []).map((seg, i) => (
                                            <li
                                                key={i}
                                                className="flex gap-3 px-3 py-1.5 text-xs"
                                            >
                                                <span className="shrink-0 font-mono text-muted-foreground">
                                                    {fmtTime(seg.start)}–{fmtTime(seg.end)}
                                                </span>
                                                <span className="break-words text-foreground">
                                                    {seg.text}
                                                </span>
                                            </li>
                                        ))}
                                    </ol>
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
