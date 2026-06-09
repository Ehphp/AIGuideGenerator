import sys, json
sys.path.insert(0, 'app')

# Monkey-patch the models and services so we can run standalone
from unittest.mock import MagicMock, AsyncMock

# Patch imports that need DB
import app.pipeline.common as common_mod

# Override read_artifact to read from disk directly
import pathlib, json as _json

def read_artifact_disk(session_id, stage):
    p = pathlib.Path(f'../../data/storage/sessions/{session_id}/artifacts/{stage}.json')
    if not p.is_file():
        return None
    return _json.loads(p.read_text())

common_mod.read_artifact = read_artifact_disk

# Patch write_artifact to write to disk too
def write_artifact_disk(session_id, stage, payload):
    p = pathlib.Path(f'../../data/storage/sessions/{session_id}/artifacts/{stage}.json')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(payload, ensure_ascii=False, indent=2))
    return f'sessions/{session_id}/artifacts/{stage}.json'

common_mod.write_artifact = write_artifact_disk

# Import the module under test
from app.pipeline.stages import extract_visual_facts as evf

# Test sessions
sessions = [
    ('46c74c53-6193-4eb1-801c-9fa9a5599c58', 'Docker Desktop'),
    ('ec440370-0c02-419f-891c-6e8643a919cd', 'Biblioteca'),
]

for sid, label in sessions:
    print(f'\n{"="*60}')
    print(f'SESSION: {label} ({sid})')
    print('='*60)

    frames_data = read_artifact_disk(sid, 'analyze_frames')
    if not frames_data:
        print('  [!] No analyze_frames artifact found')
        continue

    results = []
    for frame in frames_data:
        try:
            fact = evf._process_frame(frame)
            results.append(fact)
        except Exception as e:
            print(f'  [!] Error on frame idx={frame.get("idx")}: {e}')
            import traceback; traceback.print_exc()

    if not results:
        print('  [!] No frames processed')
        continue

    # Summary
    informative = [f for f in results if f['informativeness_score'] >= 0.2]
    noise_only  = [f for f in results if f['diagnostics']['n_blocks_kept'] == 0]
    avg_info = sum(f['informativeness_score'] for f in results) / len(results)
    avg_el   = sum(len(f['visible_ui_elements']) for f in results) / len(results)

    print(f'  frame_count:             {len(results)}')
    print(f'  informative_frames:      {len(informative)}')
    print(f'  noise_only_frames:       {len(noise_only)}')
    print(f'  avg_informativeness:     {avg_info:.3f}')
    print(f'  avg_ui_elements/frame:   {avg_el:.2f}')

    # Top 5 frames by informativeness
    top5 = sorted(results, key=lambda f: -f['informativeness_score'])[:5]
    print(f'\n  --- Top {len(top5)} frames by informativeness ---')
    for f in top5:
        d = f['diagnostics']
        print(f'\n  Frame idx={f["idx"]} t={f["t"]}s  score={f["informativeness_score"]}')
        print(f'    app_context:     {f["app_context"]}')
        print(f'    screen_title:    {f["screen_title"]}')
        print(f'    regions_excl:    {f["regions_excluded"]}')
        print(f'    noise_removed:   {f["noise_text_removed"]}')
        print(f'    diagnostics:     total={d["n_blocks_total"]} kept={d["n_blocks_kept"]} dropped={d["n_blocks_dropped"]} pct_dropped={d["pct_dropped"]} uncertain={d["uncertain"]}')
        print(f'    main_content:    {f["main_content_text"][:120]}')
        els = f['visible_ui_elements'][:10]
        print(f'    ui_elements ({len(f["visible_ui_elements"])} total, showing first {len(els)}):')
        for e in els:
            print(f'      [{e["type"]:16s}] {e["label"]!r:<30} conf={e["confidence"]} bbox={e["bbox"]}')
        print(f'    possible_actions ({len(f["possible_actions"])}):')
        for a in f['possible_actions']:
            print(f'      {a["verb"]} {a["target"]!r:<30} conf={a["confidence"]}  ({a["reason"]})')

print('\nDone.')
