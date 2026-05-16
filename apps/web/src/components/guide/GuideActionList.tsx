import type { GuideAction } from "@/lib/types";

interface GuideActionListProps {
    actions: GuideAction[];
}

export function GuideActionList({ actions }: GuideActionListProps) {
    if (actions.length === 0) return null;

    return (
        <div className="mt-3">
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Actions
            </div>
            <ul className="flex flex-col gap-1.5">
                {actions.map((a, i) => (
                    <li
                        key={i}
                        className="flex flex-wrap items-baseline gap-2 text-sm"
                    >
                        <span className="shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs font-semibold uppercase tracking-wide text-foreground">
                            {a.verb}
                        </span>
                        <span className="font-medium text-foreground">{a.target}</span>
                        {a.value && (
                            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs text-muted-foreground">
                                {a.value}
                            </code>
                        )}
                    </li>
                ))}
            </ul>
        </div>
    );
}
