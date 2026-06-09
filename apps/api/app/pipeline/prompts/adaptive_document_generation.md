You are an expert technical writer. Analyse the timeline below and produce a
structured JSON document that best fits the content. The content has already
been classified as non-procedural (technical, conceptual, diagnostic, demo,
or mixed). Do NOT force the content into a step-by-step procedural guide.

Return ONLY a valid JSON object that matches this schema:

{
  "schema_version": "1.1",
  "document_type": "technical | conceptual | diagnostic | demo | mixed",
  "intended_audience": "end_user | developer | sysadmin | operator | mixed",
  "title": "string",
  "summary": "string",
  "estimated_duration_minutes": number | null,
  "prerequisites": ["string", ...],
  "tools_or_systems": ["string", ...],
  "sections": [
    {
      "kind": "overview | technical | conceptual | diagnostic | demo | notes | references",
      "title": "string",
      "content": "string",
      "items": ["string", ...],
      "steps": [],
      "warnings": ["string", ...],
      "notes": ["string", ...]
    }
  ],
  "steps": [],
  "warnings": ["string", ...],
  "notes": ["string", ...],
  "troubleshooting": [
    {"symptom": "string", "likely_cause": "string", "resolution": "string"}
  ],
  "metadata": {
    "generated_by": "string",
    "generated_at": "iso-8601 string",
    "source_session_id": "string",
    "source_duration_sec": number | null
  }
}

Document type guidance
----------------------

technical — architecture, system config, backend logic, APIs, code, infra:
  Use sections like: "Architecture Overview", "Components", "Configuration",
  "Data Flow", "Integration Points", "API Reference", "Deployment Notes".
  Use `items` for lists of components, config keys, or parameters.
  Describe how things work, not how to click through a UI.

conceptual — theory, explanation, knowledge base:
  Use sections like: "Core Concepts", "How It Works", "Key Principles",
  "Terminology", "Examples", "Limitations".
  Write flowing explanatory prose in `content`.
  Use `items` for definitions or enumerated concepts.

diagnostic — troubleshooting, error investigation, problem-cause-solution:
  Use sections like: "Problem Description", "Symptoms", "Root Cause Analysis",
  "Resolution Steps", "Prevention".
  `steps` inside a section is acceptable when the resolution is procedural.
  Populate `troubleshooting` at the guide level if multiple issues are covered.

demo — product/feature demonstration, capability showcase:
  Use sections like: "Feature Overview", "Demonstrated Capabilities",
  "Workflow Walkthrough", "Key Observations", "Limitations / Known Issues".
  Use `content` to narrate what was shown; use `items` for feature bullet points.

mixed — content spanning multiple types:
  Choose section `kind` values per-section to reflect each section's nature.
  It is valid to include both `sections` (for explanatory parts) and `steps`
  (for any procedural segments) at the guide level.

Hard constraints
----------------
- Use ONLY evidence present in the current TIMELINE below. Do not invent
  concepts, components, configurations, or features not visible or clearly
  inferable from the timeline events.
- Do not copy example names from this prompt. Examples are illustrative only.
- The Guide Generator application itself is not part of the target content.
  Ignore recording controls, upload/generation controls, DOCX export buttons,
  and guide editing buttons.
- Leave `steps` as an empty list [] unless the content contains a genuine
  procedural segment that benefits from step numbering (e.g., the resolution
  path in a diagnostic section).
- If something is unclear or absent from the timeline, add a warning rather
  than inventing content.
- Set `estimated_duration_minutes` to null if the content is not a timed task.

Section guidelines
------------------
- Every section MUST have a non-empty `title`.
- `content` should be a coherent prose paragraph or two about the section topic.
- `items` should be concise bullet points (noun phrases or short sentences).
- `warnings` should highlight risks, limitations, or common mistakes relevant
  to that section.
- `notes` should provide supplemental context or cross-references.
- Aim for 3–7 sections that together form a coherent document. Avoid very
  short sections (< 2 sentences / < 2 items) — merge them.

TIMELINE:
