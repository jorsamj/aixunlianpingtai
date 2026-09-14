from pathlib import Path

path = Path('tests/api/test_upload_clean_flow.py')
text = path.read_text(encoding='utf-8')
if 'import hashlib\n' not in text:
    anchor = 'import io\n'
    if text.count(anchor) != 1:
        raise SystemExit('hashlib import anchor mismatch')
    text = text.replace(anchor, anchor + 'import hashlib\n', 1)
old = '''    (app_module.project_dir(pid) / "uploads" / corrupt["stored_name"]).write_bytes(
        b"broken-image"
    )
'''
new = '''    broken = b"broken-image"
    (app_module.project_dir(pid) / "uploads" / corrupt["stored_name"]).write_bytes(broken)
    # This case exercises a corrupt object that is itself the indexed source
    # truth. External mutation after indexing is a distinct SOURCE_CONTENT_CHANGED
    # integrity failure and must not be disguised as image corruption.
    app_module.material_store(pid).patch({
        corrupt["id"]: {
            "content_sha256": hashlib.sha256(broken).hexdigest(),
            "size_bytes": len(broken),
        }
    })
'''
if text.count(old) != 1:
    raise SystemExit(f'corrupt fixture anchor mismatch: {text.count(old)}')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
