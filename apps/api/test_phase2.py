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

    # Step 1: write visual_facts.json
    frames_data = read_artifact_disk(sid, 'analyze_frames')
    if not frames_data:
        print("  [!] no analyze_frames")
        continue
    results = [evf._process_frame(f) for f in frames_data]
    avg_info = sum(f['informativeness_score'] for f in results) / len(results)
    informative = [f for f in results if f['informativeness_score'] >= 0.2]
    vf_payload = {
        'schema_version': '1.0',
        'frames': results,
        'summary': {
            'frame_count': len(results),
            'informative_frame_count': len(informative),
            'noise_only_frame_count': sum(1 for f in results if f['diagnostics']['n_blocks_kept'] == 0),
            'avg_informativeness_score': round(avg_info, 3),
            'avg_ui_elements_per_frame': round(sum(len(f['visible_ui_elements']) for f in results) / len(results), 2),
        }
    }
    write_artifact_disk(sid, 'visual_facts', vf_payload)
    print(f"  visual_facts.json written ({len(results)} frames)")

    # Step 2: preview enriched frame events
    vf_by_key = {}
    for vf_frame in results:
        fk = vf_frame.get('frame_key')
        if fk:
            vf_by_key[fk] = vf_frame

    full_analyzed = read_artifact_disk(sid, 'analyze_frames') or []
    print(f"\n  --- Per-frame enrichment preview ---")
    for f in full_analyzed:
        frame_key = f.get('key')
        vf = vf_by_key.get(frame_key) if frame_key else None
        idx = f.get('idx', '?')
        t = f.get('t', 0.0)
        if not vf:
            print(f"  [idx={idx} t={t}s]  NO visual_facts match")
            continue
        raw_els = vf.get('visible_ui_elements') or []
        visual_elements = [
            {'label': e['label'], 'type': e['type']}
            for e in raw_els
            if e.get('type') in _VF_TYPES
        ][:_MAX_VF_ELEMENTS]
        possible_actions = vf.get('possible_actions') or []
        score = vf.get('informativeness_score', 0)
        print(f"  [idx={idx} t={t}s score={score}]")
        print(f"    visual_elements ({len(visual_elements)}): {[(e['type'], e['label']) for e in visual_elements]}")
        print(f"    possible_actions: {[(a['verb'], a['target']) for a in possible_actions]}")

print("\nDone.")
