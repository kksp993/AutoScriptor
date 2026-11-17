const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const requests = [];
const errors = [];
const refreshDelays = [];
let remoteResponse = { ok: true };
let pendingClick = null;
const context = vm.createContext({
  EditorCanvas: {}, EditorControls: {}, PythonCodeEditor: {}, EditorMenuBar: {}, EditorTutorial: {},
  Vue: {
    ref: value => ({ value }),
    computed: getter => ({ get value() { return getter(); } }),
    watch() {}, onMounted() {}, onBeforeUnmount() {},
    nextTick: callback => callback(),
  },
  ElementPlus: { ElMessage: { success() {}, warning() {}, info() {}, error: message => errors.push(message) } },
  setTimeout: (callback, milliseconds) => {
    refreshDelays.push(milliseconds);
    callback();
  },
  window: { WebUIApi: {
    async request(method, url, body) {
      requests.push({ method, url, body });
      if (url.endsWith('/remote/click')) {
        if (pendingClick) await pendingClick;
        return { data: remoteResponse };
      }
      return { data: { image: 'next-frame', width: 1280, height: 720 } };
    },
  } },
});
const source = fs.readFileSync(path.resolve(
  __dirname, '../../backend/webui/static/js/components/editor/EditorPanel.js',
), 'utf8');
vm.runInContext(source, context);
const panel = vm.runInContext('EditorPanel.setup({}, { emit() {} })', context);

function attachInput(model, inputRef) {
  let selection = { start: 0, end: 0 };
  inputRef.value = {
    getSelectionRange: () => selection,
    setSelection(start, end) { selection = { start, end }; },
    replaceRange(start, end, replacement) {
      model.value = model.value.slice(0, start) + replacement + model.value.slice(end);
    },
  };
  return inputRef.value;
}

const input = attachInput(panel.recordedCode, panel.recordedCodeInput);
const sequenceAction = panel.recorderMenuGroups.value
  .flatMap(group => group.items).find(item => item.key === 'seq-click');
assert.ok(sequenceAction, 'Sequence action must be reachable from the operation menu');
sequenceAction.action();
assert.equal(panel.recordedCode.value, 'seq_click([])');
assert.equal(input.getSelectionRange().start, 'seq_click(['.length);

panel.optimizedSel.value = { left: 1, top: 2, right: 11, bottom: 22 };
panel.virtualRemoteOnly.value = true;
panel.insertCurrentTargetObject();
panel.insertCurrentTargetObject();
assert.equal(panel.recordedCode.value, 'seq_click([B(1,2,10,20), B(1,2,10,20), ])');
assert.equal(panel.recordedCode.value.slice(input.getSelectionRange().start), '])');

function insertAtMarker(code) {
  const position = code.indexOf('|');
  panel.recordedCode.value = code.replace('|', '');
  input.setSelection(position, position);
  panel.insertCurrentTargetObject();
  return panel.recordedCode.value;
}

assert.equal(insertAtMarker('ui_T(|)'), 'ui_T(B(1,2,10,20))');
assert.equal(insertAtMarker('seq_click([], until=lambda: ui_T(|))'),
  'seq_click([], until=lambda: ui_T(B(1,2,10,20)))');
assert.equal(insertAtMarker('seq_click([T("[)"),\n    |])'),
  'seq_click([T("[)"),\n    B(1,2,10,20), ])');
assert.equal(insertAtMarker('seq_click(target=[\n# ] ignored\n|])'),
  'seq_click(target=[\n# ] ignored\nB(1,2,10,20), ])');

panel.recordedCode.value = 'seq_click([T("old"), T("next")])';
input.setSelection('seq_click(['.length, 'seq_click([T("old")'.length);
panel.insertCurrentTargetObject();
assert.equal(panel.recordedCode.value, 'seq_click([B(1,2,10,20), T("next")])');
panel.insertCurrentTargetObject();
assert.equal(panel.recordedCode.value, 'seq_click([B(1,2,10,20), B(1,2,10,20), T("next")])');

panel.functionEditorDialogVisible.value = true;
const functionInput = attachInput(panel.functionEditorCode, panel.functionEditorCodeInput);
sequenceAction.action();
panel.insertCurrentTargetObject();
assert.equal(panel.functionEditorCode.value, 'seq_click([B(1,2,10,20), ])');
assert.equal(panel.functionEditorCode.value.slice(functionInput.getSelectionRange().start), '])');
console.log('Sequence menu, caret, repeated insertion, context and function editor: OK');

async function testSequenceRecordingClick() {
  panel.functionEditorDialogVisible.value = false;
  panel.virtualRemoteOnly.value = false;
  panel.recordedCode.value = 'seq_click([])';
  input.setSelection('seq_click(['.length, 'seq_click(['.length);
  await panel.insertCurrentTargetObject();
  assert.equal(requests.length, 2, 'Sequence generation must click once and refresh the screenshot');
  assert.equal(requests[0].url, '/editor/remote/click');
  assert.equal(JSON.stringify(requests[0].body), JSON.stringify({ x: 6, y: 12 }));
  assert.equal(requests[1].url, '/editor/screenshot');
  assert.equal(panel.recordedCode.value, 'seq_click([B(1,2,10,20), ])');
  assert.equal(panel.recordedCode.value.slice(input.getSelectionRange().start), '])');
  assert.equal(panel.imageSrc.value, 'data:image/jpeg;base64,next-frame');
  assert.equal(panel.remoteLoading.value, false);
  assert.equal(refreshDelays.at(-1), 1500,
    'Remote capture must allow 1.5 seconds for the next game page to render');

  requests.length = 0;
  panel.recordedCode.value = 'ui_T()';
  input.setSelection(5, 5);
  await panel.insertCurrentTargetObject();
  assert.equal(requests.length, 0, 'Non-sequence generation must not click');

  panel.virtualRemoteOnly.value = true;
  panel.recordedCode.value = 'seq_click([])';
  input.setSelection('seq_click(['.length, 'seq_click(['.length);
  await panel.insertCurrentTargetObject();
  assert.equal(requests.length, 0, 'Virtual recording must not request the device');
  assert.equal(JSON.stringify(panel.virtualClickMarkers.value.slice(-1)), JSON.stringify([{ x: 6, y: 12 }]));

  panel.virtualRemoteOnly.value = false;
  remoteResponse = { ok: false, error: 'credential_locked', message: 'unlock required' };
  await panel.insertCurrentTargetObject();
  assert.equal(requests.length, 1, 'A rejected click must not refresh or retry');
  assert.equal(errors.at(-1), 'unlock required');
  assert.equal(panel.remoteLoading.value, false);

  remoteResponse = { ok: true };
  requests.length = 0;
  let finishClick;
  pendingClick = new Promise(resolve => { finishClick = resolve; });
  const generating = panel.insertCurrentTargetObject();
  assert.equal(panel.remoteLoading.value, true);
  const recordedBeforeDuplicate = panel.recordedCode.value;
  await panel.insertCurrentTargetObject();
  assert.equal(panel.recordedCode.value, recordedBeforeDuplicate, 'Ignore duplicate clicks while recording');
  assert.equal(requests.length, 1);
  finishClick();
  await generating;
  pendingClick = null;
  assert.equal(panel.remoteLoading.value, false);
  console.log('Sequence recording click, screenshot, virtual mode, rejection and duplicate guard: OK');
}

testSequenceRecordingClick().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
