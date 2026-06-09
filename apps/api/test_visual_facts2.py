import sys, json, pathlib

sys.path.insert(0, 'app')

def read_artifact_disk(session_id, stage):
    p = pathlib.Path(f'../../data/storage/sessions/{session_id}/artifacts/{stage}.json')
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding='utf-8'))

import app.pipeline.common as common_mod
common_mod.read_artifact = read_artifact_disk

def write_artifact_disk(session_id, stage, payload):
    p = pathlib.Path(f'../../data/storage/sessions/{session_id}/artifacts/{stage}.json')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return f'sessions/{session_id}/artifacts/{stage}.json'

common_mod.write_artifact = write_artifact_disk

from app.pipeline.stages import extract_visual_facts as evf

sessions = [
    ('46c74c53-6193-4eb1-801c-9fa9a5599c58', 'Docker Desktop'),
    ('ec440370-0c02-419f-891c-6e8643a919cd', 'Biblioteca'),
]

for sid, label in sessions:
    print()
    print("="*60)
    print(f"SESSION: {label} ({sid})")
    print("="*60)
    frames_data = read_artifact_disk(sid, 'analyze_frames')
    if not frames_data:
        print("  [!] No analyze_frames artifact")
        continue
    results = [evf._process_frame(f) for f in frames_data]
    informative = [f for f in results if f['informativeness_score'] >= 0.2]
    noise_only  = [f for f in results if f['diagnostics']['n_blocks_kept'] == 0]
    avg_info = sum(f['informativeness_score'] for f in results) / len(results)
    avg_el   = sum(len(f['visible_ui_elements']) for f in results) / len(results)
    print(f"  frames={len(results)}  informative={len(informative)}  noise_only={len(noise_only)}  avg_score={avg_info:.3f}  avg_elements={avg_el:.2f}")
    top5 = sorted(results, key=lambda f: -f['informativeness_score'])[:5]
    print(f"  --- Top {len(top5)} frames ---")
    for f in top5:
        d = f['diagnostics']
        print(f"  [idx={f['idx']} t={f['t']}s score={f['informativeness_score']}]  app={f['app_context']}  title={f['screen_title']}")
        print(f"    regions_excl={f['regions_excluded']}  noise_removed={f['noise_text_removed']}")
        print(f"    diag: total={d['n_blocks_total']} kept={d['n_blocks_kept']} dropped={d['n_blocks_dropped']} uncertain={d['uncertain']}")
        print(f"    content: {f['main_content_text'][:120]}")
        print(f"    ui_elements ({len(f['visible_ui_elements'])} total, showing first 8):")
        for e in f['visible_ui_elements'][:8]:
            print(f"      [{e['type']:16s}] {repr(e['label']):<32} conf={e['confidence']}")
        print(f"    actions ({len(f['possible_actions'])}):")
        for a in f['possible_actions']:
            print(f"      {a['verb']} {repr(a['target']):<32} conf={a['confidence']}")

print("\nDone.")
