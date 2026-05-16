"use client";

import { useState } from "react";
import type { AiUsage } from "@/lib/types";

interface Props {
    aiUsage?: AiUsage | null;
}

export function AiUsagePanel({ aiUsage }: Props) {
    const [open, setOpen] = useState(false);

    const hasSomeData =
        aiUsage != null &&
        (aiUsage.models?.stt ||
            aiUsage.models?.vision ||
            aiUsage.models?.llm ||
            aiUsage.models?.ocr ||
            aiUsage.audio_duration_sec != null ||
            aiUsage.frame_count != null ||
            aiUsage.approx_input_chars != null ||
            (aiUsage.calls && aiUsage.calls.length > 0));

    if (!hasSomeData) {
        return (
            <div className="rounded border border-border p-4 text-xs text-muted-foreground">
                <span className="font-semibold uppercase tracking-wider">AI usage</span>
                <span className="ml-3">No AI usage details available for this session.</span>
            </div>
        );
    }

    return (
        <div className="rounded border border-border">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex w-full items-center justify-between px-4 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
            >
                <span>AI usage</span>
                <span>{open ? "▲" : "▼"}</span>
            </button>

            {open && (
                <div className="border-t border-border px-4 py-4">
                    {/* Summary metrics */}
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                        {aiUsage!.models?.stt && (
                            <>
                                <dt className="text-muted-foreground">STT model</dt>
                                <dd className="font-mono text-xs sm:col-span-2">
                                    {aiUsage!.models.stt}
                                </dd>
                            </>
                        )}
                        {aiUsage!.models?.vision && (
                            <>
                                <dt className="text-muted-foreground">Vision model</dt>
                                <dd className="font-mono text-xs sm:col-span-2">
                                    {aiUsage!.models.vision}
                                </dd>
                            </>
                        )}
                        {aiUsage!.models?.llm && (
                            <>
                                <dt className="text-muted-foreground">LLM model</dt>
                                <dd className="font-mono text-xs sm:col-span-2">
                                    {aiUsage!.models.llm}
                                </dd>
                            </>
                        )}
                        {aiUsage!.models?.ocr && (
                            <>
                                <dt className="text-muted-foreground">OCR engine</dt>
                                <dd className="font-mono text-xs sm:col-span-2">
                                    {aiUsage!.models.ocr}
                                </dd>
                            </>
                        )}
                        {aiUsage!.audio_duration_sec != null && (
                            <>
                                <dt className="text-muted-foreground">Audio duration</dt>
                                <dd className="sm:col-span-2">
                                    {aiUsage!.audio_duration_sec.toFixed(1)} s
                                </dd>
                            </>
                        )}
                        {aiUsage!.frame_count != null && (
                            <>
                                <dt className="text-muted-foreground">Frames processed</dt>
                                <dd className="sm:col-span-2">{aiUsage!.frame_count}</dd>
                            </>
                        )}
                        {aiUsage!.approx_input_chars != null && (
                            <>
                                <dt className="text-muted-foreground">Approx input chars</dt>
                                <dd className="sm:col-span-2">
                                    {aiUsage!.approx_input_chars.toLocaleString()}
                                </dd>
                            </>
                        )}
                        {aiUsage!.calls && aiUsage!.calls.length > 0 && (
                            <>
                                <dt className="text-muted-foreground">AI calls</dt>
                                <dd className="sm:col-span-2">{aiUsage!.calls.length}</dd>
                            </>
                        )}
                    </dl>

                    {/* Call detail table */}
                    {aiUsage!.calls && aiUsage!.calls.length > 0 && (
                        <div className="mt-4 overflow-x-auto">
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                                Call details
                            </p>
                            <table className="w-full text-xs">
                                <thead>
                                    <tr className="border-b border-border text-left text-muted-foreground">
                                        <th className="pb-1.5 pr-4 font-medium">Stage</th>
                                        <th className="pb-1.5 pr-4 font-medium">Model</th>
                                        <th className="pb-1.5 pr-4 text-right font-medium">
                                            In chars
                                        </th>
                                        <th className="pb-1.5 pr-4 text-right font-medium">
                                            Out chars
                                        </th>
                                        <th className="pb-1.5 font-medium">Time</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {aiUsage!.calls.map((call, i) => (
                                        <tr key={i} className="border-b border-border/40 last:border-0">
                                            <td className="py-1.5 pr-4 font-mono">
                                                {call.stage ?? "—"}
                                            </td>
                                            <td className="py-1.5 pr-4 font-mono">
                                                {call.model ?? "—"}
                                            </td>
                                            <td className="py-1.5 pr-4 text-right">
                                                {call.input_chars?.toLocaleString() ?? "—"}
                                            </td>
                                            <td className="py-1.5 pr-4 text-right">
                                                {call.output_chars?.toLocaleString() ?? "—"}
                                            </td>
                                            <td className="py-1.5">
                                                {call.ts
                                                    ? new Date(call.ts).toLocaleTimeString()
                                                    : "—"}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
