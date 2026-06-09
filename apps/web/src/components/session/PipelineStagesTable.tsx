"use client";

import type { AiUsage, PipelineEvent } from "@/lib/types";

interface StageDefinition {
    key: string;
    label: string;
    optional?: boolean;
}

const STAGES: StageDefinition[] = [
    { key: "ingest", label: "Ingest / Probe media" },
    { key: "extract_audio", label: "Extract audio" },
    { key: "transcribe", label: "Transcribe" },
    { key: "extract_frames", label: "Extract frames" },
    { key: "analyze_frames", label: "Analyse frames" },
    { key: "build_timeline", label: "Build timeline" },
    { key: "sanitize_timeline", label: "Sanitize timeline", optional: true },
    { key: "generate_guide", label: "Generate guide" },
    { key: "rehydrate_guide", label: "Rehydrate guide", optional: true },
    { key: "validate_guide", label: "Validate guide" },
    { key: "attach_evidence", label: "Attach evidence" },
];

function fmtDuration(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
}

function getStageNote(
    key: string,
    artifact: unknown,
    aiUsage: AiUsage | null | undefined,
): string | null {
    if (artifact === null || artifact === undefined) return null;

    // ingest: { duration, width, height, has_audio }
    if (key === "ingest" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        const parts: string[] = [];
        if (typeof a.width === "number" && typeof a.height === "number") {
            parts.push(`${a.width}×${a.height}`);
        }
        if (typeof a.has_audio === "boolean") {
            parts.push(a.has_audio ? "audio ✓" : "no audio");
        }
        return parts.length ? parts.join(" · ") : null;
    }

    // transcribe: { path, segment_count, language }
    if (key === "transcribe" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        const parts: string[] = [];
        if (typeof a.segment_count === "number") parts.push(`${a.segment_count} segments`);
        if (typeof a.language === "string" && a.language) parts.push(`lang: ${a.language}`);
        return parts.length ? parts.join(" · ") : null;
    }

    // extract_frames: legacy list [{idx,t,key}] or dict {frames:[...], ...stats}
    if (key === "extract_frames") {
        if (Array.isArray(artifact)) {
            return `${artifact.length} frames extracted`;
        }
        if (typeof artifact === "object" && artifact !== null) {
            const a = artifact as Record<string, unknown>;
            const count =
                typeof a.frame_count_final === "number"
                    ? a.frame_count_final
                    : Array.isArray(a.frames)
                        ? (a.frames as unknown[]).length
                        : null;
            const parts: string[] = [];
            if (count !== null) parts.push(`${count} frames`);
            if (typeof a.frame_max_gap_sec === "number")
                parts.push(`max gap ${a.frame_max_gap_sec.toFixed(1)}s`);
            return parts.length ? parts.join(" · ") : null;
        }
        return null;
    }

    // analyze_frames: array (per-frame, scrubbed)
    if (key === "analyze_frames" && Array.isArray(artifact)) {
        return `${artifact.length} frames analysed`;
    }

    // build_timeline: { path, event_count }
    if (key === "build_timeline" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        if (typeof a.event_count === "number") return `${a.event_count} timeline events`;
        return null;
    }

    // sanitize_timeline: { event_count, events_modified, placeholder_count, categories, ... }
    if (key === "sanitize_timeline" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        const count = typeof a.placeholder_count === "number" ? a.placeholder_count : null;
        const modified = typeof a.events_modified === "number" ? a.events_modified : null;
        if (count === 0) return "Nessun pattern sensibile";
        if (count !== null) {
            const cats =
                a.categories && typeof a.categories === "object" && !Array.isArray(a.categories)
                    ? Object.keys(a.categories as Record<string, unknown>).join(", ")
                    : null;
            const base = `${count} redazion${count !== 1 ? "i" : "e"}`;
            const mod = modified ? ` · ${modified} eventi` : "";
            const catStr = cats ? ` (${cats})` : "";
            return `${base}${mod}${catStr}`;
        }
        return null;
    }

    // generate_guide: { path, output_chars } + model from ai_usage
    if (key === "generate_guide" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        const parts: string[] = [];
        const model = aiUsage?.models?.llm;
        if (model) parts.push(`model: ${model}`);
        if (typeof a.output_chars === "number") parts.push(`${a.output_chars.toLocaleString()} chars out`);
        return parts.length ? parts.join(" · ") : null;
    }

    // rehydrate_guide: { path, placeholders_resolved, placeholders_unresolved }
    if (key === "rehydrate_guide" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        const unresolved = typeof a.placeholders_unresolved === "number" ? a.placeholders_unresolved : 0;
        const resolved = typeof a.placeholders_resolved === "number" ? a.placeholders_resolved : 0;
        if (unresolved > 0) return `⚠ ${unresolved} unresolved placeholders`;
        if (resolved > 0) return `${resolved} placeholders resolved`;
        return null;
    }

    // validate_guide: { first_error: null, ok: true } or { first_error: "...", ... }
    if (key === "validate_guide" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        if (typeof a.first_error === "string" && a.first_error) {
            const excerpt = a.first_error.length > 80 ? `${a.first_error.slice(0, 80)}…` : a.first_error;
            return `⚠ repair: ${excerpt}`;
        }
        if (a.ok === true || a.first_error === null) return "ok";
        return null;
    }

    // attach_evidence: { step_count, steps_with_click, attached_count, kept_llm, unresolved_count }
    if (key === "attach_evidence" && typeof artifact === "object" && !Array.isArray(artifact)) {
        const a = artifact as Record<string, unknown>;
        const parts: string[] = [];
        if (typeof a.step_count === "number") parts.push(`${a.step_count} steps`);
        if (typeof a.attached_count === "number") parts.push(`${a.attached_count} attached`);
        if (typeof a.unresolved_count === "number" && a.unresolved_count > 0) {
            parts.push(`⚠ ${a.unresolved_count} unresolved`);
        }
        return parts.length ? parts.join(" · ") : null;
    }

    return null;
}

interface Props {
    artifacts: Record<string, unknown>;
    events: PipelineEvent[];
    aiUsage?: AiUsage | null;
}

export function PipelineStagesTable({ artifacts, events, aiUsage }: Props) {
    // Build sorted event list and a map: stage_key → completion timestamp (ms)
    const sorted = [...events].sort(
        (a, b) => new Date(a.t).getTime() - new Date(b.t).getTime(),
    );
    const eventTsList = sorted.map((e) => ({
        stage: e.stage,
        ts: new Date(e.t).getTime(),
    }));
    const eventMap = new Map(eventTsList.map((e) => [e.stage, e.ts]));

    // Total pipeline duration: first to last event
    const totalDuration =
        eventTsList.length >= 2
            ? eventTsList[eventTsList.length - 1].ts - eventTsList[0].ts
            : null;

    // Per-stage duration: completion_ts - previous_event_ts
    function getStageDuration(key: string): number | null {
        const idx = eventTsList.findIndex((e) => e.stage === key);
        if (idx <= 0) return null; // no prior baseline
        return eventTsList[idx].ts - eventTsList[idx - 1].ts;
    }

    // Filter optional stages: only show if present in artifacts or events
    const visibleStages = STAGES.filter((s) => {
        if (!s.optional) return true;
        return s.key in artifacts || eventMap.has(s.key);
    });

    return (
        <div className="rounded border border-border">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Pipeline stages
                </h3>
                {totalDuration !== null && (
                    <span className="text-xs text-muted-foreground">
                        Total ~{fmtDuration(totalDuration)}
                    </span>
                )}
            </div>
            <ol className="divide-y divide-border">
                {visibleStages.map((stage) => {
                    const artifact = artifacts[stage.key];
                    const done =
                        artifact !== undefined && artifact !== null && artifact !== false;
                    const duration = getStageDuration(stage.key);
                    const note = done ? getStageNote(stage.key, artifact, aiUsage) : null;
                    const isWarning = typeof note === "string" && note.startsWith("⚠");

                    return (
                        <li
                            key={stage.key}
                            className="flex items-center gap-3 px-4 py-2.5 text-sm"
                        >
                            {/* Status dot */}
                            {done ? (
                                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-green-500 text-[10px] font-bold text-white">
                                    ✓
                                </span>
                            ) : (
                                <span className="h-4 w-4 shrink-0 rounded-full border-2 border-muted-foreground/30" />
                            )}

                            {/* Stage name */}
                            <span
                                className={
                                    done ? "text-foreground" : "text-muted-foreground"
                                }
                            >
                                {stage.label}
                                {stage.optional && !done && (
                                    <span className="ml-1 text-xs opacity-50">(skipped)</span>
                                )}
                            </span>

                            {/* Inline note */}
                            {note && (
                                <span
                                    className={`truncate text-xs ${isWarning
                                            ? "text-amber-700"
                                            : "text-muted-foreground"
                                        }`}
                                >
                                    {note}
                                </span>
                            )}

                            {/* Approx duration — pushed to the right */}
                            {duration !== null && (
                                <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                                    ~{fmtDuration(duration)}
                                </span>
                            )}
                        </li>
                    );
                })}
            </ol>
        </div>
    );
}
