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
- An ACTION_LIST block may follow the TIMELINE block. It contains atomic
  actions already mined from the same timeline. Treat each entry in
  ACTION_LIST with `confidence >= 0.5` as a RECALL FLOOR: it must appear in
  at least one step (either as the step's own action or explicitly listed in
  an adjacent step's `actions[]`). You may freely add steps that are not in
  ACTION_LIST when the timeline supports them, but you must NOT silently
  drop a mined high-confidence action. When using a mined action, prefer its
  `target` and `value` as the step's action target/value, and copy its
  `transcript_excerpt` and `frame_keys` into the step's evidence.

Coverage requirements (CRITICAL — read carefully):
- This is a comprehensive step-by-step reproduction guide, NOT an executive
  summary. Your job is to reconstruct every concrete operational action the
  user performs in the recording so a reader can replay it end-to-end.
- Step density target: produce roughly ONE step per 60–120 seconds of
  substantive timeline activity. A 5-minute procedural recording should
  yield 4–8 steps, a 10-minute one 8–15 steps, a 20-minute one 15–25 steps.
  Outputs with only 2–3 steps for recordings longer than 5 minutes are
  considered a failure of this task.
- Every transcript segment containing an imperative or operational verb in
  the recording language (open/click/type/run/install/configure/create/
  save/check/verify/edit/select/copy/paste/close/restart/apri/clicca/
  scrivi/esegui/installa/configura/crea/salva/verifica/modifica/seleziona/
  copia/incolla/chiudi/riavvia/…) MUST either become its own step or be
  explicitly covered inside an adjacent step whose `description` mentions
  that action.
- Whenever a frame event at time T shows a distinct UI interaction (button
  click, form input, terminal command, navigation between tabs/panes) and
  no current step covers a window around T, create a new step for it.
- It is acceptable to skip the first/last ~5% of the timeline if it is
  framing or chitchat with no concrete action. Everything between, when it
  contains a verb-target pair anchored in the timeline, belongs in the guide.
- One step = one atomic, replayable action. Do NOT merge multiple distinct
  actions into one step: "Open the terminal and run docker compose up"
  must become TWO steps (one OPEN, one RUN). Same for compound transcript
  segments like "configura il file .env e poi avvia i container" → two steps.

Forbidden output patterns (these indicate the model is over-summarising and
should be avoided):
- A `steps` array with fewer than 4 entries when the timeline spans more
  than ~5 minutes of substantive procedural content.
- Generic, non-evidenced prerequisites or warnings such as "X must be
  installed" / "Ensure all dependencies are installed" when installation
  is never discussed or shown in the timeline. Prerequisites and warnings
  must be anchored to specific timeline events.
- Step descriptions that lump together more than one verb-target pair
  ("Open and configure and run …").
- `transcript_excerpt` fields that are vague filler ("Ok", "vai", "si")
  when richer, more descriptive adjacent transcript text is available.
- Two or three high-level meta-steps ("Setup environment", "Run application")
  in place of the concrete sequence of operations the user actually performed.

Guidelines:
- Steps must be in execution order; assign monotonically increasing `order` and
  ids `step-1`, `step-2`, ...
- Pull evidence frame_keys verbatim from the timeline events.
- Prefer concise, imperative descriptions ("Click Save", not "The user clicks Save").
- Granularity bias: when in doubt between producing one combined step or two
  separate steps, ALWAYS prefer two steps. It is far better to be slightly
  too granular than to drop or merge actions.
- Cover the full timeline span: the `t_start` of your first step and the
  `t_end` of your last step should together span most of the substantive
  procedural portion of the recording. Large unexplained gaps (> 3 minutes
  with no step) between adjacent steps suggest missing coverage — add steps
  or document the gap with a `notes` entry explaining why nothing happens
  there.
- Use this action vocabulary and keep `actions[*].verb` in UPPERCASE:
  OPEN, NAVIGATE, CLICK, TYPE, SELECT, CONFIRM, WAIT, DOWNLOAD, UPLOAD,
  SCROLL, VERIFY, COPY, PASTE, CLOSE.
- Every step that describes a UI interaction MUST include at least one
  structured action. Do not leave `actions` empty for operational steps.
- Actions must be atomic and ordered. Split compound instructions into separate
  actions (example: "Open X and click Y" => OPEN X, CLICK Y).
- Keep action targets concrete and UI-visible when possible (menu names,
  button labels, field names, tabs, dialogs).
- Frame events may include two optional fields produced by structured OCR
  analysis: `visual_elements` and `possible_actions`.
  - `visual_elements`: list of `{"label": "...", "type": "..."}` representing
    classified widgets visible on screen. Types: `button`, `list_item`,
    `navigation_item`, `title`, `status_badge`, `error_message`.
  - `possible_actions`: list of `{"verb": "...", "target": "...", "confidence": 0.0}`
    pre-inferred from those elements.
  When these fields are present on a frame event, treat them as primary
  evidence for action targets — they are already filtered from OCR noise and
  carry semantically classified labels. Apply these rules:
  - PREFER a `possible_actions` entry whose `verb` matches the action you are
    writing (e.g. `CLICK`) and whose `target` is a specific identifier (a
    container name, an item ID, a menu label) over anything derived from raw
    `ocr_text` or `ui_summary`.
  - PREFER `visual_elements` of type `button`, `list_item`, or
    `navigation_item` over generic OCR text when naming action targets.
  - Entries with `[hyphenated-id]` in their `reason` field are high-confidence
    specific identifiers (e.g. "guide-generator", "problemi-db") — prioritise
    them as CLICK targets.
  - Discard labels shorter than 3 characters, labels containing `[` or `]`,
    and labels that are generic single words: Button, Field, Container, Menu,
    Option, Tab, Icon, Item, Row, Panel, Box.
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
