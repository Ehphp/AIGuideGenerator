import json, sys
sid = '1737ea5b-9087-4c0d-a4e0-82b9c3d26a11'
base = f'data/storage/sessions/{sid}/artifacts'

with open(f'{base}/content_classification.json', encoding='utf-8') as f:
    cc = json.load(f)
print('=== content_classification ===')
print(json.dumps(cc, indent=2, ensure_ascii=False))

with open(f'{base}/generate_guide.json', encoding='utf-8') as f:
    gg = json.load(f)
raw = gg.get('raw_text', '')
guide = json.loads(raw)
print('\n=== generate_guide top-level keys ===')
print(list(guide.keys()))
print('document_type:', guide.get('document_type'))
print('steps count:', len(guide.get('steps', [])))
print('sections count:', len(guide.get('sections', [])))
print('\n=== sections ===')
for s in guide.get('sections', []):
    print(f"- kind={s.get('kind')} title={s.get('title')}")
    items = s.get('items') or []
    steps = s.get('steps') or []
    content = s.get('content') or ''
    print(f"  items={len(items)} steps={len(steps)} content_len={len(content)}")

with open(f'{base}/transcribe.json', encoding='utf-8') as f:
    tr = json.load(f)
text = tr.get('text', '')
print(f'\n=== transcribe ===')
print('chars:', len(text))
print('first 500 chars:')
print(text[:500])
