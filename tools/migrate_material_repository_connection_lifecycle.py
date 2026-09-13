from pathlib import Path


TARGET = Path(__file__).resolve().parents[1] / 'platform_core' / 'material_repository.py'


def main() -> None:
    text = TARGET.read_text(encoding='utf-8')
    old = 'with self._connect() as database:'
    new = 'with closing(self._connect()) as database:'
    count = text.count(old)
    if count < 10:
        raise RuntimeError(f'expected at least 10 live MaterialRepository connection contexts, found {count}')
    text = text.replace(old, new)
    if old in text:
        raise RuntimeError('plain MaterialRepository SQLite connection contexts remain after migration')
    TARGET.write_text(text, encoding='utf-8')
    print(f'MATERIAL_REPOSITORY_CONNECTION_CONTEXTS_MIGRATED={count}')


if __name__ == '__main__':
    main()
