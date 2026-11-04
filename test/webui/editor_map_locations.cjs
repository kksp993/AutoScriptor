// Exercise the real menu actions and cursor insertion without a device.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const mountedCallbacks = [];
let finishNavigationRequest;
const context = vm.createContext({
  EditorCanvas: {}, EditorControls: {}, PythonCodeEditor: {}, EditorMenuBar: {},
  Vue: {
    ref: value => ({ value }),
    computed: getter => ({ get value() { return getter(); } }),
    watch() {}, onMounted: callback => mountedCallbacks.push(callback),
    onBeforeUnmount() {}, nextTick: callback => callback(),
  },
  ElementPlus: { ElMessage: { success() {}, warning() {}, error: assert.fail } },
  document: { addEventListener() {} },
  window: { WebUIApi: {
    request: () => new Promise(resolve => { finishNavigationRequest = resolve; }),
  } },
});
vm.runInContext(fs.readFileSync(path.resolve(
  __dirname, '../../backend/webui/static/js/components/editor/EditorPanel.js',
), 'utf8'), context);
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

const mainInput = attachInput(panel.recordedCode, panel.recordedCodeInput);
const functionInput = attachInput(panel.functionEditorCode, panel.functionEditorCodeInput);
const findTools = () => panel.recorderMenuGroups.value.find(group => group.label === '工具').items;
const findMap = () => findTools().find(item => item.key === 'map-location');
assert.ok(findMap(), 'Tools must offer map location objects alongside navigation');
assert.equal(findMap().children[0].label, '重新加载');

function labels(items) {
  return Array.from(items, item => ({
    label: item.label, children: item.children ? labels(item.children) : null,
  }));
}
async function main() {
  mountedCallbacks.forEach(callback => callback());
  assert.equal(findMap().children[0].disabled(), true);
  finishNavigationRequest({ data: { ok: true, items: [
    { name: '村庄', locations: ['邮件', '法相'] },
    { name: '天庭', locations: [] },
  ] } });
  await new Promise(resolve => setImmediate(resolve));
  const navigation = findTools().find(item => item.key === 'navigation');
  assert.deepEqual(labels(findMap().children), labels(navigation.children));

  const snippets = [];
  for (const inFunction of [false, true]) {
    panel.functionEditorDialogVisible.value = inFunction;
    const model = inFunction ? panel.functionEditorCode : panel.recordedCode;
    const input = inFunction ? functionInput : mainInput;
    model.value = 'ui_T()';
    input.setSelection(5, 5);
    findMap().children[0].children[1].action();
    assert.equal(model.value, 'ui_T(mm.locs["邮件"].identifier)');
    snippets.push(model.value);
    model.value = 'seq_click([])';
    input.setSelection(11, 11);
    findMap().children[1].action();
    assert.equal(model.value, 'seq_click([mm.locs["天庭"].identifier, ])');
    assert.equal(input.getSelectionRange().start, model.value.length - 2);
  }
  console.log(JSON.stringify(snippets));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
