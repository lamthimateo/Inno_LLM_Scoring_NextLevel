from pathlib import Path
from typing import Dict


def load_model_outputs(model_outputs_dir: str) -> Dict[str, str]:
    """Return {model_id: raw_text}. Model_id is filename without extension."""
    out: Dict[str, str] = {}
    p = Path(model_outputs_dir)
    for fp in sorted(p.glob("*.txt")):
        out[fp.stem] = fp.read_text(encoding="utf-8")
    return out
