from pathlib import Path

PATH = Path("static/modules/training-draft-runtime.js")
text = PATH.read_text(encoding="utf-8")

replacements = [
    (
        "  function inheritanceFor(s, algorithmId = s.train428AlgorithmId) {",
        "  function inheritanceFor(s, algorithmId = s.trainingDraft?.algorithmId || s.train428AlgorithmId) {",
    ),
    (
        "    const previousSplit = s.trainSplitV3 || {};\n    const train = new Set(draft.materialIds || []);\n    const test = new Set(draft.testMaterialIds || []);\n    s.trainSplitV3 = {\n      ...previousSplit,\n      mode: draft.splitMode,\n      train,\n      test,\n      experiment: draft.experimentPercent ?? previousSplit.experiment ?? 20,\n      validation: draft.validationPercent,\n    };\n    s.train429Selected = train;",
        "    delete s.trainSplitV3;\n    s.train429Selected = new Set(draft.materialIds || []);",
    ),
    (
        "    build: 'training-draft-runtime-422506',",
        "    build: 'training-draft-runtime-422507',",
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one match, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)

# One explicit delete is allowed so a hot-loaded stale page cannot retain the retired mirror.
occurrences = text.count("trainSplitV3")
if occurrences != 1 or "delete s.trainSplitV3;" not in text:
    raise SystemExit(f"unexpected trainSplitV3 references after retirement: {occurrences}")

PATH.write_text(text, encoding="utf-8")
print("retired TrainingDraftRuntime trainSplitV3 mirror")
