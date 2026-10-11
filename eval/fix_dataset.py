import json
import shutil
from pathlib import Path

DATASET = Path(__file__).resolve().parent / "dataset.jsonl"
BACKUP = DATASET.with_suffix(".jsonl.bak")

shutil.copy(DATASET, BACKUP)
decoder = json.JSONDecoder()
out_lines = []
split_count = 0

with open(DATASET, encoding="utf-8-sig") as f:
    for n, line in enumerate(f, 1):
        text = line.strip()
        if not text:
            continue
        pos, parts = 0, []
        while pos < len(text):
            obj, end = decoder.raw_decode(text, pos)
            parts.append(obj)
            pos = end
            while pos < len(text) and text[pos].isspace():
                pos += 1
        if len(parts) > 1:
            print(f"line {n}: split into {len(parts)} items "
                  f"({', '.join(p.get('id', '?') for p in parts)})")
            split_count += 1
        out_lines.extend(json.dumps(p, ensure_ascii=False) for p in parts)

with open(DATASET, "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines) + "\n")

print(f"done. {len(out_lines)} items written, {split_count} line(s) repaired.")
print(f"backup saved to {BACKUP}")