"use client";

import { useState } from "react";
import { getGuideExportUrl, updateGuideContent } from "@/lib/apiClient";
import type { Guide, Session } from "@/lib/types";
import { GuideDocument } from "./GuideDocument";
import { GuideEditorForm } from "./edit/GuideEditorForm";
import { GuideEditorToolbar } from "./edit/GuideEditorToolbar";

interface GuideEditorShellProps {
    guide: Guide | null;
    session: Session;
    onGuideUpdated: (session: Session) => void;
}

export function GuideEditorShell({
    guide,
    session,
    onGuideUpdated,
}: GuideEditorShellProps) {
    const [editMode, setEditMode] = useState(false);
    const [draft, setDraft] = useState<Guide | null>(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);

    const startEdit = () => {
        if (!guide) return;
        const cloned = JSON.parse(JSON.stringify(guide)) as Guide;
        setDraft(cloned);
        setSaveError(null);
        setEditMode(true);
    };

    const cancelEdit = () => {
        setEditMode(false);
        setDraft(null);
        setSaveError(null);
        setSaving(false);
    };

    const saveEdit = async () => {
        if (!draft) return;
        setSaving(true);
        setSaveError(null);
        try {
            const updated = await updateGuideContent(session.id, draft);
            onGuideUpdated(updated);
            setEditMode(false);
            setDraft(null);
        } catch (e) {
            setSaveError(e instanceof Error ? e.message : String(e));
        } finally {
            setSaving(false);
        }
    };

    if (editMode && draft) {
        return (
            <div className="mt-2">
                <GuideEditorToolbar
                    onSave={() => void saveEdit()}
                    onCancel={cancelEdit}
                    saving={saving}
                    saveError={saveError}
                />
                <GuideEditorForm draft={draft} onChange={setDraft} />
            </div>
        );
    }

    return (
        <div className="mt-2 flex flex-col gap-4">
            {session.status === "ready" && guide && (
                <div className="flex justify-end gap-2">
                    <a
                        href={getGuideExportUrl(session.id)}
                        download
                        className="rounded border border-border px-3 py-2 text-sm hover:bg-muted"
                    >
                        ↓ Download DOCX
                    </a>
                    <button
                        type="button"
                        onClick={startEdit}
                        className="rounded border border-border px-3 py-2 text-sm hover:bg-muted"
                    >
                        ✎ Edit guide
                    </button>
                </div>
            )}
            <GuideDocument guide={guide} session={session} />
        </div>
    );
}
