import type { GuideSection } from "@/lib/types";
import { GuideCallout } from "./GuideCallout";
import { GuideProcedure } from "./GuideProcedure";

interface GuideSectionCardProps {
    section: GuideSection;
}

/**
 * Renders a single adaptive section produced by non-procedural document types
 * (technical, conceptual, diagnostic, demo, mixed).
 *
 * The `kind` field drives minor visual hints (e.g. a "Technical" badge) but
 * the structure is intentionally generic: prose content, bullet items, inline
 * steps (if the section has a procedural sub-path), warnings, and notes.
 */
export function GuideSectionCard({ section }: GuideSectionCardProps) {
    const hasContent = !!section.content?.trim();
    const hasItems = (section.items?.length ?? 0) > 0;
    const hasSteps = (section.steps?.length ?? 0) > 0;
    const hasWarnings = (section.warnings?.length ?? 0) > 0;
    const hasNotes = (section.notes?.length ?? 0) > 0;

    return (
        <div className="flex flex-col gap-3">
            {/* Section kind badge — subtle label for non-generic kinds */}
            {section.kind && section.kind !== "notes" && section.kind !== "overview" && (
                <span className="inline-block w-fit rounded bg-muted px-2 py-0.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    {section.kind}
                </span>
            )}

            {/* Prose content */}
            {hasContent && (
                <p className="text-sm leading-relaxed text-foreground whitespace-pre-wrap">
                    {section.content}
                </p>
            )}

            {/* Bullet items */}
            {hasItems && (
                <ul className="flex flex-col gap-1 pl-4">
                    {section.items!.map((item, i) => (
                        <li
                            key={i}
                            className="list-disc text-sm leading-relaxed text-foreground"
                        >
                            {item}
                        </li>
                    ))}
                </ul>
            )}

            {/* Inline procedural steps (e.g. resolution path in a diagnostic section) */}
            {hasSteps && (
                <div className="mt-1">
                    <GuideProcedure steps={section.steps!} />
                </div>
            )}

            {/* Section-level warnings */}
            {hasWarnings && (
                <div className="flex flex-col gap-2">
                    {section.warnings!.map((w, i) => (
                        <GuideCallout key={i} variant="warning">
                            {w}
                        </GuideCallout>
                    ))}
                </div>
            )}

            {/* Section-level notes */}
            {hasNotes && (
                <div className="flex flex-col gap-2">
                    {section.notes!.map((n, i) => (
                        <GuideCallout key={i} variant="note" title="Note">
                            {n}
                        </GuideCallout>
                    ))}
                </div>
            )}
        </div>
    );
}
