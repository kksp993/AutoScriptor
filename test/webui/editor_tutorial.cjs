// Exercise only the tutorial's public interactions; any device/network access fails.
const assert = require('node:assert/strict');
const filesystem = require('node:fs');
const path = require('node:path');
const virtualMachine = require('node:vm');

const tutorialPath = path.resolve(__dirname, '../../backend/webui/static/js/components/editor/EditorTutorial.js');
assert.ok(filesystem.existsSync(tutorialPath), 'The editor needs an embedded interactive tutorial');

function createTutorial() {
  const timers = new Map();
  const unmountCallbacks = [];
  const emitted = [];
  let nextTimer = 0;
  const context = virtualMachine.createContext({
    EditorCanvas: {}, EditorMenuBar: {},
    Vue: {
      ref: value => ({ value }),
      computed: getter => ({ get value() { return getter(); } }),
      onBeforeUnmount: callback => unmountCallbacks.push(callback),
      nextTick: callback => callback(),
    },
    setTimeout(callback, delay) {
      timers.set(++nextTimer, { callback, delay });
      return nextTimer;
    },
    clearTimeout: identifier => timers.delete(identifier),
    fetch: () => assert.fail('Tutorial must never fetch a device or API'),
    window: { WebUIApi: { request: () => assert.fail('Tutorial must not use the backend') } },
  });
  virtualMachine.runInContext(filesystem.readFileSync(tutorialPath, 'utf8'), context);
  context.emit = event => emitted.push(event);
  const tutorial = virtualMachine.runInContext('EditorTutorial.setup({}, { emit })', context);
  return {
    tutorial, timers, emitted,
    unmount: () => unmountCallbacks.forEach(callback => callback()),
    flush() {
      let remaining = 50;
      while (timers.size && remaining-- > 0) {
        const [identifier, timer] = timers.entries().next().value;
        timers.delete(identifier);
        timer.callback();
      }
      assert.ok(remaining > 0, 'Demonstrations must finish instead of leaving a timer loop');
    },
  };
}

const practice = createTutorial();
const tutorial = practice.tutorial;
assert.equal(tutorial.steps.length, 7);
assert.equal(tutorial.currentStepIndex.value, 0);
assert.equal(tutorial.frameLoaded.value, false);
tutorial.captureDemoFrame();
assert.equal(tutorial.frameLoaded.value, true);
assert.ok(tutorial.frameSource.value.startsWith('data:image/svg+xml'));
tutorial.toggleDemoPlayback();
assert.equal(tutorial.playing.value, true);
tutorial.toggleDemoPlayback();
assert.equal(tutorial.playing.value, false);
assert.equal(practice.timers.size, 0);

tutorial.goToStep(1);
tutorial.onDemoSelection({ left: 0, top: 0, right: 40, bottom: 40 });
assert.equal(tutorial.completedSteps.value.includes(1), false, 'Missing the target is not a completed exercise');
tutorial.onDemoSelection({ left: 920, top: 490, right: 1160, bottom: 600 });
assert.ok(tutorial.completedSteps.value.includes(1));

tutorial.goToStep(2);
for (const kind of ['T', 'I', 'B']) {
  tutorial.targetKind.value = kind;
  tutorial.generateDemoTarget();
  assert.ok(tutorial.generatedCode.value.startsWith(`${kind}(`));
}

tutorial.goToStep(3);
tutorial.recordDemoClick();
assert.equal(tutorial.clickMarkers.value.length, 1);
assert.match(tutorial.recordedCode.value, /click\(T\(/);
tutorial.onDemoCanvasSwipe({ x1: 100, y1: 200, x2: 300, y2: 200 });
assert.match(tutorial.recordedCode.value, /swipe\(B\(100,200\), B\(300,200\), duration_s=1\)/);
assert.equal(tutorial.swipeLines.value.length, 1);

tutorial.goToStep(4);
const waiting = tutorial.menuGroups.value.find(group => group.label === '\u64cd\u4f5c')
  .items.find(item => item.key === 'wait').children[0];
tutorial.runMenuAction(waiting);
assert.match(tutorial.recordedCode.value, /wait_for_appear\(/);
assert.ok(tutorial.completedSteps.value.includes(4));

tutorial.goToStep(5);
tutorial.runDemoCode();
assert.equal(tutorial.executionRunning.value, true);
tutorial.stopDemoCode();
assert.equal(tutorial.executionRunning.value, false);
assert.equal(practice.timers.size, 0);
tutorial.runDemoCode();
practice.flush();
assert.match(tutorial.executionResult.value, /930.*500.*220.*90/);

tutorial.goToStep(6);
tutorial.previewTaskSave();
assert.equal(tutorial.savePreview.value, '', 'Saving needs an explicit name and start');
tutorial.taskName.value = 'demo/mail';
tutorial.taskStart.value = '\u6751\u5e84';
tutorial.previewTaskSave();
assert.match(tutorial.savePreview.value, /data\/custom_task\/demo\/mail\.py/);
tutorial.taskName.value = '../outside';
tutorial.previewTaskSave();
assert.equal(tutorial.savePreview.value, '', 'The example must not teach unsafe paths');

for (let stepIndex = 0; stepIndex < tutorial.steps.length; stepIndex++) {
  tutorial.goToStep(stepIndex);
  tutorial.runDemonstration();
  practice.flush();
  assert.equal(tutorial.demonstrating.value, false);
  assert.ok(tutorial.completedSteps.value.includes(stepIndex), `Demo ${stepIndex + 1} must teach a complete action`);
}

tutorial.goToStep(0);
tutorial.toggleDemoPlayback();
tutorial.goToStep(1);
assert.equal(practice.timers.size, 0, 'Step changes stop playback');
tutorial.runDemonstration();
assert.ok(practice.timers.size);
practice.unmount();
assert.equal(practice.timers.size, 0, 'Unmount cancels delayed demonstrations');

const closing = createTutorial();
closing.tutorial.runDemonstration();
closing.tutorial.closeTutorial();
assert.equal(closing.timers.size, 0);
assert.deepEqual(closing.emitted, ['close']);
const reopened = createTutorial();
assert.equal(reopened.tutorial.currentStepIndex.value, 0);
assert.equal(reopened.tutorial.completedSteps.value.length, 0);
assert.equal(reopened.timers.size, 0, 'Opening the tutorial never auto-starts a demo');
console.log('Editor tutorial interactions, safety and lifecycle: OK');
