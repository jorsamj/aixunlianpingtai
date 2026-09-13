import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const appSource = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function liveStorageUploaderExpression() {
  const captureMarker = 'window.__storageDoUploadImages61=window.doUploadImages426;';
  const captureIndex = appSource.indexOf(captureMarker);
  assert.ok(captureIndex > 0, 'storage61 must capture the live image-upload owner');

  const assignment = 'window.doUploadImages426=';
  const start = appSource.lastIndexOf(assignment, captureIndex);
  assert.ok(start >= 0, 'live storage61 image uploader must be defined before capture');

  const raw = appSource.slice(start + assignment.length, captureIndex).trim();
  assert.ok(raw.startsWith('function(input){'), 'live storage61 uploader must remain directly executable for behavior coverage');
  return raw.endsWith(';') ? raw.slice(0, -1) : raw;
}

function buildHarness() {
  const elements = {
    uploadStorage61: {value: 'default_local'},
    up411Bar: {style: {width: ''}},
    up411Pct: {textContent: ''},
    up411Text: {textContent: ''},
    up411Result: {innerHTML: ''},
  };
  let xhr = null;

  class FakeFormData {
    append() {}
  }

  class FakeXMLHttpRequest {
    constructor() {
      this.upload = {};
      xhr = this;
    }
    open() {}
    send() {}
  }

  const context = vm.createContext({
    window: {},
    document: {getElementById: id => elements[id] || null},
    FormData: FakeFormData,
    XMLHttpRequest: FakeXMLHttpRequest,
    performance: {now: () => 0},
    state: {page: '数据集', images: [], recentUploadedMaterials61: []},
    pid: () => 'project-test',
    closeModal: () => {},
    modal: () => {},
    esc: value => String(value ?? ''),
    renderDatasets424: () => {},
  });

  const uploader = vm.runInContext(`(${liveStorageUploaderExpression()})`, context);
  return {uploader, elements, getXhr: () => xhr};
}

test('plain-image byte upload reaching 100% must not present the whole task as 100% before server commit', () => {
  const {uploader, elements, getXhr} = buildHarness();
  const input = {files: [{name: 'sample.jpg', size: 1024}], value: 'sample.jpg'};

  uploader(input);
  const xhr = getXhr();
  assert.ok(xhr?.upload?.onprogress, 'live uploader must expose browser byte progress');

  xhr.upload.onprogress({lengthComputable: true, loaded: 1024, total: 1024});

  const shown = Number.parseInt(elements.up411Pct.textContent, 10);
  assert.ok(Number.isFinite(shown), 'visible whole-task progress must remain numeric');
  assert.ok(shown < 100, `browser byte completion must stay below terminal 100%, got ${shown}%`);
  assert.notEqual(elements.up411Bar.style.width, '100%', 'progress bar must reserve terminal 100% for successful server commit');
  assert.match(elements.up411Text.textContent, /服务器|入库|处理/, 'after byte transfer completes, UI must tell the user that server-side commit is still running');
});
