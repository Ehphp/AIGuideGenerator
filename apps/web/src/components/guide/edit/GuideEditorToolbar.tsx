interface GuideEditorToolbarProps {
    onSave: () => void;
    onCancel: () => void;
    saving: boolean;
    saveError: string | null;
}

export function GuideEditorToolbar({
    onSave,
    onCancel,
    saving,
    saveError,
}: GuideEditorToolbarProps) {
    return (
        <div className="sticky top-0 z-10 mb-4 rounded border border-border bg-background/95 p-3 backdrop-blur">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold">Edit guide</div>
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={onCancel}
                        disabled={saving}
                        className="rounded border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={onSave}
                        disabled={saving}
                        className="rounded border border-primary bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        {saving ? "Saving..." : "Save changes"}
                    </button>
                </div>
            </div>
            {saveError && (
                <div className="mt-2 rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800">
                    {saveError}
                </div>
            )}
        </div>
    );
}
