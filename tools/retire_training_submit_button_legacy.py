from pathlib import Path


APP = Path("static/app.js")
OLD = """    const algorithm=(state.algorithms||[]).find(row=>String(row.id)===String(state.train428AlgorithmId)),base=state.iteration414?.[state.train428AlgorithmId],start=root.querySelector('.train428-footer .btn.primary');\n    if(start)start.disabled=s.train.size<2||(!!algorithm?.versions?.length&&(!base?.version_name||!!base.error));\n"""
NEW = """    // TrainingSubmitRuntime is the sole owner of submit-button readiness.\n    // Legacy renderSplit must never write the disabled state from train428/train429 mirrors.\n"""


def main() -> None:
    text = APP.read_text(encoding="utf-8")
    old_count = text.count(OLD)
    new_count = text.count(NEW)
    if old_count == 0 and new_count == 1:
        print("legacy training submit-button owner already retired")
        return
    if old_count != 1:
        raise SystemExit(f"expected exactly one legacy training submit-button owner, found {old_count}")
    if new_count:
        raise SystemExit("replacement marker already exists while legacy owner is still present")
    APP.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("retired legacy training submit-button disabled owner")


if __name__ == "__main__":
    main()
