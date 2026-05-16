import type { GuideStep } from "@/lib/types";
import { EditActionList } from "./EditActionList";
import { EditStringList } from "./EditStringList";

interface EditStepCardProps {
    step: GuideStep;
    index: number;
    isFirst: boolean;
    isLast: boolean;
    onMove: (direction: -1 | 1) => void;
    onRemove: () => void;
    onChange: (step: GuideStep) => void;
}

export function EditStepCard({
    step,
    index,
    isFirst,
    isLast,
    onMove,
    onRemove,
    onChange,
}: EditStepCardProps) {
    return (
        <div className="rounded border border-border">
            <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/40 p-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
                    {index + 1}
                </span>
                <input
                    value={step.title}
                    onChange={(e) => onChange({ ...step, title: e.target.value })}
                    className="min-w-[220px] flex-1 rounded border border-input bg-background px-2 py-1.5 text-sm font-medium outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    placeholder="Step title"
                />
                <button
                    type="button"
                    onClick={() => onMove(-1)}
                    disabled={isFirst}
                    className="rounded border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-40"
                    title="Move up"
                >
                    ↑
                </button>
                <button
                    type="button"
                    onClick={() => onMove(1)}
                    disabled={isLast}
                    className="rounded border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-40"
                    title="Move down"
                >
                    ↓
                </button>
                <button
                    type="button"
                    onClick={onRemove}
                    className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                >
                    Delete
                </button>
            </div>

            <div className="flex flex-col gap-3 p-3">
                <label className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Description
                    </span>
                    <textarea
                        value={step.description}
                        rows={3}
                        onChange={(e) => onChange({ ...step, description: e.target.value })}
                        className="rounded border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    />
                </label>

                <EditActionList
                    actions={step.actions}
                    onChange={(actions) => onChange({ ...step, actions })}
                />

                <EditStringList
                    label="Warnings"
                    items={step.warnings}
                    onChange={(warnings) => onChange({ ...step, warnings })}
                    placeholder="Add warning"
                    addLabel="Add warning"
                />

                <EditStringList
                    label="Notes"
                    items={step.notes}
                    onChange={(notes) => onChange({ ...step, notes })}
                    placeholder="Add note"
                    addLabel="Add note"
                />
            </div>
        </div>
    );
}
