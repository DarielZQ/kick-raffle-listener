"""Prueba el extractor con texto: `python scripts/extract_text.py "la contraseña es patata de papa"`.

Sin argumentos lee de la entrada estándar (útil para pegar una transcripción entera).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raffle_listener.extract import extract, variants  # noqa: E402
from raffle_listener.transcript import Segment  # noqa: E402

text = " ".join(sys.argv[1:]) or sys.stdin.read()
candidates = extract([Segment(0, 0, text)])
if not candidates:
    print("Sin candidatas.")
for c in candidates:
    print(f"{c.score:.2f}  {c.text!r:30}  [{c.pattern}, x{c.mentions}]  {' | '.join(variants(c.text))}")
