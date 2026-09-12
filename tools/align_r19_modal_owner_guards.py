from pathlib import Path

p = Path('tests/frontend/post-render-normalization-owner.test.mjs')
s = p.read_text(encoding='utf-8')

old_modal = "  assert.equal(app.includes(\"function modal(title,body,wide=false){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=body;\"), true);"
new_modal = "  assert.equal(app.includes(\"function modal(title,body,wide=false){$('#modalTitle').textContent=title;window.ModalContentRuntime.replace($('#modalBody'),body);\"), true);"
if s.count(old_modal) != 1:
    raise SystemExit(f'base modal structure guard count={s.count(old_modal)}')
s = s.replace(old_modal, new_modal, 1)

old_observer = "  assert.equal(app.includes(\"modalObserver.observe(modalBody,{childList:true,subtree:true})\"), true);"
new_observer = "  assert.equal(app.includes('new MutationObserver'), false);\n  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);"
if s.count(old_observer) != 1:
    raise SystemExit(f'modal observer structure guard count={s.count(old_observer)}')
s = s.replace(old_observer, new_observer, 1)

p.write_text(s, encoding='utf-8')
print('R19 post-render guards aligned to semantic modal owner')
