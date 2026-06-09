"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";

export interface UploaderProps {
    disabled?: boolean;
    accept?: string;
    onPicked: (file: File) => void;
}

const ACCEPT_DEFAULT = "video/webm,video/mp4,video/quicktime,video/x-matroska";

// Must match MAX_RECORDING_MB on the backend. Set via NEXT_PUBLIC_MAX_RECORDING_MB env var.
const MAX_UPLOAD_MB = Number(process.env.NEXT_PUBLIC_MAX_RECORDING_MB ?? "2048");

export function Uploader({
    disabled,
    accept = ACCEPT_DEFAULT,
    onPicked,
}: UploaderProps) {
    const inputRef = useRef<HTMLInputElement | null>(null);
    const [name, setName] = useState<string | null>(null);
    const [size, setSize] = useState<number | null>(null);

    return (
        <div className="flex flex-col gap-3">
            <input
                ref={inputRef}
                type="file"
                accept={accept}
                className="hidden"
                onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                        if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
                            alert(
                                `File too large: ${(f.size / 1024 / 1024).toFixed(0)} MB. ` +
                                `Maximum allowed: ${MAX_UPLOAD_MB} MB.`,
                            );
                            e.target.value = "";
                            return;
                        }
                        setName(f.name);
                        setSize(f.size);
                        onPicked(f);
                    }
                }}
            />
            <button
                type="button"
                disabled={disabled}
                onClick={() => inputRef.current?.click()}
                className="inline-flex w-fit items-center gap-2 rounded border border-border bg-background px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
            >
                <Upload className="h-4 w-4" />
                Choose video file
            </button>
            {name && size !== null && (
                <div className="text-sm text-muted-foreground">
                    {name} · {(size / (1024 * 1024)).toFixed(1)} MB
                </div>
            )}
        </div>
    );
}
