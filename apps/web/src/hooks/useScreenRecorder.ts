"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Screen + mic recording via MediaRecorder.
 *
 * Locked decision (Phase 2): screen video + microphone audio only.
 * System audio is best-effort: if the browser exposes audio in the
 * display stream, we keep it as an additional track; otherwise we
 * silently fall back to mic-only.
 *
 * MIME fallback chain:
 *   video/webm;codecs=vp9,opus
 *   video/webm;codecs=vp8,opus
 *   video/webm
 *   (browser default)
 */

const MIME_CANDIDATES = [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
];

export type RecorderState =
    | "idle"
    | "requesting"
    | "recording"
    | "paused"
    | "stopping"
    | "ready"
    | "error";

export interface RecordedMedia {
    blob: Blob;
    mimeType: string;
    durationMs: number;
    sizeBytes: number;
}

export interface UseScreenRecorder {
    state: RecorderState;
    error: string | null;
    elapsedMs: number;
    recorded: RecordedMedia | null;
    previewStream: MediaStream | null;
    isSupported: boolean;
    start: () => Promise<void>;
    stop: () => void;
    reset: () => void;
}

function pickMimeType(): string | undefined {
    if (typeof MediaRecorder === "undefined") return undefined;
    for (const m of MIME_CANDIDATES) {
        try {
            if (MediaRecorder.isTypeSupported(m)) return m;
        } catch {
            /* ignore */
        }
    }
    return undefined;
}

export function useScreenRecorder(): UseScreenRecorder {
    const [state, setState] = useState<RecorderState>("idle");
    const [error, setError] = useState<string | null>(null);
    const [elapsedMs, setElapsedMs] = useState(0);
    const [recorded, setRecorded] = useState<RecordedMedia | null>(null);
    const [previewStream, setPreviewStream] = useState<MediaStream | null>(null);

    const recorderRef = useRef<MediaRecorder | null>(null);
    const chunksRef = useRef<Blob[]>([]);
    const startTsRef = useRef<number>(0);
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const composedStreamRef = useRef<MediaStream | null>(null);
    const displayStreamRef = useRef<MediaStream | null>(null);
    const micStreamRef = useRef<MediaStream | null>(null);
    const audioCtxRef = useRef<AudioContext | null>(null);

    const isSupported =
        typeof window !== "undefined" &&
        typeof navigator !== "undefined" &&
        !!navigator.mediaDevices &&
        typeof (navigator.mediaDevices as MediaDevices).getDisplayMedia === "function" &&
        typeof MediaRecorder !== "undefined";

    const stopAllTracks = useCallback(() => {
        for (const s of [
            composedStreamRef.current,
            displayStreamRef.current,
            micStreamRef.current,
        ]) {
            if (s) s.getTracks().forEach((t) => t.stop());
        }
        composedStreamRef.current = null;
        displayStreamRef.current = null;
        micStreamRef.current = null;
        if (audioCtxRef.current) {
            audioCtxRef.current.close().catch(() => {
                /* ignore */
            });
            audioCtxRef.current = null;
        }
        setPreviewStream(null);
    }, []);

    const clearTimer = useCallback(() => {
        if (timerRef.current !== null) {
            clearInterval(timerRef.current);
            timerRef.current = null;
        }
    }, []);

    const reset = useCallback(() => {
        clearTimer();
        stopAllTracks();
        recorderRef.current = null;
        chunksRef.current = [];
        setElapsedMs(0);
        setRecorded(null);
        setError(null);
        setState("idle");
    }, [clearTimer, stopAllTracks]);

    const start = useCallback(async () => {
        if (!isSupported) {
            setError("Screen recording is not supported in this browser.");
            setState("error");
            return;
        }
        setError(null);
        setRecorded(null);
        setElapsedMs(0);
        setState("requesting");

        let display: MediaStream;
        try {
            display = await navigator.mediaDevices.getDisplayMedia({
                video: { frameRate: 30 },
                audio: true, // best-effort, ignored if not provided
            });
        } catch (e) {
            setError(
                e instanceof Error ? e.message : "Failed to start screen capture."
            );
            setState("error");
            return;
        }
        displayStreamRef.current = display;

        let mic: MediaStream | null = null;
        try {
            mic = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true },
                video: false,
            });
            micStreamRef.current = mic;
        } catch (e) {
            // Mic denied: clean up display and surface a clear error.
            stopAllTracks();
            setError(
                e instanceof Error
                    ? `Microphone permission required: ${e.message}`
                    : "Microphone permission required."
            );
            setState("error");
            return;
        }

        // Compose: screen video + ONE mixed audio track (mic + display audio if any).
        // MediaRecorder typically encodes only the first audio track in WebM, so we
        // mix everything down via Web Audio API into a single output track.
        const composed = new MediaStream();
        display.getVideoTracks().forEach((t) => composed.addTrack(t));

        const audioSources: MediaStream[] = [];
        if (mic.getAudioTracks().length > 0) audioSources.push(mic);
        if (display.getAudioTracks().length > 0) audioSources.push(display);

        if (audioSources.length > 0) {
            try {
                const AudioCtx: typeof AudioContext =
                    window.AudioContext ||
                    (window as unknown as { webkitAudioContext: typeof AudioContext })
                        .webkitAudioContext;
                const ctx = new AudioCtx();
                audioCtxRef.current = ctx;
                // Some browsers (Opera/Safari) start the context suspended.
                if (ctx.state === "suspended") {
                    try {
                        await ctx.resume();
                    } catch {
                        /* ignore */
                    }
                }
                const dest = ctx.createMediaStreamDestination();
                for (const src of audioSources) {
                    const node = ctx.createMediaStreamSource(src);
                    node.connect(dest);
                }
                const mixed = dest.stream.getAudioTracks();
                // eslint-disable-next-line no-console
                console.info(
                    `[recorder] audio sources=${audioSources.length} mixed tracks=${mixed.length} ctx=${ctx.state}`
                );
                mixed.forEach((t) => composed.addTrack(t));
            } catch (e) {
                // Fallback: at least add the mic track raw.
                mic.getAudioTracks().forEach((t) => composed.addTrack(t));
                // eslint-disable-next-line no-console
                console.warn("Audio mixing failed, falling back to mic only:", e);
            }
        }

        composedStreamRef.current = composed;
        setPreviewStream(composed);

        // eslint-disable-next-line no-console
        console.info(
            "[recorder] composed tracks:",
            composed.getTracks().map((t) => ({
                kind: t.kind,
                label: t.label,
                enabled: t.enabled,
                readyState: t.readyState,
            }))
        );

        // If user clicks the browser's "Stop sharing" button, end the recording.
        const videoTrack = display.getVideoTracks()[0];
        if (videoTrack) {
            videoTrack.addEventListener("ended", () => {
                if (recorderRef.current && recorderRef.current.state !== "inactive") {
                    try {
                        recorderRef.current.stop();
                    } catch {
                        /* ignore */
                    }
                }
            });
        }

        const mime = pickMimeType();
        let rec: MediaRecorder;
        try {
            rec = mime
                ? new MediaRecorder(composed, { mimeType: mime })
                : new MediaRecorder(composed);
        } catch (e) {
            stopAllTracks();
            setError(
                e instanceof Error ? e.message : "MediaRecorder failed to initialize."
            );
            setState("error");
            return;
        }
        recorderRef.current = rec;
        chunksRef.current = [];

        rec.ondataavailable = (ev) => {
            if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
        };
        rec.onstop = () => {
            const finalMime = rec.mimeType || mime || "video/webm";
            const blob = new Blob(chunksRef.current, { type: finalMime });
            const durationMs = Date.now() - startTsRef.current;
            clearTimer();
            stopAllTracks();
            setRecorded({
                blob,
                mimeType: finalMime,
                durationMs,
                sizeBytes: blob.size,
            });
            setState("ready");
        };
        rec.onerror = (ev) => {
            const err = (ev as unknown as { error?: Error }).error;
            setError(err?.message ?? "Recorder error");
            setState("error");
            clearTimer();
            stopAllTracks();
        };

        startTsRef.current = Date.now();
        timerRef.current = setInterval(() => {
            setElapsedMs(Date.now() - startTsRef.current);
        }, 200);

        try {
            rec.start();
            setState("recording");
        } catch (e) {
            stopAllTracks();
            clearTimer();
            setError(e instanceof Error ? e.message : "Failed to start recording.");
            setState("error");
        }
    }, [clearTimer, isSupported, stopAllTracks]);

    const stop = useCallback(() => {
        const rec = recorderRef.current;
        if (rec && rec.state !== "inactive") {
            setState("stopping");
            try {
                rec.stop();
            } catch (e) {
                setError(e instanceof Error ? e.message : "Failed to stop.");
                setState("error");
            }
        }
    }, []);

    // Cleanup on unmount.
    useEffect(() => {
        return () => {
            clearTimer();
            stopAllTracks();
        };
    }, [clearTimer, stopAllTracks]);

    return {
        state,
        error,
        elapsedMs,
        recorded,
        previewStream,
        isSupported,
        start,
        stop,
        reset,
    };
}
