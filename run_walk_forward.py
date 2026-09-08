"""Back-compat entrypoint. Prefer: ``python scripts/run_walk_forward.py``."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts" / "run_walk_forward.py"), run_name="__main__")
