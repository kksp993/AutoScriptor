// Offline lifecycle checks: no backend, emulator, wall-clock waits or real input.
const assert = require('node:assert/strict');
const filesystem = require('node:fs');
const path = require('node:path');
const virtualMachine = require('node:vm');

const source = filesystem.readFileSync(path.resolve(
  __dirname, '../../backend/webui/static/js/components/editor/EditorPanel.js',
), 'utf8');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((finish, fail) => { resolve = finish; reject = fail; });
  return { promise, resolve, reject };
}

async function settle() {
  for (let iteration = 0; iteration < 30; iteration++) await Promise.resolve();
}

function createHarness() {
  const requests = [];
  const events = [];
  const errors = [];
  const timers = new Map();
  const unmountCallbacks = [];
  const watchers = [];
  let timerIdentifier = 0;
  let frameNumber = 0;
  const harness = {
    requests, events, errors, timers,
    screenshot: async () => ({ image: `frame-${++frameNumber}`, width: 720, height: 1280 }),
    execute: async () => ({ ok: true, result: 'None' }),
    unmount: () => unmountCallbacks.forEach(callback => callback()),
    async tick() {
      const [identifier, timer] = timers.entries().next().value || [];
      assert.ok(timer, 'Expected a pending screenshot timer');
      timers.delete(identifier);
      timer.callback();
      await settle();
      return timer.milliseconds;
    },
    async importImage() {
      const watcher = watchers.find(entry => entry.options?.immediate);
      await watcher.callback('/archive/frame.png');
    },
  };
  const message = () => {};
  Object.assign(message, { success() {}, warning() {}, info() {}, error: error => errors.push(error) });
  const context = virtualMachine.createContext({
    EditorCanvas: {}, EditorControls: {}, PythonCodeEditor: {}, EditorMenuBar: {}, EditorTutorial: {},
    Vue: {
      ref: value => ({ value }),
      computed: getter => ({ get value() { return getter(); } }),
      watch: (getter, callback, options) => watchers.push({ getter, callback, options }),
      onMounted() {}, onBeforeUnmount: callback => unmountCallbacks.push(callback),
      nextTick: callback => callback(),
    },
    ElementPlus: { ElMessage: message },
    setTimeout(callback, milliseconds) {
      const identifier = ++timerIdentifier;
      timers.set(identifier, { callback, milliseconds });
      return identifier;
    },
    clearTimeout: identifier => timers.delete(identifier),
    fetch: async () => ({ ok: true, blob: async () => ({}) }),
    FileReader: class {
      readAsDataURL() { this.result = 'data:image/png;base64,imported'; this.onload(); }
    },
    window: { WebUIApi: { async request(method, url, body) {
      requests.push({ method, url, body });
      if (url === '/editor/screenshot') return { ok: true, data: await harness.screenshot() };
      if (url === '/editor/execute-code') return { ok: true, data: await harness.execute() };
      if (url === '/editor/ingest-image') {
        return { ok: true, data: { image: 'imported', width: 720, height: 1280 } };
      }
      if (url === '/editor/locate') return { ok: true, data: { found: true, boxes: [] } };
      assert.fail(`Unexpected editor request: ${method} ${url}`);
    } } },
    emitEvent: event => events.push(event),
  });
  virtualMachine.runInContext(source, context);
  harness.panel = virtualMachine.runInContext('EditorPanel.setup({}, { emit: emitEvent })', context);
  return harness;
}

const screenshotCount = harness => harness.requests.filter(request => request.url === '/editor/screenshot').length;

async function testPlaybackAndPause() {
  const harness = createHarness();
  const panel = harness.panel;
  assert.equal(panel.screenshotPlaying?.value, false, 'Playback must default to paused');
  assert.equal(harness.requests.length, 0, 'Opening the editor must not capture a device');
  panel.virtualRemoteOnly.value = true;
  panel.optimizedSel.value = { left: 10, top: 20, right: 40, bottom: 50 };
  panel.name.value = 'target';
  await panel.toggleScreenshotPlayback();
  assert.equal(panel.screenshotPlaying.value, true);
  assert.equal(panel.imageSrc.value, 'data:image/jpeg;base64,frame-1');
  assert.equal(panel.imgWidth.value, 720);
  assert.equal(panel.virtualRemoteOnly.value, true, 'Playback must never enable real input implicitly');
  assert.equal(harness.requests.length, 1, 'Playback must not run OCR on every frame');
  await harness.tick();
  assert.equal(screenshotCount(harness), 2);
  assert.equal(panel.imageSrc.value, 'data:image/jpeg;base64,frame-2');
  await panel.toggleScreenshotPlayback();
  assert.equal(panel.screenshotPlaying.value, false);
  assert.equal(harness.timers.size, 0);
  assert.equal(panel.imageSrc.value, 'data:image/jpeg;base64,frame-2', 'Pause retains the last frame');
  assert.equal(harness.requests.at(-1).url, '/editor/locate', 'Static validation resumes after pause');
  await panel.refreshScreenshot();
  assert.equal(screenshotCount(harness), 3, 'Manual refresh remains available');
}

async function testSlowRequestsAndCleanup() {
  const harness = createHarness();
  const capture = deferred();
  harness.screenshot = () => capture.promise;
  const playing = harness.panel.toggleScreenshotPlayback();
  const manual = harness.panel.refreshScreenshot();
  await settle();
  assert.equal(screenshotCount(harness), 1, 'Slow requests must not overlap');
  assert.equal(harness.timers.size, 0, 'Schedule the next frame only after this request settles');
  const pausing = harness.panel.toggleScreenshotPlayback();
  capture.resolve({ image: 'settled', width: 1280, height: 720 });
  await Promise.all([playing, manual, pausing]);
  assert.equal(harness.panel.imageSrc.value, 'data:image/jpeg;base64,settled');
  assert.equal(harness.timers.size, 0, 'Pause must not leave an automatic refresh behind');

  const lateCapture = deferred();
  harness.screenshot = () => lateCapture.promise;
  const restarted = harness.panel.toggleScreenshotPlayback();
  harness.unmount();
  lateCapture.resolve({ image: 'too-late' });
  await restarted;
  assert.equal(harness.panel.imageSrc.value, 'data:image/jpeg;base64,settled');
  assert.equal(harness.timers.size, 0, 'Unmount must stop timers and ignore late responses');
}

async function testFailureAndImport() {
  const harness = createHarness();
  harness.screenshot = async () => ({ error: 'device unavailable' });
  await harness.panel.toggleScreenshotPlayback();
  assert.equal(harness.panel.screenshotPlaying.value, false);
  assert.equal(harness.errors.length, 1, 'A failure must stop playback instead of spamming retries');
  assert.equal(harness.timers.size, 0);

  const capture = deferred();
  harness.screenshot = () => capture.promise;
  const playing = harness.panel.toggleScreenshotPlayback();
  const importing = harness.importImage();
  await settle();
  capture.resolve({ image: 'old-live-frame', width: 1280, height: 720 });
  await Promise.all([playing, importing]);
  assert.equal(harness.panel.imageSrc.value, 'data:image/jpeg;base64,imported');
  assert.equal(harness.panel.virtualRemoteOnly.value, true);
  assert.equal(harness.panel.screenshotPlaying.value, false);
  assert.equal(harness.timers.size, 0, 'Playback must not overwrite imported offline images');
}

async function finishExecution(harness, execution) {
  await settle();
  assert.equal(await harness.tick(), 1500, 'Final capture allows the scene to settle');
  await execution;
}

async function testExecutionCompletion() {
  for (const response of [
    { ok: true, result: '7' }, { ok: true },
    { ok: false, error: 'snippet failed' },
    { ok: false, error: 'cancelled', code: 'editor_execution_stopped' },
  ]) {
    const harness = createHarness();
    harness.panel.customExecCode.value = 'pass';
    harness.execute = async () => response;
    await finishExecution(harness, harness.panel.executeCustomCode());
    assert.equal(screenshotCount(harness), 1, 'Every completed real run needs a final capture');
    assert.equal(harness.panel.execCustomLoading.value, false);
    assert.equal(harness.panel.imageSrc.value, 'data:image/jpeg;base64,frame-1');
  }

  const harness = createHarness();
  harness.panel.customExecCode.value = 'pass';
  harness.panel.virtualRemoteOnly.value = true;
  harness.panel.imageSrc.value = 'offline-frame';
  const result = deferred();
  harness.execute = () => result.promise;
  const execution = harness.panel.executeCustomCode();
  await settle();
  harness.panel.virtualRemoteOnly.value = false;
  result.resolve({ ok: true, virtual_clicks: [{ x: 10, y: 20 }] });
  await execution;
  assert.equal(screenshotCount(harness), 0, 'Use the submitted mode, not the later switch value');
  assert.equal(harness.panel.imageSrc.value, 'offline-frame');
  assert.equal(harness.panel.virtualClickMarkers.value.length, 1);
  assert.equal(harness.timers.size, 0);

  const rejected = createHarness();
  rejected.panel.customExecCode.value = 'pass';
  rejected.execute = async () => ({ ok: false, code: 'runtime_busy', error: 'busy' });
  await rejected.panel.executeCustomCode();
  assert.equal(screenshotCount(rejected), 0, 'A rejected run never owns a final device capture');
  assert.equal(rejected.timers.size, 0);
}

async function testCompletionWhilePlayingAndImporting() {
  const harness = createHarness();
  const earlierCapture = deferred();
  harness.screenshot = () => earlierCapture.promise;
  const playing = harness.panel.toggleScreenshotPlayback();
  harness.panel.customExecCode.value = 'pass';
  const execution = harness.panel.executeCustomCode();
  await settle();
  assert.equal(await harness.tick(), 1500);
  assert.equal(screenshotCount(harness), 1, 'Final capture waits for the older in-flight frame');
  harness.screenshot = async () => ({ image: 'after-execution', width: 720, height: 1280 });
  earlierCapture.resolve({ image: 'before-execution', width: 720, height: 1280 });
  await Promise.all([playing, execution]);
  assert.equal(screenshotCount(harness), 2, 'Do not reuse a frame requested before execution ended');
  assert.equal(harness.panel.imageSrc.value, 'data:image/jpeg;base64,after-execution');
  assert.equal(harness.panel.screenshotPlaying.value, true, 'Real execution does not disable live preview');
  assert.equal(harness.timers.size, 1, 'Keep only one playback timer after the final capture');
  harness.unmount();
  assert.equal(harness.timers.size, 0);

  const importing = createHarness();
  importing.panel.customExecCode.value = 'pass';
  const finishing = importing.panel.executeCustomCode();
  await settle();
  await importing.importImage();
  await importing.tick();
  await finishing;
  assert.equal(screenshotCount(importing), 0, 'Final refresh must not replace a newly imported frame');
  assert.equal(importing.panel.imageSrc.value, 'data:image/jpeg;base64,imported');

  const disconnected = createHarness();
  disconnected.panel.customExecCode.value = 'pass';
  disconnected.execute = async () => { throw new Error('connection lost'); };
  await disconnected.panel.executeCustomCode();
  assert.equal(screenshotCount(disconnected), 0, 'Transport failure is not proof execution has finished');
  assert.equal(disconnected.panel.execCustomLoading.value, false);
  assert.match(disconnected.errors[0], /connection lost/);
}

function testCanvasDecodeOrder() {
  const images = [];
  const draws = [];
  const watchers = [];
  const unmountCallbacks = [];
  const context = virtualMachine.createContext({
    Vue: {
      ref: value => ({ value }),
      computed: getter => ({ get value() { return getter(); } }),
      watch: (getter, callback) => watchers.push(callback),
      onMounted() {}, onBeforeUnmount: callback => unmountCallbacks.push(callback),
      nextTick: callback => callback(),
    },
    window: {},
    Image: class {
      constructor() { images.push(this); this.complete = true; this.naturalWidth = 1280; }
    },
  });
  virtualMachine.runInContext(filesystem.readFileSync(path.resolve(
    __dirname, '../../backend/webui/static/js/components/editor/EditorCanvas.js',
  ), 'utf8'), context);
  const canvas = virtualMachine.runInContext(`EditorCanvas.setup({
    imgWidth: 1280, imgHeight: 720, locateBoxes: [], virtualClickMarkers: [], virtualSwipeLines: [],
  }, { emit() {} })`, context);
  canvas.canvas.value = { getContext: () => ({ setTransform() {}, drawImage: image => draws.push(image.src) }) };
  watchers[0]('older-frame');
  watchers[0]('newer-frame');
  images[1].onload();
  images[0].onload();
  assert.deepEqual(draws, ['newer-frame'], 'Slow image decoding must not roll back a newer frame');
  watchers[0]('after-unmount');
  unmountCallbacks.forEach(callback => callback());
  images[2].onload();
  assert.deepEqual(draws, ['newer-frame'], 'Image decoding after unmount must not redraw');
}

async function testTutorialPausesWithoutReplacingEditorState() {
  const harness = createHarness();
  const panel = harness.panel;
  panel.recordedCode.value = 'keep_recorded_code()';
  panel.customExecCode.value = 'keep_custom_code()';
  panel.virtualRemoteOnly.value = true;
  await panel.toggleScreenshotPlayback();
  const imageBeforeTutorial = panel.imageSrc.value;
  const requestsBeforeTutorial = harness.requests.length;
  await panel.openEditorTutorial();
  assert.equal(panel.tutorialVisible.value, true);
  assert.equal(panel.screenshotPlaying.value, false);
  assert.equal(harness.timers.size, 0);
  await panel.refreshScreenshot();
  await panel.toggleScreenshotPlayback();
  panel.closeEditorTutorial();
  assert.equal(panel.tutorialVisible.value, false);
  assert.equal(panel.screenshotPlaying.value, false, 'Closing the tutorial must not resume real capture');
  assert.equal(harness.requests.length, requestsBeforeTutorial, 'Tutorial entry/exit must never call device APIs');
  assert.equal(panel.imageSrc.value, imageBeforeTutorial);
  assert.equal(panel.recordedCode.value, 'keep_recorded_code()');
  assert.equal(panel.customExecCode.value, 'keep_custom_code()');
  assert.equal(panel.virtualRemoteOnly.value, true);

  panel.execCustomLoading.value = true;
  await panel.openEditorTutorial();
  assert.equal(panel.tutorialVisible.value, false, 'Do not hide an ongoing code execution behind a tutorial');
  panel.execCustomLoading.value = false;
  const capture = deferred();
  harness.screenshot = () => capture.promise;
  const starting = panel.toggleScreenshotPlayback();
  const opening = panel.openEditorTutorial();
  harness.unmount();
  capture.resolve({ image: 'late-frame' });
  await Promise.all([starting, opening]);
  assert.equal(panel.tutorialVisible.value, false, 'Leaving the editor during entry must not open a late dialog');
}

async function main() {
  await testPlaybackAndPause();
  await testSlowRequestsAndCleanup();
  await testFailureAndImport();
  await testExecutionCompletion();
  await testCompletionWhilePlayingAndImporting();
  testCanvasDecodeOrder();
  await testTutorialPausesWithoutReplacingEditorState();
  const documentationHarness = createHarness();
  await documentationHarness.panel.toggleScreenshotPlayback();
  const captureCount = screenshotCount(documentationHarness);
  await documentationHarness.panel.openApiDocumentation();
  assert.deepEqual(documentationHarness.events, ['open-api-docs']);
  assert.equal(documentationHarness.panel.screenshotPlaying.value, false);
  assert.equal(documentationHarness.timers.size, 0);
  assert.equal(screenshotCount(documentationHarness), captureCount, 'Opening API docs cannot capture another frame');
  documentationHarness.panel.execCustomLoading.value = true;
  await documentationHarness.panel.openApiDocumentation();
  assert.equal(documentationHarness.events.length, 1, 'Do not hide ongoing execution behind API docs');
  console.log('Editor screenshot playback and execution completion: OK');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
