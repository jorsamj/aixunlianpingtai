from pathlib import Path

LABELS = Path('static/modules/training-labels.js')
MAIN = Path('static/main.mjs')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/training-labels.test.mjs')


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and (not new or new in text):
        print(f'{label}: already migrated')
        return text
    if count != 1:
        raise SystemExit(f'expected one {label}, found {count}')
    print(f'{label}: migrated')
    return text.replace(old, new, 1)


def main() -> None:
    text = LABELS.read_text(encoding='utf-8')
    text = replace_one(text, "    wrap('openTrain428', {reset: true});\n", '', 'openTrain428 stale bind')
    text = replace_one(text, "    wrap('refreshTrain428');\n", '', 'refreshTrain428 stale bind')
    text = replace_one(text, "    build: 'module-422507',", "    build: 'module-422509',", 'TrainingLabel build')
    if "wrap('openTrain428'" in text or "wrap('refreshTrain428'" in text:
        raise SystemExit('stale TrainingLabel bind target remains')
    LABELS.write_text(text, encoding='utf-8')

    text = MAIN.read_text(encoding='utf-8')
    text = replace_one(text, "./modules/training-labels.js?v=422508", "./modules/training-labels.js?v=422509", 'TrainingLabel import cache')
    MAIN.write_text(text, encoding='utf-8')

    text = INDEX.read_text(encoding='utf-8')
    text = replace_one(text, '/static/main.mjs?v=42.25.41', '/static/main.mjs?v=42.25.42', 'main outer cache')
    INDEX.write_text(text, encoding='utf-8')

    text = TEST.read_text(encoding='utf-8')
    if "TrainingLabel runtime does not rebind removed 428 entrypoints" not in text:
        text = replace_one(
            text,
            "import assert from 'node:assert/strict';\n",
            "import assert from 'node:assert/strict';\nimport {readFileSync} from 'node:fs';\n",
            'test fs import',
        )
        text += """\n\ntest('TrainingLabel runtime does not rebind removed 428 entrypoints', () => {\n  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');\n  assert.equal(source.includes(\"wrap('openTrain428'\"), false);\n  assert.equal(source.includes(\"wrap('refreshTrain428'\"), false);\n  assert.match(source, /build: 'module-422509'/);\n});\n"""
    TEST.write_text(text, encoding='utf-8')
    print('stale TrainingLabel 428 bind targets pruned')


if __name__ == '__main__':
    main()
