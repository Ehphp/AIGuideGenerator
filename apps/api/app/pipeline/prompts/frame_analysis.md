You are analyzing a single screenshot from a recorded screen procedure.
Return ONLY a JSON object with these keys:
  "ocr_text": string  -- the visible text on screen, concatenated, no markup
  "ui_summary": string -- one or two sentences describing the active window, the
                          control(s) the user appears to interact with, and any
                          dialogs/menus visible.
Do not include any other keys. Do not wrap in markdown.
