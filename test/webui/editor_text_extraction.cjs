const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const requests = [];
const notifications = [];
const context = vm.createContext({
  EditorCanvas: {}, EditorControls: {}, PythonCodeEditor: {}, EditorMenuBar: {}, EditorTutorial: {},
  Vue: {
    ref: value => ({ value }),
    computed: getter => ({ get value() { return getter(); } }),
    watch() {}, onMounted() {}, onBeforeUnmount() {}, nextTick: callback => callback(),
  },
  ElementPlus: {
    ElMessage: { success() {}, warning() {}, error: message => assert.fail(message) },
    ElNotification: notification => notifications.push(notification),
  },
  window: { WebUIApi: {
    async request(method, url, body) {
      requests.push({ method, url, body });
      assert.equal(url, '/editor/preview-extract');
      return { data: { ok: true, info: body.post_process === 'prenum' ? 0 : 'preview' } };
    },
  } },
});
vm.runInContext(fs.readFileSync(path.resolve(
  __dirname, '../../backend/webui/static/js/components/editor/EditorPanel.js',
), 'utf8'), context);
const panel = vm.runInContext('EditorPanel.setup({}, { emit() {} })', context);

async function main() {
  const groups = panel.recorderMenuGroups.value;
  const operations = groups.find(group => group.label === '操作');
  const extraction = operations.items.find(item => item.key === 'extract');
  const recognition = groups.find(group => group.label === '定位').items
    .find(item => item.key === 'region-recognition');
  assert.equal(recognition.children.some(item => item.key === 'extract-text'), false);
  assert.deepEqual(Array.from(extraction.children, item => item.label),
    ['文字', '前缀文本', '后缀文本', '前缀数字', '后缀数字', '颜色']);
  assert.equal(extraction.children[0].disabled(), true);
  panel.optimizedSel.value = { left: 1, top: 2, right: 11, bottom: 22 };

  const generated = [];
  for (const [index, processor] of ['strip', 'pretext', 'posttext', 'prenum', 'postnum'].entries()) {
    for (const inFunction of [false, true]) {
      panel.functionEditorDialogVisible.value = inFunction;
      const model = inFunction ? panel.functionEditorCode : panel.recordedCode;
      model.value = '';
      assert.equal(extraction.children[index].disabled(), false);
      await extraction.children[index].action();
      const postProcess = processor === 'strip' ? 'lambda text: text.strip()' : processor;
      assert.equal(model.value.trim(),
        `info = extract_info(B(1,2,10,20), post_process=${postProcess}, ensure_not_empty=True, mode="text")`);
      assert.equal(requests.at(-1).body.post_process, processor);
      assert.equal(panel.extractPreviewLoading.value, false);
      if (processor === 'prenum') assert.equal(notifications.at(-1).message, '0');
      generated.push({ processor, code: model.value.trim() });
    }
  }
  // Return real generated snippets for Python execution/namespace checks.
  console.log(JSON.stringify(generated));
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
