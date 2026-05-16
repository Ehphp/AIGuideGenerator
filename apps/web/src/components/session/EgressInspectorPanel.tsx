"use client";

import { useState } from "react";

// Public shape of egress_generate_guide after backend public_artifacts() filter.
// The "payload" field is stripped server-side (SENSITIVE_FIELD_NAMES); only
// the metadata summary is exposed.
type EgressArtifact = {
  prompt_chars?: number;
  timeline_language?: string | null;
  events_total?: number;
  transcript_events?: number;
  frame_events?: number;
  sanitize_enabled?: boolean;
  ocr_provider?: string;
  frame_keys_opacified?: boolean;
  [key: string]: unknown;
};

type EgressRepairArtifact = {
  kind?: "legacy" | "sanitized";
  prompt_chars?: number;
  sanitize_enabled?: boolean;
  first_error_len?: number;
  [key: string]: unknown;
};

interface Props {
  artifacts: Record<string, unknown>;
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

export function EgressInspectorPanel({ artifacts }: Props) {
  const [open, setOpen] = useState(false);

  const rawEgress = artifacts["egress_generate_guide"];
  const rawRepair = artifacts["egress_validate_repair"];

  const egress: EgressArtifact | null =
    rawEgress && typeof rawEgress === "object" && !Array.isArray(rawEgress)
      ? (rawEgress as EgressArtifact)
      : null;

  const repair: EgressRepairArtifact | null =
    rawRepair && typeof rawRepair === "object" && !Array.isArray(rawRepair)
      ? (rawRepair as EgressRepairArtifact)
      : null;

  if (!egress && !repair) return null;

  const isExternal =
    egress?.ocr_provider === "openai" ||
    (!egress?.sanitize_enabled && egress?.events_total !== undefined);

  const sanitized = egress?.sanitize_enabled ?? false;
  const opacified = egress?.frame_keys_opacified ?? false;

  const headerBadgeClass = sanitized
    ? "bg-green-100 text-green-800"
    : "bg-amber-100 text-amber-800";
  const headerBadgeLabel = sanitized ? "Sanitizzato" : "Non sanitizzato";

  return (
    <div className="rounded border border-border">
      {/* Header */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between border-b border-border px-4 py-3 text-left"
      >
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Egress AI — cosa è stato inviato al provider esterno
        </h3>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${headerBadgeClass}`}
          >
            {headerBadgeLabel}
          </span>
          <span className="text-xs text-muted-foreground">
            {open ? "▲" : "▼"}
          </span>
        </div>
      </button>

      {open && (
        <div className="px-4 py-4 space-y-4">
          {/* Vision / multimodal warning */}
          {egress?.ocr_provider === "openai" && (
            <div className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-800">
              ⚠ <strong>Modalità Vision attiva</strong>: immagini base64 dei
              frame sono state inviate a OpenAI. Assicurarsi che{" "}
              <code>OCR_PROVIDER</code> sia impostato correttamente e che
              l&rsquo;uso delle immagini sia voluto.
            </div>
          )}

          {/* Sanitization missing warning */}
          {!sanitized && egress && (
            <div className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              ⚠ <strong>Sanitizzazione disabilitata</strong>: il timeline è
              stato inviato senza redazione PII. Attivare{" "}
              <code>SANITIZE_ENABLED=true</code> per produzione.
            </div>
          )}

          {/* Egress summary stats */}
          {egress && (
            <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-3">
              {egress.prompt_chars !== undefined && (
                <Stat
                  label="Caratteri inviati"
                  value={egress.prompt_chars.toLocaleString("it-IT")}
                />
              )}
              {egress.events_total !== undefined && (
                <Stat label="Tot. eventi" value={egress.events_total} />
              )}
              {egress.transcript_events !== undefined && (
                <Stat
                  label="Segmenti transcript"
                  value={egress.transcript_events}
                />
              )}
              {egress.frame_events !== undefined && (
                <Stat label="Frame (OCR)" value={egress.frame_events} />
              )}
              {egress.timeline_language && (
                <Stat label="Lingua" value={egress.timeline_language} />
              )}
              {egress.ocr_provider && (
                <Stat
                  label="OCR provider"
                  value={
                    <span
                      className={
                        egress.ocr_provider === "openai"
                          ? "font-semibold text-red-700"
                          : ""
                      }
                    >
                      {egress.ocr_provider}
                    </span>
                  }
                />
              )}
              <Stat
                label="Frame key opacizzati"
                value={
                  opacified ? (
                    <span className="text-green-700">✓ sì</span>
                  ) : (
                    <span className="text-amber-700">no</span>
                  )
                }
              />
              <Stat
                label="Payload (timeline)"
                value={
                  <span className="italic text-muted-foreground">
                    rimosso (solo locale)
                  </span>
                }
              />
            </dl>
          )}

          {/* Repair pass */}
          {repair && (
            <div className="rounded border border-border bg-muted/40 px-3 py-3 text-xs space-y-1">
              <p className="font-medium text-muted-foreground">
                Repair pass validate_guide
              </p>
              <p>
                Tipo:{" "}
                <span className="font-mono">
                  {repair.kind ?? "—"}
                </span>
                {repair.kind === "sanitized" ? (
                  <span className="ml-2 text-green-700">
                    ✓ solo placeholder inviati
                  </span>
                ) : repair.kind === "legacy" ? (
                  <span className="ml-2 text-amber-700">
                    guida JSON (nessun timeline raw)
                  </span>
                ) : null}
              </p>
              {repair.prompt_chars !== undefined && (
                <p>
                  Caratteri prompt repair:{" "}
                  {repair.prompt_chars.toLocaleString("it-IT")}
                </p>
              )}
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Il payload completo (timeline sanitizzata) è salvato localmente in{" "}
            <code>artifacts/egress_generate_guide.json</code> e non viene
            esposto via API.
          </p>
        </div>
      )}
    </div>
  );
}
