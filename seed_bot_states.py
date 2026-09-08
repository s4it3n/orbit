"""Back-compat entrypoint. Prefer: ``python scripts/seed_bot_states.py``."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts" / "seed_bot_states.py"), run_name="__main__")
