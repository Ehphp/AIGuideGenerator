"use client";

import { useState } from "react";
import type { GuideAction } from "@/lib/types";

interface EditActionListProps {
    actions: GuideAction[];
    onChange: (actions: GuideAction[]) => void;
}

export function EditActionList({ actions, onChange }: EditActionListProps) {
    const [verb, setVerb] = useState("");
    const [target, setTarget] = useState("");
    const [value, setValue] = useState("");

    return (
        <div className="flex flex-col gap-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Actions
            </div>
            {actions.map((action, i) => (
                <div key={i} className="grid grid-cols-12 gap-2">
                    <input
                        value={action.verb}
                        onChange={(e) => {
                            const next = [...actions];
                            next[i] = { ...next[i], verb: e.target.value };
                            onChange(next);
                        }}
                        className="col-span-3 rounded border border-input bg-background px-2 py-2 font-mono text-xs uppercase outline-none ring-offset-background focus:ring-2 focus:ring-ring sm:col-span-2"
                        placeholder="verb"
                    />
                    <input
                        value={action.target}
                        onChange={(e) => {
                            const next = [...actions];
                            next[i] = { ...next[i], target: e.target.value };
                            onChange(next);
                        }}
                        className="col-span-6 rounded border border-input bg-background px-2 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                        placeholder="target"
                    />
                    <input
                        value={action.value ?? ""}
                        onChange={(e) => {
                            const next = [...actions];
                            const v = e.target.value;
                            next[i] = { ...next[i], value: v ? v : null };
                            onChange(next);
                        }}
                        className="col-span-2 rounded border border-input bg-background px-2 py-2 text-xs font-mono outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                        placeholder="value"
                    />
                    <button
                        type="button"
                        onClick={() => onChange(actions.filter((_, idx) => idx !== i))}
                        className="col-span-1 rounded border border-red-300 px-1 text-xs text-red-700 hover:bg-red-50"
                        aria-label="Remove action"
                    >
                        ✕
                    </button>
                </div>
            ))}

            <div className="grid grid-cols-12 gap-2 rounded border border-dashed border-border p-2">
                <input
                    value={verb}
                    onChange={(e) => setVerb(e.target.value)}
                    className="col-span-3 rounded border border-input bg-background px-2 py-2 font-mono text-xs uppercase outline-none ring-offset-background focus:ring-2 focus:ring-ring sm:col-span-2"
                    placeholder="click"
                />
                <input
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                    className="col-span-6 rounded border border-input bg-background px-2 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    placeholder="target"
                />
                <input
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    className="col-span-2 rounded border border-input bg-background px-2 py-2 text-xs font-mono outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    placeholder="value"
                />
                <button
                    type="button"
                    onClick={() => {
                        const v = verb.trim();
                        const t = target.trim();
                        if (!v || !t) return;
                        onChange([
                            ...actions,
                            { verb: v, target: t, value: value.trim() || null },
                        ]);
                        setVerb("");
                        setTarget("");
                        setValue("");
                    }}
                    className="col-span-1 rounded border border-border px-1 text-xs hover:bg-muted"
                >
                    +
                </button>
            </div>
        </div>
    );
}
