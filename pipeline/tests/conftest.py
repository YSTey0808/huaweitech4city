import sys
from pathlib import Path

# pipeline/ is a flat script directory, not an installable package (see
# inference.py's own module docstring) -- inference.py and gnn/ import each
# other as top-level modules (`from gnn.config import ...`, `import inference`).
# Put pipeline/ itself on sys.path so tests can import them the same way
# backend/app/main.py does at runtime.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
