"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listSessions, deleteSession } from "@/lib/apiClient";
import type { Session } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
    created: "bg-muted text-muted-foreground",
    uploaded: "bg-blue-100 text-blue-800",
    processing: "bg-amber-100 text-amber-800",
    ready: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
};

export default function HomePage() {
    const [sessions, setSessions] = useState<Session[] | null>(null);
    const [err, setErr] = useState<string | null>(null);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        let cancelled = false;
        setErr(null);
        listSessions()
            .then((s) => {
                if (!cancelled) setSessions(s);
            })
            .catch((e) => {
                if (!cancelled) setErr(String(e?.message ?? e));
            });
        return () => {
            cancelled = true;
        };
    }, [reloadKey]);

    const handleDelete = async (id: string) => {
        if (!confirm("Delete this session and its media?")) return;
        try {
            await deleteSession(id);
            setReloadKey((k) => k + 1);
        } catch (e) {
            alert(`Delete failed: ${e instanceof Error ? e.message : e}`);
        }
    };

    return (
        <main className="container mx-auto flex max-w-3xl flex-col gap-8 px-4 py-12">
            <header className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Guide Generator</h1>
                    <p className="text-sm text-muted-foreground">
                        Record or upload a procedure, get a structured guide.
                    </p>
                </div>
                <Link
                    href="/sessions/new"
                    className="rounded bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90"
                >
                    New session
                </Link>
            </header>

            <section>
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                    Sessions
                </h2>
                {err && (
                    <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
                        {err}
                    </div>
                )}
                {sessions === null && !err && (
                    <div className="text-sm text-muted-foreground">Loading…</div>
                )}
                {sessions && sessions.length === 0 && (
                    <div className="rounded border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                        No sessions yet. Click <span className="font-medium">New session</span>{" "}
                        to start.
                    </div>
                )}
                {sessions && sessions.length > 0 && (
                    <ul className="divide-y divide-border rounded border border-border">
                        {sessions.map((s) => (
                            <li key={s.id} className="flex items-center gap-3 p-3">
                                <Link
                                    href={`/sessions/${s.id}`}
                                    className="flex-1 min-w-0 hover:underline"
                                >
                                    <div className="truncate text-sm font-medium">
                                        {s.title || "Untitled session"}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                        {new Date(s.created_at).toLocaleString()} ·{" "}
                                        {s.source_type ?? "—"}
                                    </div>
                                </Link>
                                <span
                                    className={`rounded-full px-2 py-0.5 text-xs ${STATUS_STYLES[s.status] ?? "bg-muted"
                                        }`}
                                >
                                    {s.status}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => void handleDelete(s.id)}
                                    className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                                >
                                    Delete
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
        </main>
    );
}
