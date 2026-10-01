"""Debug: check cookies.txt Netscape format (structure only, no values)."""
from pathlib import Path

lines = Path("cookies.txt").read_text(encoding="utf-8").splitlines()
bad = 0
for i, line in enumerate(lines):
    if not line or line.startswith("#"):
        continue
    parts = line.split("\t")
    status = "OK" if len(parts) == 7 else f"BAD ({len(parts)} fields)"
    if len(parts) != 7:
        bad += 1
    domain = parts[0] if parts else "?"
    name = parts[5] if len(parts) > 5 else "?"
    print(f"line {i}: {status}  domain={domain}  name={name}")
print(f"\nTotal bad lines: {bad}")
