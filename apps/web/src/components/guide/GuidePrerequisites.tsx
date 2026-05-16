import type { Guide } from "@/lib/types";

interface GuidePrerequisitesProps {
    prerequisites: Guide["prerequisites"];
    tools: Guide["tools_or_systems"];
}

export function GuidePrerequisites({
    prerequisites,
    tools,
}: GuidePrerequisitesProps) {
    const hasPrereqs = prerequisites.length > 0;
    const hasTools = tools.length > 0;

    if (!hasPrereqs && !hasTools) return null;

    return (
        <div className="grid gap-4 sm:grid-cols-2">
            {hasPrereqs && (
                <div>
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Prerequisites
                    </h4>
                    <ul className="flex flex-col gap-1">
                        {prerequisites.map((item, i) => (
                            <li
                                key={i}
                                className="flex items-start gap-2 text-sm text-foreground"
                            >
                                <span
                                    className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                                    aria-hidden="true"
                                />
                                {item}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {hasTools && (
                <div>
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Tools &amp; Systems
                    </h4>
                    <ul className="flex flex-col gap-1">
                        {tools.map((item, i) => (
                            <li
                                key={i}
                                className="flex items-start gap-2 text-sm text-foreground"
                            >
                                <span
                                    className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                                    aria-hidden="true"
                                />
                                {item}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}
