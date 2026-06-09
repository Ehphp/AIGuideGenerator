import type { Guide } from "@/lib/types";

interface GuideTableOfContentsProps {
    guide: Guide;
}

const FIXED_SECTION_LABELS: { id: string; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "prerequisites", label: "Prerequisites" },
    { id: "warnings", label: "Warnings" },
    // "procedure" is added dynamically below when steps are present
    { id: "troubleshooting", label: "Troubleshooting" },
    { id: "notes", label: "Notes" },
    { id: "about", label: "About" },
];

function isFixedVisible(id: string, guide: Guide): boolean {
    switch (id) {
        case "overview":
            return !!guide.summary;
        case "prerequisites":
            return guide.prerequisites.length > 0 || guide.tools_or_systems.length > 0;
        case "warnings":
            return guide.warnings.length > 0;
        case "troubleshooting":
            return (guide.troubleshooting?.length ?? 0) > 0;
        case "notes":
            return guide.notes.length > 0;
        case "about":
            return true;
        default:
            return true;
    }
}

export function GuideTableOfContents({ guide }: GuideTableOfContentsProps) {
    const hasSteps = (guide.steps?.length ?? 0) > 0;
    const hasSections = (guide.sections?.length ?? 0) > 0;

    const visibleFixed = FIXED_SECTION_LABELS.filter((s) =>
        isFixedVisible(s.id, guide)
    );

    return (
        <nav aria-label="Table of contents">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Contents
            </div>
            <ol className="flex flex-col gap-1">
                {visibleFixed.slice(0, 3).map((s) => (
                    <li key={s.id}>
                        <a
                            href={`#${s.id}`}
                            className="block rounded px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                            {s.label}
                        </a>
                    </li>
                ))}

                {/* Adaptive sections (non-procedural document types) */}
                {hasSections && guide.sections!.map((sec, i) => (
                    <li key={`section-${i}`}>
                        <a
                            href={`#section-${i}`}
                            className="block rounded px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                            {sec.title}
                        </a>
                    </li>
                ))}

                {/* Procedure section — only when steps present */}
                {hasSteps && (
                    <li>
                        <a
                            href="#procedure"
                            className="block rounded px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                            Procedure
                        </a>
                        {/* Step links under Procedure */}
                        <ol className="ml-4 mt-0.5 flex flex-col gap-0.5 border-l border-border pl-2">
                            {guide.steps.map((step, i) => (
                                <li key={step.id}>
                                    <a
                                        href={`#step-${step.id}`}
                                        className="block rounded px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                                    >
                                        {i + 1}. {step.title}
                                    </a>
                                </li>
                            ))}
                        </ol>
                    </li>
                )}

                {visibleFixed.slice(3).map((s) => (
                    <li key={s.id}>
                        <a
                            href={`#${s.id}`}
                            className="block rounded px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                            {s.label}
                        </a>
                    </li>
                ))}
            </ol>
        </nav>
    );
}

