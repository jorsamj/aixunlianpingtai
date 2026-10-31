(globalThis => {
  'use strict';

  if (globalThis.BrowserCapabilityRuntime?.build === 'browser-runtime-422600') return;

  let fallbackCounter = 0;

  function availableCapabilities({
    globalSource = globalThis,
    navigatorSource = globalSource.navigator || {},
  } = {}) {
    const secureContext = globalSource.isSecureContext === true;
    const cryptoSource = globalSource.crypto;
    return Object.freeze({
      secureContext,
      randomUUID: typeof cryptoSource?.randomUUID === 'function',
      randomBytes: typeof cryptoSource?.getRandomValues === 'function',
      clipboard: secureContext && typeof navigatorSource.clipboard?.writeText === 'function',
      fileSystemAccess: secureContext && (
        typeof globalSource.showOpenFilePicker === 'function'
        || typeof globalSource.showDirectoryPicker === 'function'
      ),
      mediaCapture: secureContext && typeof navigatorSource.mediaDevices?.getUserMedia === 'function',
      notifications: secureContext && typeof globalSource.Notification === 'function',
      serviceWorker: secureContext && !!navigatorSource.serviceWorker,
      geolocation: secureContext && !!navigatorSource.geolocation,
      sharedArrayBuffer: secureContext && typeof globalSource.SharedArrayBuffer === 'function',
    });
  }

  function fallbackHex(length, {
    random = Math.random,
    now = Date.now,
    performanceNow = () => globalThis.performance?.now?.() || 0,
  } = {}) {
    fallbackCounter = (fallbackCounter + 1) >>> 0;
    const clock = Math.max(0, Number(now?.()) || 0);
    const tick = Math.max(0, Number(performanceNow?.()) || 0);
    const randomWord = () => {
      const sample = Number(random?.());
      const normalized = Number.isFinite(sample) ? Math.abs(sample % 1) : 0;
      return Math.floor(normalized * 0x100000000).toString(16).padStart(8, '0');
    };
    let value = [
      Math.floor(clock).toString(16).slice(-8).padStart(8, '0'),
      fallbackCounter.toString(16).slice(-8).padStart(8, '0'),
      Math.floor(tick * 1000).toString(16).slice(-8).padStart(8, '0'),
      randomWord(),
      randomWord(),
    ].join('');
    while (value.length < length) value += randomWord();
    return value.slice(0, length);
  }

  function browserRandomHex(bytes, {
    cryptoSource = globalThis.crypto,
    random = Math.random,
    now = Date.now,
    performanceNow,
  } = {}) {
    const byteLength = Math.max(1, Math.floor(Number(bytes) || 0));
    const hexLength = byteLength * 2;
    let value = '';

    if (typeof cryptoSource?.randomUUID === 'function') {
      try {
        while (value.length < hexLength) {
          const chunk = String(cryptoSource.randomUUID() || '').replace(/-/g, '').toLowerCase();
          if (!/^[0-9a-f]{32}$/.test(chunk)) {
            value = '';
            break;
          }
          value += chunk;
        }
      } catch (_) {
        value = '';
      }
    }

    if (!value && typeof cryptoSource?.getRandomValues === 'function') {
      try {
        const values = new Uint8Array(byteLength);
        cryptoSource.getRandomValues(values);
        value = Array.from(values, item => item.toString(16).padStart(2, '0')).join('');
      } catch (_) {
        value = '';
      }
    }

    if (!value) value = fallbackHex(hexLength, {random, now, performanceNow});
    return value.slice(0, hexLength);
  }

  function createClientId(prefix, hexLength, options = {}) {
    const normalizedPrefix = String(prefix || '');
    const normalizedLength = Math.max(2, Math.floor(Number(hexLength) || 0));
    const evenLength = normalizedLength % 2 === 0 ? normalizedLength : normalizedLength + 1;
    return `${normalizedPrefix}${browserRandomHex(evenLength / 2, options).slice(0, normalizedLength)}`;
  }

  const runtime = Object.freeze({
    build: 'browser-runtime-422600',
    capabilities: availableCapabilities,
    has(name, sources) {
      return availableCapabilities(sources)[String(name || '')] === true;
    },
    browserRandomHex,
    createClientId,
  });

  globalThis.BrowserCapabilityRuntime = runtime;
})(globalThis);
