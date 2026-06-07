import os
from pathlib import Path

KUZU_DATA_DIR = Path(os.getenv("KUZU_DATA_DIR", Path(__file__).parent / "kuzu_data"))
# KùzuDB creates and owns this path itself — do not pre-create it with mkdir
