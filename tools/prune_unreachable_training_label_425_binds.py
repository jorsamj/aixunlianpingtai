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
    for old, label in (
        ("    wrap('startAlgorithmTraining423', {reset: true});\n", 'startAlgorithmTraining423 bind'),
        ("    wrap('openTrain425', {reset: true});\n", 'openTrain425 bind'),
        ("    wrap('trainCounts425');\n", 'trainCounts425 bind'),
    ):
        text = replace_one(text, old, '', label)
    text = replace_one(text, "    build: 'module-422509',", "    build: 'module-422510',", 'TrainingLabel build')
    for token in ("wrap('startAlgorithmTraining423'", "wrap('openTrain425'", "wrap('trainCounts425'"):
        if token in text:
            raise SystemExit(f'unreachable historical TrainingLabel bind remains: {token}')
    LABELS.write_text(text, encoding='utf-8')

    text = MAIN.read_text(encoding='utf-8')
    text = replace_one(text, "./modules/training-labels.js?v=422509", "./modules/training-labels.js?v=422510", 'TrainingLabel import cache')
    MAIN.write_text(text, encoding='utf-8')

    text = INDEX.read_text(encoding='utf-8')
    text = replace_one(text, '/static/main.mjs?v=42.25.42', '/static/main.mjs?v=42.25.43', 'main outer cache')
    INDEX.write_text(text, encoding='utf-8')

    text = TEST.read_text(encoding='utf-8')
    text = text.replace("assert.match(source, /build: 'module-422509'/);", "assert.match(source, /build: 'module-422510'/);")
    if "final stable renderers make historical 423/425 training entrypoints unreachable" not in text:
        text += r'''

test('final stable renderers make historical 423/425 training entrypoints unreachable', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

  const stableCards = app.lastIndexOf('window.renderAlg412=function(){');
  const stableAlgorithmPage = app.lastIndexOf('window.renderAlgorithms423=function(){');
  assert.ok(stableCards >= 0 && stableAlgorithmPage > stableCards);
  const cardSource = app.slice(stableCards, stableAlgorithmPage);
  assert.match(cardSource, /startAlgorithmTraining429\('\$\{a\.id\}'\)/);
  assert.equal(cardSource.includes("startAlgorithmTraining423('${a.id}')"), false);

  const finalTaskRenderer = app.lastIndexOf('window.renderTraining425=window.renderTraining424=window.renderTraining423=function(){');
  assert.ok(finalTaskRenderer >= 0);
  const taskSource = app.slice(finalTaskRenderer, finalTaskRenderer + 5000);
  assert.equal(taskSource.includes('openTrain425()'), false);
  assert.equal(taskSource.includes('▶ 开始训练'), false);

  const last423Call = app.lastIndexOf("startAlgorithmTraining423('${a.id}')");
  const last425OpenCall = app.lastIndexOf('openTrain425(');
  const last425CountCall = app.lastIndexOf('trainCounts425()');
  assert.ok(last423Call >= 0 && last423Call < stableCards);
  assert.ok(last425OpenCall >= 0 && last425OpenCall < finalTaskRenderer);
  assert.ok(last425CountCall >= 0 && last425CountCall < finalTaskRenderer);

  const labels = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  assert.equal(labels.includes("wrap('startAlgorithmTraining423'"), false);
  assert.equal(labels.includes("wrap('openTrain425'"), false);
  assert.equal(labels.includes("wrap('trainCounts425'"), false);
  assert.match(labels, /build: 'module-422510'/);
});
'''
    TEST.write_text(text, encoding='utf-8')
    print('unreachable historical TrainingLabel 423/425 binds pruned')


if __name__ == '__main__':
    main()
