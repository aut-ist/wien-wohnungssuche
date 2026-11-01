import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, obj, indent=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    # Windows: Virenscanner/Indexer halten die große listings.json manchmal kurz offen (WinError 5,
    # 2026-11-01 brach so der FindMyHome-Teil des Scrapes ab); kurz warten und nochmal
    for versuch in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if versuch == 9:
                raise
            time.sleep(0.5)
