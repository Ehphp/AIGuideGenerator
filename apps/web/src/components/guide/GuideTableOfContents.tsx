import type { Guide } from "@/lib/types";

interface GuideTableOfContentsProps {
    guide: Guide;
}

const SECTION_LABELS: { id: string; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "prerequisites", label: "Prerequisites" },
    { id: "warnings", label: "Warnings" },
    { id: "procedure", label: "Procedure" },
    { id: "troubleshooting", label: "Troubleshooting" },
    { id: "notes", label: "Notes" },
    { id: "about", label: "About" },
];

function isVisible(id: string, guide: Guide): boolean {
    switch (id) {
        case "overview":
            return !!guide.summary;
        case "prerequisites":
            return guide.prerequisites.length > 0 || guide.tools_or_systems.length > 0;
        case "warnings":
            return guide.warnings.length > 0;
        case "procedure":
            return guide.steps.length > 0;
        case "troubleshooting":
            return (guide.troubleshooting?.length ?? 0) > 0;
        case "notes":
            return guide.notes.length > 0;
        case "about":
            return true; // always show about
        default:
            return true;
    }
}

export function GuideTableOfContents({ guide }: GuideTableOfContentsProps) {
    const visibleSections = SECTION_LABELS.filter((s) =>
        isVisible(s.id, guide)
    );

    return (
        <nav aria-label="Table of contents">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Contents
            </div>
            <ol className="flex flex-col gap-1">
                {visibleSections.map((s) => (
                    <li key={s.id}>
                        <a
                            href={`#${s.id}`}
                            className="block rounded px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                            {s.label}
                        </a>
                    </li>
                ))}

                {/* Step links under Procedure */}
                {guide.steps.length > 0 && (
                    <li>
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
            </ol>
        </nav>
    );
}
