interface EditFieldProps {
    label: string;
    value: string;
    onChange: (value: string) => void;
    multiline?: boolean;
    rows?: number;
    type?: "text" | "number";
    required?: boolean;
    placeholder?: string;
}

export function EditField({
    label,
    value,
    onChange,
    multiline = false,
    rows = 3,
    type = "text",
    required = false,
    placeholder,
}: EditFieldProps) {
    return (
        <label className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {label}
            </span>
            {multiline ? (
                <textarea
                    value={value}
                    rows={rows}
                    required={required}
                    placeholder={placeholder}
                    onChange={(e) => onChange(e.target.value)}
                    className="rounded border border-input bg-background px-3 py-2 text-sm text-foreground outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                />
            ) : (
                <input
                    type={type}
                    value={value}
                    required={required}
                    placeholder={placeholder}
                    onChange={(e) => onChange(e.target.value)}
                    className="rounded border border-input bg-background px-3 py-2 text-sm text-foreground outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                />
            )}
        </label>
    );
}
