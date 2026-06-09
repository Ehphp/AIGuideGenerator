import type { Guide, Session } from "@/lib/types";
import { GuideHeader } from "./GuideHeader";
import { GuideTableOfContents } from "./GuideTableOfContents";
import { GuidePrerequisites } from "./GuidePrerequisites";
import { GuideProcedure } from "./GuideProcedure";
import { GuideSectionCard } from "./GuideSectionCard";
import { GuideTroubleshooting } from "./GuideTroubleshooting";
import { GuideCallout } from "./GuideCallout";
import { GuideAbout } from "./GuideAbout";
import { GuideEmptyState } from "./GuideEmptyState";

interface GuideDocumentProps {
    guide: Guide | null;
    session: Session;
}

interface SectionProps {
    id: string;
    title: string;
    children: React.ReactNode;
}

function Section({ id, title, children }: SectionProps) {
    return (
        <section id={id} className="scroll-mt-20">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {title}
            </h3>
            {children}
        </section>
    );
}

export function GuideDocument({ guide, session }: GuideDocumentProps) {
    if (!guide) {
        return <GuideEmptyState />;
    }

    const hasTroubleshooting = (guide.troubleshooting?.length ?? 0) > 0;
    const hasPrerequisites =
        guide.prerequisites.length > 0 || guide.tools_or_systems.length > 0;
    const hasWarnings = guide.warnings.length > 0;
    const hasNotes = guide.notes.length > 0;
    const hasSteps = (guide.steps?.length ?? 0) > 0;
    const hasSections = (guide.sections?.length ?? 0) > 0;

    return (
        <div className="flex flex-col gap-0">
            {/* Header */}
            <GuideHeader guide={guide} session={session} />

            {/* Layout: sticky TOC sidebar + main content */}
            <div className="mt-8 flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-12">
                {/* TOC — sticky on large screens */}
                <aside className="shrink-0 lg:sticky lg:top-8 lg:w-52">
                    <GuideTableOfContents guide={guide} />
                </aside>

                {/* Main document content */}
                <div className="min-w-0 flex-1">
                    <div className="flex flex-col gap-10">

                        {/* Overview */}
                        {guide.summary && (
                            <Section id="overview" title="Overview">
                                <p className="text-sm leading-relaxed text-foreground">
                                    {guide.summary}
                                </p>
                            </Section>
                        )}

                        {/* Prerequisites */}
                        {hasPrerequisites && (
                            <Section id="prerequisites" title="Prerequisites">
                                <GuidePrerequisites
                                    prerequisites={guide.prerequisites}
                                    tools={guide.tools_or_systems}
                                />
                            </Section>
                        )}

                        {/* Global warnings */}
                        {hasWarnings && (
                            <Section id="warnings" title="Warnings">
                                <div className="flex flex-col gap-2">
                                    {guide.warnings.map((w, i) => (
                                        <GuideCallout key={i} variant="warning">
                                            {w}
                                        </GuideCallout>
                                    ))}
                                </div>
                            </Section>
                        )}

                        {/* Adaptive sections (non-procedural document types) */}
                        {hasSections && guide.sections!.map((sec, i) => (
                            <Section
                                key={`section-${i}`}
                                id={`section-${i}`}
                                title={sec.title}
                            >
                                <GuideSectionCard section={sec} />
                            </Section>
                        ))}

                        {/* Procedure — only shown when steps are present */}
                        {hasSteps && (
                            <Section id="procedure" title="Procedure">
                                <GuideProcedure steps={guide.steps} />
                            </Section>
                        )}

                        {/* Troubleshooting */}
                        {hasTroubleshooting && (
                            <Section id="troubleshooting" title="Troubleshooting">
                                <GuideTroubleshooting
                                    items={guide.troubleshooting!}
                                />
                            </Section>
                        )}

                        {/* Global notes */}
                        {hasNotes && (
                            <Section id="notes" title="Notes">
                                <div className="flex flex-col gap-2">
                                    {guide.notes.map((n, i) => (
                                        <GuideCallout key={i} variant="note" title="Note">
                                            {n}
                                        </GuideCallout>
                                    ))}
                                </div>
                            </Section>
                        )}

                        {/* About */}
                        <Section id="about" title="About this guide">
                            <GuideAbout guide={guide} session={session} />
                        </Section>

                    </div>
                </div>
            </div>
        </div>
    );
}

