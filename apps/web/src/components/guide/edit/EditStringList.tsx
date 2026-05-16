"use client";

import { useState } from "react";

interface EditStringListProps {
    label?: string;
    items: string[];
    onChange: (items: string[]) => void;
    placeholder?: string;
    addLabel?: string;
}

export function EditStringList({
    label,
    items,
    onChange,
    placeholder = "Add item",
    addLabel = "Add",
}: EditStringListProps) {
    const [draft, setDraft] = useState("");

    return (
        <div className="flex flex-col gap-2">
            {label && (
                <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {label}
                </div>
            )}

            {items.map((item, i) => (
                <div key={i} className="flex items-center gap-2">
                    <input
                        value={item}
                        onChange={(e) => {
                            const next = [...items];
                            next[i] = e.target.value;
                            onChange(next);
                        }}
                        className="flex-1 rounded border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    />
                    <button
                        type="button"
                        onClick={() => onChange(items.filter((_, idx) => idx !== i))}
                        className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                        aria-label="Remove item"
                    >
                        ✕
                    </button>
                </div>
            ))}

            <div className="flex items-center gap-2">
                <input
                    value={draft}
                    placeholder={placeholder}
                    onChange={(e) => setDraft(e.target.value)}
                    className="flex-1 rounded border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                />
                <button
                    type="button"
                    onClick={() => {
                        const value = draft.trim();
                        if (!value) return;
                        onChange([...items, value]);
                        setDraft("");
                    }}
                    className="rounded border border-border px-3 py-2 text-xs hover:bg-muted"
                >
                    {addLabel}
                </button>
            </div>
        </div>
    );
}
