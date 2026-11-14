"""Isolated subprocess entry point for offline numerical verification tasks."""
import argparse
from pathlib import Path

from platform_core.deployment.numeric_consistency import run_verification_directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-dir", required=True)
    args = parser.parse_args()
    run_verification_directory(Path(args.verification_dir).resolve())
