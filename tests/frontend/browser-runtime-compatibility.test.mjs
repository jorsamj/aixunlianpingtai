import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';

import '../../static/browser-runtime.js';

const runtime = globalThis.BrowserCapabilityRuntime;
const appSource = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const indexSource = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const uploadSource = readFileSync(new URL('../../static/modules/material-upload-runtime.js', import.meta.url), 'utf8');
const streamSource = readFileSync(new URL('../../static/modules/training-progress-stream.js', import.meta.url), 'utf8');
const modelArtifactSource = readFileSync(new URL('../../static/modules/model-artifact-runtime.js', import.meta.url), 'utf8');
const serviceNodeSource = readFileSync(new URL('../../static/modules/service-node-runtime.js', import.meta.url), 'utf8');
const authSessionSource = readFileSync(new URL('../../static/auth-session.js', import.meta.url), 'utf8');
const loginSource = readFileSync(new URL('../../static/login.js', import.meta.url), 'utf8');

const frontendFiles = directory => readdirSync(directory, {withFileTypes: true}).flatMap(entry => {
  const path = join(directory, entry.name);
  if (entry.isDirectory()) return frontendFiles(path);
  return /\.(?:js|mjs)$/.test(entry.name) ? [path] : [];
});

test('browser runtime reports secure-context-sensitive capabilities without invoking them', () => {
  const navigatorSource = {
    clipboard: {writeText() {}},
    mediaDevices: {getUserMedia() {}},
    serviceWorker: {},
    geolocation: {},
  };
  const capabilities = runtime.capabilities({
    globalSource: {
      isSecureContext: false,
      crypto: {getRandomValues() {}},
      showOpenFilePicker() {},
      Notification() {},
    },
    navigatorSource,
  });

  assert.deepEqual(capabilities, {
    secureContext: false,
    randomUUID: false,
    randomBytes: true,
    clipboard: false,
    fileSystemAccess: false,
    mediaCapture: false,
    notifications: false,
    serviceWorker: false,
    geolocation: false,
    sharedArrayBuffer: false,
  });
});

test('secure context exposes only capabilities that are actually present', () => {
  const capabilities = runtime.capabilities({
    globalSource: {
      isSecureContext: true,
      crypto: {randomUUID() {}, getRandomValues() {}},
      showDirectoryPicker() {},
      Notification() {},
      SharedArrayBuffer() {},
    },
    navigatorSource: {
      clipboard: {writeText() {}},
      mediaDevices: {getUserMedia() {}},
      serviceWorker: {},
    },
  });

  assert.equal(capabilities.secureContext, true);
  assert.equal(capabilities.randomUUID, true);
  assert.equal(capabilities.randomBytes, true);
  assert.equal(capabilities.clipboard, true);
  assert.equal(capabilities.fileSystemAccess, true);
  assert.equal(capabilities.mediaCapture, true);
  assert.equal(capabilities.notifications, true);
  assert.equal(capabilities.serviceWorker, true);
  assert.equal(capabilities.geolocation, false);
  assert.equal(capabilities.sharedArrayBuffer, true);
});

test('HTTPS randomUUID path creates the requested lowercase hex client id', () => {
  const id = runtime.createClientId('train_', 24, {
    cryptoSource: {randomUUID: () => 'ABCDEF01-2345-6789-ABCD-EF0123456789'},
    random: () => { throw new Error('fallback must not run'); },
  });
  assert.match(id, /^train_[0-9a-f]{24}$/);
  assert.equal(id, 'train_abcdef0123456789abcdef01');
});

test('HTTP getRandomValues path creates the requested lowercase hex client id', () => {
  const id = runtime.createClientId('train_', 20, {
    cryptoSource: {
      getRandomValues(bytes) {
        bytes.forEach((_, index) => { bytes[index] = index + 1; });
        return bytes;
      },
    },
    random: () => { throw new Error('fallback must not run'); },
  });
  assert.equal(id, 'train_0102030405060708090a');
});

test('lowest browser fallback remains collision-safe during rapid annotation creation', () => {
  const options = {
    cryptoSource: null,
    random: () => 0.25,
    now: () => 1_700_000_000_000,
    performanceNow: () => 123.5,
  };
  const ids = Array.from({length: 200}, () => runtime.createClientId('', 20, options));
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.every(id => /^[0-9a-f]{20}$/.test(id)));
});

test('training annotation and upload client identities share the browser runtime owner', () => {
  assert.ok(indexSource.indexOf('/static/browser-runtime.js') < indexSource.indexOf('/static/app.js'));
  const ownerStart = appSource.lastIndexOf('Pointer based annotation editing is the canonical interaction owner.');
  const ownerEnd = appSource.indexOf('// ---------- image upload with actual browser upload progress / ETA ----------', ownerStart);
  const annotationOwner = appSource.slice(ownerStart, ownerEnd);
  assert.match(annotationOwner, /BrowserCapabilityRuntime\.createClientId\('',\s*20\)/);
  assert.doesNotMatch(annotationOwner, /randomUUID|String\(Date\.now\(\)\)/);
  assert.match(uploadSource, /BrowserCapabilityRuntime\.createClientId\('up',\s*32\)/);
  assert.match(uploadSource, /BrowserCapabilityRuntime\.createClientId\('images:',\s*32\)/);
  assert.doesNotMatch(uploadSource, /randomUUID|Math\.random\(\)\.toString\(16\)/);
});

test('clipboard remains an explicitly capability-detected optional enhancement', () => {
  assert.match(modelArtifactSource, /BrowserCapabilityRuntime\?\.has\('clipboard'\)/);
  assert.match(serviceNodeSource, /BrowserCapabilityRuntime\?\.has\('clipboard'\)/);
});

test('training SSE and browser-to-platform requests stay same-origin', () => {
  assert.match(streamSource, /new Source\(`\/api\/v64\/projects\//);
  assert.doesNotMatch(streamSource, /new Source\(`(?:https?|wss?):\/\//);

  const hardcodedNetworkCall = /(?:fetch|EventSource|XMLHttpRequest\.prototype\.open)\s*\([^\n]*(?:https?|wss?):\/\//;
  const offenders = frontendFiles('static')
    .filter(path => hardcodedNetworkCall.test(readFileSync(path, 'utf8')));
  assert.deepEqual(offenders, []);
});

test('HTTP and HTTPS auth navigation stays on the current origin without protocol rewrites', () => {
  assert.match(authSessionSource, /fetch\('\/api\/auth\/session'/);
  assert.match(authSessionSource, /fetch\('\/api\/auth\/logout'/);
  assert.match(authSessionSource, /location\.replace\('\/login/);
  assert.match(loginSource, /fetch\('\/api\/auth\/login'/);
  assert.match(loginSource, /fetch\('\/api\/auth\/session'/);
  assert.doesNotMatch(`${authSessionSource}\n${loginSource}`, /location\.protocol|https?:\/\//);
});
