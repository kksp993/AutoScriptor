// Exercise task-save metadata and navigation choices without a backend or device.
const assert = require('node:assert/strict');
const filesystem = require('node:fs');
const path = require('node:path');
const virtualMachine = require('node:vm');

const requests = [];
const warnings = [];
const errors = [];
let navigationResponse = { ok: true, items: [
  { name: 'Town', locations: ['Mail', 'Inventory'] },
  { name: 'Heaven', locations: [] },
] };
let saveResponse = { ok: true, message: 'Saved' };
const context = virtualMachine.createContext({
  EditorCanvas: {}, EditorControls: {}, PythonCodeEditor: {}, EditorMenuBar: {},
  Vue: {
    ref: value => ({ value }),
    computed: getter => ({ get value() { return getter(); } }),
    watch() {}, onMounted() {}, onBeforeUnmount() {}, nextTick: callback => callback(),
  },
  ElementPlus: { ElMessage: {
    success() {}, warning: message => warnings.push(message), error: message => errors.push(message),
  } },
  window: { WebUIApi: { async request(method, url, body) {
    requests.push({ method, url, body });
    if (url === '/editor/navigation-options') return { data: navigationResponse };
    if (url === '/editor/save-custom-task') return { data: saveResponse };
    if (url === '/editor/execute-code/stop') return { data: { ok: true } };
    assert.fail(`Unexpected editor request: ${method} ${url}`);
  } } },
});
virtualMachine.runInContext(filesystem.readFileSync(path.resolve(
  __dirname, '../../backend/webui/static/js/components/editor/EditorPanel.js',
), 'utf8'), context);
const panel = virtualMachine.runInContext('EditorPanel.setup({}, { emit() {} })', context);
const template = virtualMachine.runInContext('EditorPanel.template', context);
const plain = value => value === undefined ? value : JSON.parse(JSON.stringify(value));
const saveRequests = () => requests.filter(request => request.url === '/editor/save-custom-task');

async function main() {
  assert.deepEqual(plain(panel.saveScriptForm.value.ensureIn), [], 'No implicit starting location is allowed');
  assert.match(template, /v-model="saveScriptForm\.ensureIn"/);
  assert.match(template, /emitPath:\s*false/);
  assert.match(template, /debug=True,\s*ensure_in=None/);

  panel.recordedCode.value = 'click(B(10, 20))';
  panel.saveScriptForm.value.taskPathTail = 'UnrelatedFolder/Example';
  await panel.saveCustomScript();
  assert.equal(panel.saveScriptDialogVisible.value, true);
  assert.equal(panel.saveScriptSelfRegistered.value, false);
  assert.deepEqual(plain(panel.saveScriptForm.value.ensureIn), [], 'Folder names must not infer a start');
  assert.deepEqual(plain(panel.saveScriptStartOptions.value), [
    { value: 'Town', label: 'Town', children: [
      { value: 'Mail', label: 'Mail' }, { value: 'Inventory', label: 'Inventory' },
    ] },
    { value: 'Heaven', label: 'Heaven' },
  ]);

  await panel.submitSaveCustomScript();
  assert.equal(saveRequests().length, 0, 'An empty start must block raw snippet saves');
  assert.ok(warnings.some(message => message.includes('ensure_in')));
  panel.saveScriptForm.value.ensureIn = ['NotRegistered'];
  await panel.submitSaveCustomScript();
  assert.equal(saveRequests().length, 0, 'Arbitrary location names must not be submitted');

  panel.saveScriptForm.value.ensureIn = ['Mail', 'Heaven'];
  panel.saveScriptForm.value.description = ' Summary ';
  panel.saveScriptForm.value.taskDoc = ' Detailed explanation ';
  panel.saveScriptForm.value.params = [{
    name: 'mode', type: 'enum', description: ' Mode ', enum_options: '["normal","hard"]',
  }];
  await panel.submitSaveCustomScript();
  assert.deepEqual(plain(saveRequests()[0].body), {
    filename: 'Example.py', code: 'click(B(10, 20))',
    metadata: {
      task_path: '\u81ea\u5b9a\u4e49\u4efb\u52a1/UnrelatedFolder/Example',
      description: 'Summary', task_doc: 'Detailed explanation',
      params: [{ name: 'mode', type: 'enum', description: 'Mode', enum_options: ['normal', 'hard'] }],
      ensure_in: ['Mail', 'Heaven'],
    },
  });
  assert.equal(panel.saveScriptDialogVisible.value, false);

  panel.recordedCode.value = '\nfrom tasks.task_register import register_task as author_task\n'
    + '@author_task(debug=True, ensure_in=None)\ndef task():\n    pass\n\n';
  panel.saveScriptForm.value.ensureIn = [];
  panel.saveScriptForm.value.params[0].enum_options = 'Invalid stale form field';
  await panel.saveCustomScript();
  assert.equal(panel.saveScriptSelfRegistered.value, true);
  await panel.submitSaveCustomScript();
  assert.equal(saveRequests()[1].body.code, panel.recordedCode.value);
  assert.equal(Object.hasOwn(saveRequests()[1].body.metadata, 'ensure_in'), false);

  panel.recordedCode.value = '@task_register.register_task()\ndef task():\n    pass';
  saveResponse = { ok: false, error: 'ensure_in is required before saving', code: 'invalid_payload' };
  await panel.saveCustomScript();
  await panel.submitSaveCustomScript();
  assert.equal(panel.saveScriptDialogVisible.value, true, 'Server rejection must leave the form visible');
  assert.match(errors.at(-1), /ensure_in/);

  await panel.stopCustomCodeExecution();
  assert.deepEqual(plain(requests.at(-1)), {
    method: 'POST', url: '/editor/execute-code/stop', body: {},
  }, 'Save metadata must not leak into other editor requests');

  navigationResponse = { ok: false, error: 'Navigation registry unavailable' };
  const secondPanel = virtualMachine.runInContext('EditorPanel.setup({}, { emit() {} })', context);
  secondPanel.recordedCode.value = 'pass';
  secondPanel.saveScriptForm.value.taskPathTail = 'AnotherTask';
  await secondPanel.saveCustomScript();
  assert.match(errors.at(-1), /Navigation registry unavailable/);
  assert.deepEqual(plain(secondPanel.saveScriptForm.value.ensureIn), []);
  const savedCount = saveRequests().length;
  await secondPanel.submitSaveCustomScript();
  assert.equal(saveRequests().length, savedCount);
  console.log('Editor task start metadata checks passed');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
