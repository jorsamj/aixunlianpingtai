import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const indexHtml = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const start = source.indexOf('const PLAIN_UPLOAD_PENDING_KEY411=');
const end = source.indexOf('const esc=s=>', start);
assert.ok(start > 0 && end > start, 'plain upload request identity helper must exist');

let entropyCounter = 0;
function harness(storage = new Map()) {
  let projectId = 'project-1';
  const context = {
    sessionStorage: {
      getItem: key => storage.has(key) ? storage.get(key) : null,
      setItem: (key, value) => storage.set(key, String(value)),
    },
    window: {
      crypto: {
        getRandomValues(bytes) {
          bytes.fill(++entropyCounter);
          return bytes;
        },
      },
    },
    pid: () => projectId,
    Uint8Array,
  };
  vm.runInNewContext(
    source.slice(start, end) +
      '\nthis.claim = preparePlainUpload411; this.finish = finishPlainUpload411; this.settle = settlePlainUploadResponse411;',
    context,
  );
  function form(sourceId = 'default_local', file = {name:'camera.jpg',size:2048,type:'image/jpeg',lastModified:100}) {
    const data = new Map([
      ['files', [file]], ['dataset_id', ['default']],
      ['storage_source_id', [sourceId]],
    ]);
    return {
      getAll: key => data.get(key) || [],
      get: key => (data.get(key) || [null])[0],
      set: (key, value) => data.set(key, [value]),
    };
  }
  return {
    claim: formData => context.claim(formData),
    finish: ticket => context.finish(ticket),
    settle: (ticket, status, body) => context.settle(ticket, status, body),
    form, storage,
    project: value => { projectId = value; },
  };
}

test('normal image upload gets request ID stable for retries and page reload', () => {
  const storage = new Map();
  const first = harness(storage);
  const form1 = first.form();
  const ticket1 = first.claim(form1);
  assert.match(ticket1.id, /^plain-[0-9a-f]{32}$/);
  assert.equal(form1.get('upload_request_id'), ticket1.id);
  const ticket2 = first.claim(first.form());
  assert.equal(ticket2.id, ticket1.id);
  const reloaded = harness(storage);
  assert.equal(reloaded.claim(reloaded.form()).id, ticket1.id);
  reloaded.finish(ticket1);
  assert.notEqual(reloaded.claim(reloaded.form()).id, ticket1.id);
});

test('source, project, and file identity are fenced independently', () => {
  const h = harness();
  const base = h.claim(h.form()).id;
  const otherSource = h.claim(h.form('secondary-local')).id;
  assert.notEqual(otherSource, base);
  h.project('project-2');
  assert.notEqual(h.claim(h.form()).id, base);
  h.project('project-1');
  assert.notEqual(h.claim(h.form('default_local',
    {name:'camera.jpg',size:4096,type:'image/jpeg',lastModified:100})).id, base);
});

test('fetch and XHR ordinary image upload paths reuse one request envelope', () => {
  const appScript = indexHtml.match(/<script src="\/static\/app\.js\?v=(\d+)\.(\d+)\.(\d+)"><\/script>/);
  assert.ok(appScript, 'application script must have a versioned cache key');
  const [major, minor, patch] = appScript.slice(1).map(Number);
  assert.ok(major > 42 || (major === 42 && (minor > 25 || (minor === 25 && patch > 333))),
    'the new runtime must not use the stale cached app.js');
  assert.ok(source.includes("preparePlainUpload411(opt.body)"));
  assert.ok(source.includes("const uploadTicket=preparePlainUpload411(form);const xhr=new XMLHttpRequest()"));
  assert.ok(source.includes("const uploadTicket=preparePlainUpload411(fd);const xhr=new XMLHttpRequest()"));
  const xhrSuccess = "xhr.addEventListener('load',()=>settlePlainUploadResponse411(uploadTicket,xhr.status,xhr.responseText));";
  assert.equal(source.split(xhrSuccess).length - 1, 2);
});


test('only server-confirmed byte mismatch releases ambiguous upload request ID', () => {
  const h = harness();
  const original = h.claim(h.form());
  h.settle(original, 409, JSON.stringify({code:'UPLOAD_REQUEST_IN_PROGRESS'}));
  assert.equal(h.claim(h.form()).id, original.id);
  h.settle(original, 0, '');
  assert.equal(h.claim(h.form()).id, original.id);
  h.settle(original, 409, JSON.stringify({code:'UPLOAD_REQUEST_MANIFEST_MISMATCH'}));
  const renewed = h.claim(h.form());
  assert.notEqual(renewed.id, original.id);
  // A late response for the previous request must not clear the newer ID.
  h.settle(original, 200, '{}');
  assert.equal(h.claim(h.form()).id, renewed.id);
  h.settle(renewed, 200, '{}');
  assert.notEqual(h.claim(h.form()).id, renewed.id);
});
