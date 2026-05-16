import type { Guide, GuideStep, GuideTroubleshooting } from "@/lib/types";
import { EditField } from "./EditField";
import { EditStepCard } from "./EditStepCard";
import { EditStringList } from "./EditStringList";

interface GuideEditorFormProps {
    draft: Guide;
    onChange: (guide: Guide) => void;
}

function renumberSteps(steps: GuideStep[]): GuideStep[] {
    return steps.map((step, idx) => ({ ...step, order: idx + 1 }));
}

function newStep(order: number): GuideStep {
    const suffix = `${Date.now()}-${Math.floor(Math.random() * 10000)}`;
    return {
        id: `step-edit-${suffix}`,
        order,
        title: "",
        description: "",
        actions: [],
        evidence: {
            frame_keys: [],
            transcript_excerpt: "",
            t_start: null,
            t_end: null,
        },
        warnings: [],
        notes: [],
        confidence: 1,
    };
}

function newTroubleshooting(): GuideTroubleshooting {
    return {
        symptom: "",
        likely_cause: "",
        resolution: "",
    };
}

export function GuideEditorForm({ draft, onChange }: GuideEditorFormProps) {
    const troubleshooting = draft.troubleshooting ?? [];

    return (
        <div className="flex flex-col gap-4">
            <div className="rounded border border-border p-4">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    Document Header
                </h3>
                <div className="grid gap-3">
                    <EditField
                        label="Title"
                        value={draft.title}
                        onChange={(title) => onChange({ ...draft, title })}
                        required
                    />
                    <EditField
                        label="Summary"
                        value={draft.summary}
                        onChange={(summary) => onChange({ ...draft, summary })}
                        multiline
                        rows={3}
                    />
                    <div className="max-w-[220px]">
                        <EditField
                            label="Estimated duration (minutes)"
                            value={
                                draft.estimated_duration_minutes == null
                                    ? ""
                                    : String(draft.estimated_duration_minutes)
                            }
                            onChange={(raw) => {
                                const value = raw.trim();
                                onChange({
                                    ...draft,
                                    estimated_duration_minutes:
                                        value === "" ? null : Number(value),
                                });
                            }}
                            type="number"
                        />
                    </div>
                </div>
            </div>

            <div className="rounded border border-border p-4">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    Prerequisites
                </h3>
                <div className="grid gap-4 sm:grid-cols-2">
                    <EditStringList
                        label="Prerequisites"
                        items={draft.prerequisites}
                        onChange={(prerequisites) =>
                            onChange({ ...draft, prerequisites })
                        }
                        placeholder="Add prerequisite"
                        addLabel="Add"
                    />
                    <EditStringList
                        label="Tools & Systems"
                        items={draft.tools_or_systems}
                        onChange={(tools_or_systems) =>
                            onChange({ ...draft, tools_or_systems })
                        }
                        placeholder="Add tool or system"
                        addLabel="Add"
                    />
                </div>
            </div>

            <div className="rounded border border-border p-4">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    Global Warnings
                </h3>
                <EditStringList
                    items={draft.warnings}
                    onChange={(warnings) => onChange({ ...draft, warnings })}
                    placeholder="Add warning"
                    addLabel="Add warning"
                />
            </div>

            <div className="rounded border border-border p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                        Procedure Steps
                    </h3>
                    <button
                        type="button"
                        onClick={() => {
                            const steps = renumberSteps([
                                ...draft.steps,
                                newStep(draft.steps.length + 1),
                            ]);
                            onChange({ ...draft, steps });
                        }}
                        className="rounded border border-border px-3 py-1.5 text-xs hover:bg-muted"
                    >
                        + Add step
                    </button>
                </div>

                <div className="flex flex-col gap-3">
                    {draft.steps.map((step, idx) => (
                        <EditStepCard
                            key={step.id}
                            step={step}
                            index={idx}
                            isFirst={idx === 0}
                            isLast={idx === draft.steps.length - 1}
                            onMove={(direction) => {
                                const next = [...draft.steps];
                                const target = idx + direction;
                                if (target < 0 || target >= next.length) return;
                                [next[idx], next[target]] = [next[target], next[idx]];
                                onChange({ ...draft, steps: renumberSteps(next) });
                            }}
                            onRemove={() => {
                                const next = draft.steps.filter((_, i) => i !== idx);
                                onChange({ ...draft, steps: renumberSteps(next) });
                            }}
                            onChange={(nextStep) => {
                                const next = [...draft.steps];
                                next[idx] = nextStep;
                                onChange({ ...draft, steps: renumberSteps(next) });
                            }}
                        />
                    ))}
                </div>
            </div>

            <div className="rounded border border-border p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                        Troubleshooting
                    </h3>
                    <button
                        type="button"
                        onClick={() =>
                            onChange({
                                ...draft,
                                troubleshooting: [
                                    ...troubleshooting,
                                    newTroubleshooting(),
                                ],
                            })
                        }
                        className="rounded border border-border px-3 py-1.5 text-xs hover:bg-muted"
                    >
                        + Add item
                    </button>
                </div>

                <div className="flex flex-col gap-3">
                    {troubleshooting.map((item, idx) => (
                        <div key={idx} className="rounded border border-border p-3">
                            <div className="mb-2 flex justify-end">
                                <button
                                    type="button"
                                    onClick={() =>
                                        onChange({
                                            ...draft,
                                            troubleshooting: troubleshooting.filter(
                                                (_, i) => i !== idx
                                            ),
                                        })
                                    }
                                    className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                                >
                                    Remove
                                </button>
                            </div>
                            <div className="grid gap-2">
                                <EditField
                                    label="Symptom"
                                    value={item.symptom}
                                    onChange={(symptom) => {
                                        const next = [...troubleshooting];
                                        next[idx] = { ...next[idx], symptom };
                                        onChange({ ...draft, troubleshooting: next });
                                    }}
                                />
                                <EditField
                                    label="Likely Cause"
                                    value={item.likely_cause}
                                    onChange={(likely_cause) => {
                                        const next = [...troubleshooting];
                                        next[idx] = {
                                            ...next[idx],
                                            likely_cause,
                                        };
                                        onChange({ ...draft, troubleshooting: next });
                                    }}
                                    multiline
                                    rows={2}
                                />
                                <EditField
                                    label="Resolution"
                                    value={item.resolution}
                                    onChange={(resolution) => {
                                        const next = [...troubleshooting];
                                        next[idx] = { ...next[idx], resolution };
                                        onChange({ ...draft, troubleshooting: next });
                                    }}
                                    multiline
                                    rows={2}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="rounded border border-border p-4">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    Global Notes
                </h3>
                <EditStringList
                    items={draft.notes}
                    onChange={(notes) => onChange({ ...draft, notes })}
                    placeholder="Add note"
                    addLabel="Add note"
                />
            </div>
        </div>
    );
}
