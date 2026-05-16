"use client";

// Shape of pipeline_artifacts["sanitize_timeline"] after the backend
// public_artifacts() filter. Note: redaction_map_present is intentionally
// absent — its key name contains "redaction_map" so the backend scrubs it.
type SanitizeArtifact = {
  event_count?: number;
  events_modified?: number;
  placeholder_count?: number;
  distinct_values?: number;
  categories?: Record<string, number>;
  dropped_prefix_events?: number;
  [key: string]: unknown;
};

interface Props {
  artifacts: Record<string, unknown>;
}

export function SanitizationPanel({ artifacts }: Props) {
  const raw = artifacts["sanitize_timeline"];
  const generateGuidePresent = !!artifacts["generate_guide"];

  const artifact: SanitizeArtifact | null =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as SanitizeArtifact)
      : null;

  const sanitized = artifact !== null;

  const placeholderCount =
    typeof artifact?.placeholder_count === "number"
      ? artifact.placeholder_count
      : null;
  const eventsModified =
    typeof artifact?.events_modified === "number"
      ? artifact.events_modified
      : null;
  const eventCount =
    typeof artifact?.event_count === "number" ? artifact.event_count : null;
  const distinctValues =
    typeof artifact?.distinct_values === "number"
      ? artifact.distinct_values
      : null;
  const categoriesRaw =
    artifact?.categories &&
    typeof artifact.categories === "object" &&
    !Array.isArray(artifact.categories)
      ? (artifact.categories as Record<string, number>)
      : null;
  const droppedPrefixEvents =
    typeof artifact?.dropped_prefix_events === "number" &&
    artifact.dropped_prefix_events > 0
      ? artifact.dropped_prefix_events
      : null;

  // Key security insight: LLM ran but sanitization was not applied.
  const llmWithoutSanitization = !sanitized && generateGuidePresent;

  const categoriesList = categoriesRaw
    ? Object.entries(categoriesRaw).sort((a, b) => b[1] - a[1])
    : [];

  const statusLabel = sanitized
    ? "Applicata"
    : llmWithoutSanitization
    ? "Non applicata"
    : "Non eseguita";

  const statusClass = sanitized
    ? "bg-green-100 text-green-800"
    : llmWithoutSanitization
    ? "bg-amber-100 text-amber-800"
    : "bg-muted text-muted-foreground";

  return (
    <div className="rounded border border-border">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Sanitizzazione dati prima dell&rsquo;LLM
        </h3>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusClass}`}
        >
          {statusLabel}
        </span>
      </div>

      <div className="px-4 py-4 space-y-4">
        {/* Pipeline position / status description */}
        <p className="text-xs text-muted-foreground">
          {sanitized
            ? "Il timeline è stato sanificato prima della fase generate_guide. L'LLM ha ricevuto soltanto dati con placeholder."
            : llmWithoutSanitization
            ? "La fase generate_guide è stata eseguita senza una precedente fase sanitize_timeline."
            : "La fase sanitize_timeline non è ancora stata eseguita in questa sessione."}
        </p>

        {/* Security warning */}
        {llmWithoutSanitization && (
          <div className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            ⚠ L&rsquo;LLM ha ricevuto dati non sanificati. Informazioni sensibili presenti
            nella registrazione (email, URL, credenziali…) potrebbero essere state
            trasmesse al provider AI.
          </div>
        )}

        {/* Sanitization metrics */}
        {sanitized && (
          <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">
            {eventCount !== null && (
              <>
                <dt className="text-muted-foreground">Tot. eventi</dt>
                <dd>{eventCount}</dd>
              </>
            )}
            {eventsModified !== null && (
              <>
                <dt className="text-muted-foreground">Eventi modificati</dt>
                <dd className={eventsModified > 0 ? "font-medium" : ""}>
                  {eventsModified}
                </dd>
              </>
            )}
            {placeholderCount !== null && (
              <>
                <dt className="text-muted-foreground">Redazioni totali</dt>
                <dd
                  className={
                    placeholderCount > 0 ? "font-medium text-amber-700" : ""
                  }
                >
                  {placeholderCount}
                </dd>
              </>
            )}
            {distinctValues !== null && (
              <>
                <dt className="text-muted-foreground">Valori distinti</dt>
                <dd>{distinctValues}</dd>
              </>
            )}
          </dl>
        )}

        {/* Clean bill of health */}
        {sanitized && placeholderCount === 0 && (
          <p className="text-xs text-green-700">
            ✓ Nessun pattern sensibile rilevato nel timeline.
          </p>
        )}

        {/* Category breakdown */}
        {sanitized && categoriesList.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Redazioni per tipo
            </p>
            <div className="flex flex-wrap gap-1.5">
              {categoriesList.map(([cat, count]) => (
                <span
                  key={cat}
                  className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 font-mono text-xs text-amber-800"
                >
                  {cat} ({count})
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Dropped internal tool events */}
        {sanitized && droppedPrefixEvents !== null && (
          <p className="text-xs text-muted-foreground">
            {droppedPrefixEvents} evento
            {droppedPrefixEvents !== 1 ? "i" : ""} interno
            {droppedPrefixEvents !== 1 ? "i" : ""} filtrat
            {droppedPrefixEvents !== 1 ? "i" : "o"} prima della fase LLM.
          </p>
        )}
      </div>
    </div>
  );
}
