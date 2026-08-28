import os
import sys
import tempfile
from pathlib import Path

import uvicorn


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
test_data_dir = Path(tempfile.mkdtemp(prefix="xjalgo-browser-")).resolve()
os.environ["MC_TRAIN_DATA_DIR"] = str(test_data_dir)
os.environ["MC_PLATFORM_VERSION"] = "browser-test"
uvicorn.run("app:app", host="127.0.0.1", port=8011, log_level="warning")
