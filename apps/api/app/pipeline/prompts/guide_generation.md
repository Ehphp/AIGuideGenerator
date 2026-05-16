You are an expert technical writer. Convert the following timeline of a recorded
screen procedure into a structured JSON guide.

Return ONLY a valid JSON object that matches this schema (omit no required keys):

{
  "schema_version": "1.0",
  "title": "string",
  "summary": "string",
  "estimated_duration_minutes": number | null,
  "prerequisites": ["string", ...],
  "tools_or_systems": ["string", ...],
  "steps": [
    {
      "id": "step-1",
      "order": 1,
      "title": "string",
      "description": "string",
      "actions": [{"verb": "click", "target": "Save", "value": null}],
      "evidence": {
        "frame_keys": ["sessions/.../frames/frame_0001.jpg"],
        "transcript_excerpt": "string",
        "t_start": 0.0,
        "t_end": 1.0
      },
      "warnings": ["string"],
      "notes": ["string"],
      "confidence": 0.0
    }
  ],
  "warnings": ["string"],
  "notes": ["string"],
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

Hard constraints:
- Use ONLY evidence present in the current TIMELINE block below. Do not invent
  tools, systems, menu items, prerequisites, goals, or actions that are not
  visible or clearly inferable from the current timeline events.
- Do not copy example application names, menu names, or action targets from
  this prompt into the generated guide. Examples are only illustrative of
  format.
- The Guide Generator application itself is not part of the user's target
  workflow. Ignore recording controls, upload/generation controls, status
  badges, DOCX export buttons, and guide editing buttons.
- If the first timeline events describe opening, using, or controlling the
  Guide Generator (e.g. starting a recording, uploading a video, generating a
  guide, downloading a DOCX), skip those events entirely and begin the guide
  from the first event that belongs to the actual target procedure.
- If something is unclear or absent from the timeline, add a warning instead
  of inventing a plausible step.

Guidelines:
- Steps must be in execution order; assign monotonically increasing `order` and
  ids `step-1`, `step-2`, ...
- Pull evidence frame_keys verbatim from the timeline events.
- Prefer concise, imperative descriptions ("Click Save", not "The user clicks Save").
- Use this action vocabulary and keep `actions[*].verb` in UPPERCASE:
  OPEN, NAVIGATE, CLICK, TYPE, SELECT, CONFIRM, WAIT, DOWNLOAD, UPLOAD,
  SCROLL, VERIFY, COPY, PASTE, CLOSE.
- Every step that describes a UI interaction MUST include at least one
  structured action. Do not leave `actions` empty for operational steps.
- Actions must be atomic and ordered. Split compound instructions into separate
  actions (example: "Open X and click Y" => OPEN X, CLICK Y).
- Keep action targets concrete and UI-visible when possible (menu names,
  button labels, field names, tabs, dialogs).
- Use `value` only when user input/data is involved (TYPE, SELECT, CONFIRM
  with explicit value). Otherwise set `value` to null.
- If evidence is insufficient to infer a target reliably, leave the action out
  and add a warning explaining the ambiguity.
- For steps that contain CLICK actions, include relevant frame_keys from the
  timeline in the step's evidence when available. Use only frame_keys that
  appear verbatim in the timeline events. Do not invent frame_keys.
- Set `confidence` between 0 and 1 reflecting how clearly the timeline supports
  the step.
- If something is unclear, add it to `warnings` rather than inventing details.

Action examples (abstract — do not copy these targets into the guide):
- Description: "Open <Application> and navigate to <Menu Item>."
  Actions:
  [{"verb": "OPEN", "target": "<Application>", "value": null},
   {"verb": "CLICK", "target": "<Menu Item>", "value": null}]
- Description: "Enter the value in <Field> and select <Target System>."
  Actions:
  [{"verb": "TYPE", "target": "<Field>", "value": "<value>"},
   {"verb": "SELECT", "target": "<Target System>", "value": "<option>"}]
- Description: "Confirm the dialog and close the panel."
  Actions:
  [{"verb": "CONFIRM", "target": "<Confirmation dialog>", "value": null},
   {"verb": "CLOSE", "target": "<Panel>", "value": null}]

TIMELINE:
