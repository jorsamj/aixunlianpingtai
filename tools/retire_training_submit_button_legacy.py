from pathlib import Path


APP = Path("static/app.js")

MIGRATIONS = (
    (
        "renderSplit",
        """    const algorithm=(state.algorithms||[]).find(row=>String(row.id)===String(state.train428AlgorithmId)),base=state.iteration414?.[state.train428AlgorithmId],start=root.querySelector('.train428-footer .btn.primary');\n    if(start)start.disabled=s.train.size<2||(!!algorithm?.versions?.length&&(!base?.version_name||!!base.error));\n""",
        """    // TrainingSubmitRuntime is the sole owner of submit-button readiness.\n    // Legacy renderSplit must never write the disabled state from train428/train429 mirrors.\n""",
    ),
    (
        "refreshProjected417",
        """const aid=state.train428AlgorithmId,a=(state.algorithms||[]).find(x=>String(x.id)===String(aid)),needsBase=!!a?.versions?.length,base=state.iteration414?.[aid],start=root?.querySelector('.train428-footer .btn.primary');if(start)start.disabled=(state.train429Selected?.size||0)<2||(needsBase&&(!base?.version_name||!!base.error))""",
        """// TrainingSubmitRuntime owns submit readiness; legacy projected summary must not mutate button.disabled""",
    ),
)


def main() -> None:
    text = APP.read_text(encoding="utf-8")
    changed = False

    for name, old, new in MIGRATIONS:
        old_count = text.count(old)
        new_count = text.count(new)
        if old_count == 0 and new_count == 1:
            print(f"legacy {name} submit-button owner already retired")
            continue
        if old_count != 1:
            raise SystemExit(f"expected exactly one legacy {name} submit-button owner, found {old_count}")
        if new_count:
            raise SystemExit(f"replacement marker for {name} already exists while legacy owner is still present")
        text = text.replace(old, new, 1)
        changed = True
        print(f"retired legacy {name} submit-button disabled owner")

    if changed:
        APP.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
