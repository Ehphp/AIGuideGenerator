"""Verify Phase 3 fixes: cleaner visual_elements + possible_actions for Docker and Biblioteca."""
import sys, json, pathlib
sys.path.insert(0, 'app')

def read_artifact_disk(session_id, stage):
    p = pathlib.Path(f'../../data/storage/sessions/{session_id}/artifacts/{stage}.json')
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding='utf-8'))

def write_artifact_disk(session_id, stage, payload):
    p = pathlib.Path(f'../../data/storage/sessions/{session_id}/artifacts/{stage}.json')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return f'sessions/{session_id}/artifacts/{stage}.json'

import app.pipeline.common as cm
cm.read_artifact = read_artifact_disk
cm.write_artifact = write_artifact_disk

from app.pipeline.stages import extract_visual_facts as evf

_VF_TYPES = frozenset({'list_item', 'button', 'navigation_item', 'status_badge', 'title', 'error_message'})
_MAX_VF_ELEMENTS = 12

sessions = [
    ('46c74c53-6193-4eb1-801c-9fa9a5599c58', 'Docker Desktop'),
    ('ec440370-0c02-419f-891c-6e8643a919cd', 'Biblioteca'),
]

for sid, label in sessions:
    print()
    print("="*60)
    print(f"SESSION: {label}")
    print("="*60)
    frames_data = read_artifact_disk(sid, 'analyze_frames')
    if not frames_data:
        print("  [!] no analyze_frames")
        continue
    results = [evf._process_frame(f) for f in frames_data]
    avg_info = sum(f['informativeness_score'] for f in results) / len(results)
    print(f"  frames={len(results)}  avg_score={avg_info:.3f}")

    print(f"\n  --- All frames: screen_title + top possible_actions ---")
    for f in sorted(results, key=lambda x: x['idx']):
        d = f['diagnostics']
        els = [e for e in f['visible_ui_elements'] if e['type'] in _VF_TYPES][:_MAX_VF_ELEMENTS]
        acts = f['possible_actions']
        print(f"  [idx={f['idx']} t={f['t']}s score={f['informativeness_score']}]"
              f"  app={f['app_context']}  title={f['screen_title']}")
        print(f"    diag: total={d['n_blocks_total']} kept={d['n_blocks_kept']} uncertain={d['uncertain']}")
        print(f"    visual_elements ({len(els)}): {[(e['type'], e['label']) for e in els]}")
        print(f"    possible_actions ({len(acts)}): {[(a['verb'], a['target'], a.get('reason','')) for a in acts]}")
        print()

print("Done.")
