interface ConfidenceChipProps {
    value: number; // 0.0 – 1.0
}

export function ConfidenceChip({ value }: ConfidenceChipProps) {
    const pct = Math.round(value * 100);
    const color =
        value >= 0.75
            ? "bg-green-50 text-green-700 border-green-200"
            : value >= 0.5
              ? "bg-amber-50 text-amber-700 border-amber-200"
              : "bg-red-50 text-red-700 border-red-200";

    return (
        <span
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium ${color}`}
            title="AI confidence for this step"
        >
            {pct}% confidence
        </span>
    );
}
