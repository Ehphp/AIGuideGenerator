import json, sys, pathlib

BASE = pathlib.Path(r"C:\Users\EmilioCittadini\Desktop\ITGuideGenerator\data\storage\sessions\ec440370-0c02-419f-891c-6e8643a919cd\artifacts")

# --- analyze_frames summary ---
af = json.loads((BASE / "analyze_frames.json").read_text(encoding="utf-8"))
print(f"=== analyze_frames: {len(af)} frames ===")
for f in af:
    blocks = (f.get("ocr") or {}).get("blocks") or []
    print(f"  idx={f['idx']:3d} t={f['t']:7.2f}s  ocr_len={len(f['ocr_text']):4d}  blocks={len(blocks)}")

# --- visual_facts summary ---
vf = json.loads((BASE / "visual_facts.json").read_text(encoding="utf-8"))
print(f"\n=== visual_facts summary ===")
print(json.dumps(vf.get("summary"), indent=2))
print("\n--- Per frame (t, app_context, screen_title, info_score, n_elements) ---")
for f in vf["frames"]:
    n = len(f.get("visible_ui_elements") or [])
    print(f"  idx={f['idx']:3d} t={f['t']:7.2f}s  app={str(f.get('app_context')):<20} title={str(f.get('screen_title')):<30} info={f.get('informativeness_score',0):.3f}  n_els={n}")

# --- build_timeline snippet (first 10 frame events) ---
bt = json.loads((BASE / "build_timeline.json").read_text(encoding="utf-8"))
events = bt.get("events") or []
frame_events = [e for e in events if e.get("kind") == "frame"]
print(f"\n=== build_timeline: {len(events)} events ({len(frame_events)} frame events) ===")
for e in frame_events[:10]:
    has_ve = bool(e.get("visual_elements"))
    has_pa = bool(e.get("possible_actions"))
    print(f"  t={e['t']:7.2f}s  ocr_len={len(e.get('ocr_text','')):<5}  has_visual_elements={has_ve}  has_possible_actions={has_pa}")
    if has_ve:
        for ve in e.get("visual_elements", [])[:4]:
            print(f"       VE: {ve}")
