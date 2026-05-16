"use client";

import { useState } from "react";
import { apiBase } from "@/lib/apiClient";

interface GuideFrameViewerProps {
    frameKeys: string[];
}

export function GuideFrameViewer({ frameKeys }: GuideFrameViewerProps) {
    const [expanded, setExpanded] = useState(false);
    const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

    if (frameKeys.length === 0) return null;

    const count = frameKeys.length;

    return (
        <div>
            {/* Toggle button */}
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="flex items-center gap-1 rounded border border-border bg-muted px-2 py-1 text-xs text-muted-foreground hover:bg-muted/70 hover:text-foreground"
            >
                <span aria-hidden="true">🖼</span>
                {expanded ? "Hide" : "Show"} screenshot{count !== 1 ? "s" : ""} ({count})
            </button>

            {/* Thumbnail strip */}
            {expanded && (
                <div className="mt-2 flex flex-wrap gap-2">
                    {frameKeys.map((key) => {
                        const src = `${apiBase}/files/${key}`;
                        return (
                            <button
                                key={key}
                                type="button"
                                onClick={() => setLightboxSrc(src)}
                                className="overflow-hidden rounded border border-border transition-opacity hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-ring"
                                title="Click to enlarge"
                            >
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                    src={src}
                                    alt="Step screenshot"
                                    className="h-24 w-auto max-w-[160px] object-cover"
                                    loading="lazy"
                                />
                            </button>
                        );
                    })}
                </div>
            )}

            {/* Lightbox overlay */}
            {lightboxSrc && (
                <div
                    role="dialog"
                    aria-modal="true"
                    aria-label="Screenshot enlarged view"
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
                    onClick={() => setLightboxSrc(null)}
                    onKeyDown={(e) => {
                        if (e.key === "Escape") setLightboxSrc(null);
                    }}
                    tabIndex={-1}
                >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                        src={lightboxSrc}
                        alt="Step screenshot enlarged"
                        className="max-h-[90vh] max-w-[90vw] rounded shadow-2xl"
                        onClick={(e) => e.stopPropagation()}
                    />
                    <button
                        type="button"
                        onClick={() => setLightboxSrc(null)}
                        className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/40"
                        aria-label="Close"
                    >
                        ✕
                    </button>
                </div>
            )}
        </div>
    );
}
