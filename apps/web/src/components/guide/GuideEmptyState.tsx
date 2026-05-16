export function GuideEmptyState() {
    return (
        <div className="flex flex-col items-center gap-3 rounded border border-border bg-muted px-8 py-12 text-center">
            <span className="text-3xl" aria-hidden="true">
                📄
            </span>
            <p className="text-sm font-medium text-foreground">
                Guide not available
            </p>
            <p className="max-w-xs text-xs text-muted-foreground">
                Processing completed but no guide was generated. Try re-running the
                pipeline.
            </p>
        </div>
    );
}
