import type { Guide, Session } from "@/lib/types";
import { GuideMetadataBar } from "./GuideMetadataBar";

const STATUS_STYLES: Record<string, string> = {
    created: "bg-muted text-muted-foreground",
    uploaded: "bg-blue-100 text-blue-800",
    processing: "bg-amber-100 text-amber-800",
    ready: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
};

interface GuideHeaderProps {
    guide: Guide;
    session: Session;
}

export function GuideHeader({ guide, session }: GuideHeaderProps) {
    return (
        <header className="flex flex-col gap-3 border-b border-border pb-6">
            <div className="flex flex-wrap items-center gap-2">
                <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[session.status] ?? "bg-muted"}`}
                >
                    {session.status}
                </span>
                {guide.schema_version && (
                    <span className="rounded border border-border px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                        v{guide.schema_version}
                    </span>
                )}
            </div>

            <h2 className="text-2xl font-bold tracking-tight text-foreground">
                {guide.title}
            </h2>

            {guide.summary && (
                <p className="max-w-2xl text-base leading-relaxed text-muted-foreground">
                    {guide.summary}
                </p>
            )}

            <GuideMetadataBar guide={guide} session={session} />
        </header>
    );
}
