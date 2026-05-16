"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
    apiBase,
    deleteSession,
    getSession,
    reprocessSession,
    retrySession,
} from "@/lib/apiClient";
import type { PipelineEvent, Session } from "@/lib/types";
import { GuideEditorShell } from "@/components/guide/GuideEditorShell";
import { PipelineStagesTable } from "@/components/session/PipelineStagesTable";
import { AiUsagePanel } from "@/components/session/AiUsagePanel";
import { SanitizationPanel } from "@/components/session/SanitizationPanel";
import { EgressInspectorPanel } from "@/components/session/EgressInspectorPanel";

const STATUS_STYLES: Record<string, string> = {
    created: "bg-muted text-muted-foreground",
    uploaded: "bg-blue-100 text-blue-800",
    processing: "bg-amber-100 text-amber-800",
    ready: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
};

const PIPELINE_STAGES: { label: string; messages: string[] }[] = [
    {
        label: "Queue job",
        messages: ["Reprocessing", "Retrying"],
    },
    {
        label: "Start pipeline",
        messages: ["Pipeline starting", "Retry: pipeline starting"],
    },
    { label: "Probe media", messages: ["Probing media"] },
    { label: "Extract audio", messages: ["Extracting audio"] },
    { label: "Transcribe", messages: ["Transcribing"] },
    { label: "Extract frames", messages: ["Extracting frames"] },
    { label: "Analyse frames", messages: ["Analyzing frames"] },
    { label: "Build timeline", messages: ["Building timeline"] },
    { label: "Sanitize timeline", messages: ["Sanitizing timeline"] },
    { label: "Generate guide", messages: ["Generating guide"] },
    { label: "Rehydrate guide", messages: ["Rehydrating guide"] },
    { label: "Validate guide", messages: ["Validating guide"] },
];

const TERMINAL = new Set(["ready", "failed"]);

type Tab = "pipeline" | "guide";

export default function SessionDetailPage() {
    const params = useParams<{ id: string }>();
    const id = params.id;
    const [session, setSession] = useState<Session | null>(null);
    const [err, setErr] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [activeTab, setActiveTab] = useState<Tab>("pipeline");
    const [pollKey, setPollKey] = useState(0);

    useEffect(() => {
        if (!id) return;
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | null = null;

        const tick = async () => {
            try {
                const s = await getSession(id);
                if (cancelled) return;
                setSession(s);
                setErr(null);
                if (!TERMINAL.has(s.status)) {
                    timer = setTimeout(tick, 2000);
                }
            } catch (e) {
                if (cancelled) return;
                setErr(e instanceof Error ? e.message : String(e));
                timer = setTimeout(tick, 4000);
            }
        };

        void tick();
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, [id, pollKey]);

    const handleRetry = async () => {
        if (!session) return;
        setBusy(true);
        try {
            await retrySession(session.id);
            const s = await getSession(session.id);
            setSession(s);
            setPollKey((k) => k + 1);
        } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    };

    const handleReprocess = async () => {
        if (!session) return;
        if (
            !confirm(
                "Re-run the full pipeline? The current guide and all intermediate artifacts will be overwritten."
            )
        )
            return;
        setBusy(true);
        try {
            await reprocessSession(session.id);
            const s = await getSession(session.id);
            setSession(s);
            setPollKey((k) => k + 1);
        } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    };

    const handleDelete = async () => {
        if (!session) return;
        if (!confirm("Delete this session and its media?")) return;
        setBusy(true);
        try {
            await deleteSession(session.id);
            window.location.href = "/";
        } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
            setBusy(false);
        }
    };

    return (
        <main className="container mx-auto flex max-w-5xl flex-col gap-6 px-4 py-12">
            {/* ── Header ── */}
            <div className="flex items-center justify-between">
                <h1 className="truncate text-2xl font-bold tracking-tight">
                    {session?.title || "Session"}
                </h1>
                <Link href="/" className="text-sm text-muted-foreground hover:underline">
                    ← All sessions
                </Link>
            </div>

            {/* Poll / network error */}
            {err && (
                <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
                    {err}
                </div>
            )}

            {!session && !err && (
                <div className="text-sm text-muted-foreground">Loading…</div>
            )}

            {session && (
                <>
                    {/* Status bar — always visible */}
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                        <span
                            className={`rounded-full px-2 py-0.5 text-xs ${STATUS_STYLES[session.status] ?? "bg-muted"}`}
                        >
                            {session.status}
                        </span>
                        <span className="text-muted-foreground">
                            {session.source_type ?? "—"}
                        </span>
                        <span className="text-muted-foreground">
                            created {new Date(session.created_at).toLocaleString()}
                        </span>
                    </div>

                    {/* ── Tab navigation ── */}
                    <div className="flex border-b border-border">
                        <button
                            type="button"
                            onClick={() => setActiveTab("pipeline")}
                            className={`-mb-px px-4 py-2 text-sm transition-colors ${
                                activeTab === "pipeline"
                                    ? "border-b-2 border-foreground font-medium text-foreground"
                                    : "text-muted-foreground hover:text-foreground"
                            }`}
                        >
                            Pipeline / Gestione
                        </button>
                        <button
                            type="button"
                            onClick={() => setActiveTab("guide")}
                            className={`-mb-px px-4 py-2 text-sm transition-colors ${
                                activeTab === "guide"
                                    ? "border-b-2 border-foreground font-medium text-foreground"
                                    : "text-muted-foreground hover:text-foreground"
                            }`}
                        >
                            Risultato / Guida
                            {!session.guide_content && (
                                <span className="ml-1.5 text-xs opacity-50">—</span>
                            )}
                        </button>
                    </div>

                    {/* ══════════════════════════════════════
                        Tab 1 — Pipeline / Gestione
                    ══════════════════════════════════════ */}
                    {activeTab === "pipeline" && (
                        <div className="flex flex-col gap-6">
                            {/* Progress message (during processing) */}
                            {session.progress_message && session.status !== "ready" && (
                                <div className="rounded border border-border bg-muted p-3 text-sm">
                                    {session.progress_message}
                                </div>
                            )}

                            {/* Live pipeline progress (animated, only during processing) */}
                            {session.status === "processing" && (
                                <PipelineProgress
                                    currentMessage={session.progress_message}
                                    events={session.pipeline_events ?? []}
                                />
                            )}

                            {/* Session error */}
                            {session.error && (
                                <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
                                    <div className="font-medium">Error</div>
                                    <pre className="mt-1 whitespace-pre-wrap break-words text-xs">
                                        {session.error}
                                    </pre>
                                </div>
                            )}

                            {/* Media metadata */}
                            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded border border-border p-4 text-sm">
                                <dt className="text-muted-foreground">Media MIME</dt>
                                <dd className="font-mono text-xs">{session.media_mime ?? "—"}</dd>
                                <dt className="text-muted-foreground">Size</dt>
                                <dd>
                                    {session.media_size_bytes
                                        ? `${(session.media_size_bytes / (1024 * 1024)).toFixed(1)} MB`
                                        : "—"}
                                </dd>
                                <dt className="text-muted-foreground">Duration</dt>
                                <dd>
                                    {session.media_duration_sec
                                        ? `${session.media_duration_sec.toFixed(1)} s`
                                        : "—"}
                                </dd>
                                <dt className="text-muted-foreground">Media key</dt>
                                <dd className="truncate font-mono text-xs">
                                    {session.media_key ?? "—"}
                                </dd>
                            </dl>

                            {/* Media link */}
                            {session.media_key && (
                                <a
                                    href={`${apiBase}/files/${session.media_key}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="w-fit text-sm text-muted-foreground hover:underline"
                                >
                                    Open uploaded media ↗
                                </a>
                            )}

                            {/* Pipeline stages table (shown when at least one stage has completed) */}
                            {Object.keys(session.pipeline_artifacts ?? {}).length > 0 && (
                                <PipelineStagesTable
                                    artifacts={session.pipeline_artifacts ?? {}}
                                    events={session.pipeline_events ?? []}
                                    aiUsage={session.ai_usage}
                                />
                            )}

                            {/* Sanitization diagnostics panel */}
                            {(session.pipeline_artifacts?.["sanitize_timeline"] ||
                                session.pipeline_artifacts?.["generate_guide"]) && (
                                <SanitizationPanel
                                    artifacts={session.pipeline_artifacts ?? {}}
                                />
                            )}

                            {/* Egress inspector — what was actually sent to the AI provider */}
                            {(session.pipeline_artifacts?.["egress_generate_guide"] ||
                                session.pipeline_artifacts?.["egress_validate_repair"]) && (
                                <EgressInspectorPanel
                                    artifacts={session.pipeline_artifacts ?? {}}
                                />
                            )}

                            {/* Pipeline event log — collapsed by default, visible after processing */}
                            {(session.pipeline_events ?? []).length > 0 &&
                                session.status !== "processing" && (
                                    <PipelineEventTimeline events={session.pipeline_events} />
                                )}

                            {/* AI usage diagnostics */}
                            <AiUsagePanel aiUsage={session.ai_usage} />

                            {/* ── Action buttons ── */}
                            <div className="flex items-center gap-2">
                                {session.status === "failed" && (
                                    <button
                                        type="button"
                                        onClick={() => void handleRetry()}
                                        disabled={busy}
                                        className="rounded border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
                                    >
                                        Retry processing
                                    </button>
                                )}
                                {(session.status === "ready" || session.status === "failed") &&
                                    session.media_key && (
                                        <button
                                            type="button"
                                            onClick={() => void handleReprocess()}
                                            disabled={busy}
                                            className="rounded border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
                                        >
                                            Re-run pipeline
                                        </button>
                                    )}
                                <button
                                    type="button"
                                    onClick={() => void handleDelete()}
                                    disabled={busy}
                                    className="ml-auto rounded border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
                                >
                                    Delete session
                                </button>
                            </div>
                        </div>
                    )}

                    {/* ══════════════════════════════════════
                        Tab 2 — Risultato / Guida
                    ══════════════════════════════════════ */}
                    {activeTab === "guide" && (
                        <div className="flex flex-col gap-4">
                            {session.status === "ready" ? (
                                <GuideEditorShell
                                    guide={session.guide_content}
                                    session={session}
                                    onGuideUpdated={(updated) => setSession(updated)}
                                />
                            ) : (
                                <div className="rounded border border-border p-10 text-center text-sm text-muted-foreground">
                                    <p className="font-medium">Guide not available yet</p>
                                    <p className="mt-1 text-xs">
                                        {session.status === "processing"
                                            ? "The pipeline is still running — check the Pipeline tab for progress."
                                            : session.status === "failed"
                                              ? "The pipeline failed before a guide could be generated."
                                              : "No guide has been generated for this session yet."}
                                    </p>
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </main>
    );
}

function PipelineProgress({
    currentMessage,
    events,
}: {
    currentMessage: string | null;
    events: PipelineEvent[];
}) {
    const currentIdx = PIPELINE_STAGES.findIndex(
        (s) => s.messages.includes(currentMessage ?? "")
    );

    return (
        <div className="rounded border border-amber-200 bg-amber-50 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-amber-900">
                <Spinner />
                Processing…
            </div>
            <ol className="flex flex-col gap-2">
                {PIPELINE_STAGES.map((stage, i) => {
                    const done = currentIdx === -1 ? false : i < currentIdx;
                    const active = i === currentIdx;
                    const doneEvent = done
                        ? events.findLast((e) => stage.messages.some((m) =>
                            m.toLowerCase().replace(/ing$/, "") === e.stage.replace(/_/g, " ").split(" ")[0].toLowerCase()
                            || e.stage.replace(/_/g, " ") === stage.label.toLowerCase()
                        ))
                        : undefined;
                    return (
                        <li key={stage.label} className="flex items-center gap-2 text-sm">
                            {done ? (
                                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-green-500 text-white text-xs">✓</span>
                            ) : active ? (
                                <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                                    <Spinner size="sm" />
                                </span>
                            ) : (
                                <span className="h-5 w-5 shrink-0 rounded-full border-2 border-muted-foreground/30" />
                            )}
                            <span className={
                                done ? "text-green-700 line-through decoration-green-500/50"
                                    : active ? "font-medium text-amber-900"
                                        : "text-muted-foreground"
                            }>
                                {stage.label}
                            </span>
                            {doneEvent && (
                                <span className="ml-auto text-xs text-muted-foreground">
                                    {new Date(doneEvent.t).toLocaleTimeString()}
                                </span>
                            )}
                        </li>
                    );
                })}
            </ol>
            {events.length > 0 && (
                <PipelineEventTimeline events={events} compact />
            )}
        </div>
    );
}

function PipelineEventTimeline({
    events,
    compact = false,
}: {
    events: PipelineEvent[];
    compact?: boolean;
}) {
    const [open, setOpen] = useState(!compact);

    if (events.length === 0) return null;

    return (
        <div className={compact ? "mt-4 border-t border-amber-200 pt-3" : "rounded border border-border p-4"}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className={`flex w-full items-center justify-between text-xs font-medium ${compact ? "text-amber-800" : "text-muted-foreground"
                    }`}
            >
                <span>Pipeline events ({events.length})</span>
                <span>{open ? "▲" : "▼"}</span>
            </button>
            {open && (
                <ol className="mt-2 flex flex-col gap-1">
                    {events.map((ev, i) => (
                        <li key={i} className="flex items-start gap-2 text-xs">
                            <span
                                className={`mt-0.5 shrink-0 rounded px-1 py-0.5 font-mono ${ev.level === "error"
                                        ? "bg-red-100 text-red-700"
                                        : ev.level === "warn"
                                            ? "bg-yellow-100 text-yellow-700"
                                            : "bg-muted text-muted-foreground"
                                    }`}
                            >
                                {new Date(ev.t).toLocaleTimeString()}
                            </span>
                            <span className="font-medium text-foreground">{ev.stage.replace(/_/g, " ")}</span>
                            <span className="text-muted-foreground">{ev.message}</span>
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}

function Spinner({ size = "md" }: { size?: "sm" | "md" }) {
    const cls = size === "sm"
        ? "h-4 w-4 border-2"
        : "h-4 w-4 border-2";
    return (
        <span
            className={`inline-block ${cls} animate-spin rounded-full border-amber-600 border-t-transparent`}
        />
    );
}


