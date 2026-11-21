"""Point the portal at a throwaway database before anything imports it."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="rtps-qap-test-"))
os.environ["RTPS_QAP_DB"] = str(_tmp / "test.db")
