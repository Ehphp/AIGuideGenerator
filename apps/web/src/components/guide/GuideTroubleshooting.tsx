import type { GuideTroubleshooting as Ts } from "@/lib/types";

interface GuideTroubleshootingProps {
    items: Ts[];
}

export function GuideTroubleshooting({ items }: GuideTroubleshootingProps) {
    if (items.length === 0) return null;

    return (
        <div className="flex flex-col gap-3">
            {items.map((item, i) => (
                <details
                    key={i}
                    className="group rounded border border-border"
                >
                    <summary className="flex cursor-pointer select-none items-center gap-2 px-4 py-3 text-sm font-medium text-foreground hover:bg-muted">
                        <span
                            className="shrink-0 text-amber-600 transition-transform duration-150 group-open:rotate-90"
                            aria-hidden="true"
                        >
                            ▶
                        </span>
                        {item.symptom}
                    </summary>
                    <div className="border-t border-border px-4 py-3">
                        <div className="mb-2">
                            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                Likely cause
                            </span>
                            <p className="mt-1 text-sm text-foreground">
                                {item.likely_cause}
                            </p>
                        </div>
                        <div>
                            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                Resolution
                            </span>
                            <p className="mt-1 text-sm text-foreground">
                                {item.resolution}
                            </p>
                        </div>
                    </div>
                </details>
            ))}
        </div>
    );
}
