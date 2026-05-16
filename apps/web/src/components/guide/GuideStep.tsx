import type { GuideStep } from "@/lib/types";
import { ConfidenceChip } from "./ConfidenceChip";
import { GuideActionList } from "./GuideActionList";
import { GuideCallout } from "./GuideCallout";
import { GuideFrameViewer } from "./GuideFrameViewer";

interface GuideStepProps {
    step: GuideStep;
    index: number;
}

function formatTimestamp(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
}

export function GuideStep({ step, index }: GuideStepProps) {
    const anchor = `step-${step.id}`;
    const hasTimestamps =
        step.evidence.t_start != null || step.evidence.t_end != null;
    const frameKeys = step.evidence.frame_keys ?? [];

    return (
        <section
            id={anchor}
            className="scroll-mt-20 border-t border-border pt-6 first:border-t-0 first:pt-0"
        >
            {/* Step heading row */}
            <div className="flex flex-wrap items-start gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
                    {index + 1}
                </span>
                <h3 className="flex-1 text-base font-semibold leading-7 text-foreground">
                    {step.title}
                </h3>
                {step.confidence != null && (
                    <ConfidenceChip value={step.confidence} />
                )}
            </div>

            {/* Low-confidence automatic callout */}
            {step.confidence < 0.4 && (
                <div className="mt-3">
                    <GuideCallout variant="warning">
                        This step has low AI confidence. Verify the instructions manually
                        before executing.
                    </GuideCallout>
                </div>
            )}

            {/* Description */}
            <p className="mt-3 text-sm leading-relaxed text-foreground">
                {step.description}
            </p>

            {/* Actions */}
            <GuideActionList actions={step.actions} />

            {/* Warnings callout */}
            {step.warnings.length > 0 && (
                <div className="mt-3 flex flex-col gap-2">
                    {step.warnings.map((w, i) => (
                        <GuideCallout key={i} variant="warning">
                            {w}
                        </GuideCallout>
                    ))}
                </div>
            )}

            {/* Notes callout */}
            {step.notes.length > 0 && (
                <div className="mt-3 flex flex-col gap-2">
                    {step.notes.map((n, i) => (
                        <GuideCallout key={i} variant="note" title="Note">
                            {n}
                        </GuideCallout>
                    ))}
                </div>
            )}

            {/* Evidence: timestamps + screenshots */}
            {(hasTimestamps || frameKeys.length > 0) && (
                <div className="mt-3 flex flex-wrap items-start gap-3">
                    {hasTimestamps && (
                        <span className="flex items-center gap-1 rounded border border-border bg-muted px-2 py-1 text-xs text-muted-foreground">
                            🎬{" "}
                            {step.evidence.t_start != null
                                ? formatTimestamp(step.evidence.t_start)
                                : "—"}
                            {" → "}
                            {step.evidence.t_end != null
                                ? formatTimestamp(step.evidence.t_end)
                                : "—"}
                        </span>
                    )}
                    <GuideFrameViewer frameKeys={frameKeys} />
                </div>
            )}

            {/* Transcript excerpt — collapsible */}
            {step.evidence.transcript_excerpt && (
                <details className="mt-3">
                    <summary className="cursor-pointer select-none text-xs text-muted-foreground hover:text-foreground">
                        Show transcript excerpt
                    </summary>
                    <blockquote className="mt-1.5 border-l-2 border-border pl-3 text-xs italic text-muted-foreground">
                        "{step.evidence.transcript_excerpt}"
                    </blockquote>
                </details>
            )}
        </section>
    );
}
