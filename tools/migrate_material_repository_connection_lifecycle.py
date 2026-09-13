from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    ROOT / 'platform_core' / 'material_repository.py': 19,
    ROOT / 'platform_core' / 'material_repository_batch.py': 5,
}
OLD = 'with self._connect() as database:'
NEW = 'with closing(self._connect()) as database:'


def main() -> None:
    migrated = {}
    for target, expected_count in TARGETS.items():
        text = target.read_text(encoding='utf-8')
        count = text.count(OLD)
        if count != expected_count:
            raise RuntimeError(
                f'expected {expected_count} live plain SQLite contexts in {target.name}, found {count}'
            )
        text = text.replace(OLD, NEW)
        if OLD in text:
            raise RuntimeError(f'plain SQLite connection contexts remain in {target.name}')
        target.write_text(text, encoding='utf-8')
        migrated[target.name] = count
    print('MATERIAL_REPOSITORY_CONNECTION_CONTEXTS_MIGRATED=' + ','.join(
        f'{name}:{count}' for name, count in migrated.items()
    ))


if __name__ == '__main__':
    main()
