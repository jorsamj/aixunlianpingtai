"""Run from repository root: python tools/rebuild_training_material_usage.py --help."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_core.training_usage_maintenance import rebuild_owner_batch


def main():
    parser = argparse.ArgumentParser(description='Bounded original Task/Snapshot usage projection maintenance; defaults to dry-run.')
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--batch-size', type=int, default=100)
    parser.add_argument('--apply', action='store_true', help='Write only the rebuildable usage projection and maintenance cursor')
    args = parser.parse_args()
    print(json.dumps(rebuild_owner_batch(args.data_dir, args.project_id, batch_size=args.batch_size, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
