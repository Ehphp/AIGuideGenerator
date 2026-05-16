import type { Guide, Session } from "@/lib/types";

interface GuideMetadataBarProps {
    guide: Guide;
    session: Session;
}

function formatDuration(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function formatDate(iso: string): string {
    try {
        return new Date(iso).toLocaleString(undefined, {
            dateStyle: "medium",
            timeStyle: "short",
        });
    } catch {
        return iso;
    }
}

function averageConfidence(steps: Guide["steps"]): number | null {
    if (steps.length === 0) return null;
    const avg =
        steps.reduce((sum, s) => sum + (s.confidence ?? 0.5), 0) / steps.length;
    return avg;
}

export function GuideMetadataBar({ guide, session }: GuideMetadataBarProps) {
    const meta = guide.metadata;
    const sourceDuration =
        meta?.source_duration_sec ?? session.media_duration_sec;
    const generatedAt = meta?.generated_at;
    const generatedBy = meta?.generated_by;
    const avgConf = averageConfidence(guide.steps);

    const chips: { icon: string; label: string; value: string }[] = [];

    if (guide.estimated_duration_minutes != null) {
        chips.push({
            icon: "⏱",
            label: "Estimated time",
            value: `~${guide.estimated_duration_minutes} min`,
        });
    }

    if (sourceDuration != null) {
        chips.push({
            icon: "🎬",
            label: "Recording duration",
            value: formatDuration(sourceDuration),
        });
    }

    if (generatedAt) {
        chips.push({
            icon: "📅",
            label: "Generated",
            value: formatDate(generatedAt),
        });
    }

    if (session.guide_edited_at) {
        chips.push({
            icon: "✎",
            label: "Last edited",
            value: formatDate(session.guide_edited_at),
        });
    }

    if (generatedBy) {
        chips.push({
            icon: "🤖",
            label: "Model",
            value: generatedBy,
        });
    }

    if (avgConf != null) {
        chips.push({
            icon: "✦",
            label: "Avg. confidence",
            value: `${Math.round(avgConf * 100)}%`,
        });
    }

    if (chips.length === 0) return null;

    return (
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
            {chips.map((chip) => (
                <span
                    key={chip.label}
                    className="flex items-center gap-1"
                    title={chip.label}
                >
                    <span aria-hidden="true">{chip.icon}</span>
                    {chip.value}
                </span>
            ))}
        </div>
    );
}
