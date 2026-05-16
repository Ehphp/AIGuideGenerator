interface GuideCalloutProps {
    variant: "info" | "warning" | "danger" | "note";
    title?: string;
    children: React.ReactNode;
}

const STYLES = {
    info: {
        container: "border-blue-200 bg-blue-50",
        title: "text-blue-900",
        body: "text-blue-800",
        icon: "ℹ",
    },
    warning: {
        container: "border-amber-300 bg-amber-50",
        title: "text-amber-900",
        body: "text-amber-800",
        icon: "⚠",
    },
    danger: {
        container: "border-red-300 bg-red-50",
        title: "text-red-900",
        body: "text-red-800",
        icon: "✖",
    },
    note: {
        container: "border-border bg-muted",
        title: "text-foreground",
        body: "text-muted-foreground",
        icon: "✎",
    },
};

export function GuideCallout({ variant, title, children }: GuideCalloutProps) {
    const s = STYLES[variant];
    return (
        <div className={`rounded border p-3 text-sm ${s.container}`}>
            {title && (
                <div className={`mb-1 flex items-center gap-1.5 font-medium ${s.title}`}>
                    <span aria-hidden="true">{s.icon}</span>
                    {title}
                </div>
            )}
            {!title && (
                <span
                    className={`mr-1.5 font-medium ${s.title}`}
                    aria-hidden="true"
                >
                    {s.icon}{" "}
                </span>
            )}
            <div className={s.body}>{children}</div>
        </div>
    );
}
