/**
 * PythonCodeEditor - Vue wrapper around CodeMirror 5 with textarea fallback.
 */
const PythonCodeEditor = {
  name: 'PythonCodeEditor',
  props: {
    modelValue: { type: String, default: '' },
    placeholder: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  template: `
<div class="python-code-editor" :class="{ 'is-codemirror': usingCodeMirror }">
  <div class="python-code-editor-toolbar">
    <span class="python-code-editor-lang">Python</span>
    <span class="python-code-editor-hint">{{ usingCodeMirror ? 'CodeMirror 5 / Tab 缩进' : 'Textarea fallback / Tab 缩进' }}</span>
  </div>
  <textarea ref="textarea"
            class="python-code-editor-input"
            spellcheck="false"
            autocomplete="off"
            autocorrect="off"
            autocapitalize="off"
            :value="modelValue"
            :placeholder="placeholder"
            @input="onInput"
            @keydown="onFallbackKeydown"></textarea>
</div>`,
  setup(props, { emit, expose }) {
    const { ref, nextTick, onMounted, onBeforeUnmount, watch } = Vue;
    const textarea = ref(null);
    const usingCodeMirror = ref(false);
    let cm = null;
    let updatingFromCodeMirror = false;

    function emitValue(value) {
      emit('update:modelValue', value || '');
    }

    function onInput(e) {
      if (!cm) emitValue(e.target.value || '');
    }

    function applyFallbackTab(e) {
      if (e.key !== 'Tab') return false;
      e.preventDefault();
      const ta = textarea.value;
      if (!ta) return true;
      const cur = props.modelValue || '';
      const start = ta.selectionStart || 0;
      const end = ta.selectionEnd || start;
      const hasSelection = end > start;
      const lineStart = cur.lastIndexOf('\n', start - 1) + 1;
      const lineEnd = hasSelection ? cur.indexOf('\n', end - 1) : cur.indexOf('\n', start);
      const blockEnd = lineEnd === -1 ? cur.length : lineEnd;
      const block = cur.slice(lineStart, blockEnd);
      const lines = block.split('\n');

      if (e.shiftKey) {
        let removedBeforeStart = 0;
        let removedTotal = 0;
        const nextBlock = lines.map((line, idx) => {
          const remove = line.startsWith('    ') ? 4 : (line.startsWith('\t') ? 1 : 0);
          if (idx === 0) removedBeforeStart = remove;
          removedTotal += remove;
          return remove ? line.slice(remove) : line;
        }).join('\n');
        emitValue(cur.slice(0, lineStart) + nextBlock + cur.slice(blockEnd));
        nextTick(() => setSelection(Math.max(lineStart, start - removedBeforeStart), Math.max(lineStart, end - removedTotal)));
        return true;
      }

      const nextBlock = lines.map(line => '    ' + line).join('\n');
      emitValue(cur.slice(0, lineStart) + nextBlock + cur.slice(blockEnd));
      nextTick(() => setSelection(start + 4, end + 4 * lines.length));
      return true;
    }

    function onFallbackKeydown(e) {
      if (!cm) applyFallbackTab(e);
    }

    function initCodeMirror() {
      if (!textarea.value || !window.CodeMirror) return;
      cm = window.CodeMirror.fromTextArea(textarea.value, {
        mode: 'python',
        lineNumbers: true,
        indentUnit: 4,
        tabSize: 4,
        indentWithTabs: false,
        lineWrapping: false,
        matchBrackets: true,
        autoCloseBrackets: true,
        extraKeys: {
          Tab(editor) {
            if (editor.somethingSelected()) editor.indentSelection('add');
            else editor.replaceSelection('    ', 'end');
          },
          'Shift-Tab'(editor) {
            editor.indentSelection('subtract');
          },
        },
      });
      cm.setValue(props.modelValue || '');
      cm.on('change', (editor) => {
        updatingFromCodeMirror = true;
        emitValue(editor.getValue());
        nextTick(() => { updatingFromCodeMirror = false; });
      });
      usingCodeMirror.value = true;
      nextTick(() => cm && cm.refresh());
    }

    function focus() {
      if (cm) cm.focus();
      else if (textarea.value) textarea.value.focus();
    }

    function setSelection(start, end = start) {
      if (cm) {
        const from = cm.posFromIndex(start);
        const to = cm.posFromIndex(end);
        cm.focus();
        cm.setSelection(from, to);
        return;
      }
      const ta = textarea.value;
      if (!ta) return;
      ta.focus();
      ta.setSelectionRange(start, end);
    }

    function focusAtIndex(index) {
      setSelection(index, index);
    }

    watch(() => props.modelValue, (value) => {
      if (!cm || updatingFromCodeMirror) return;
      const next = value || '';
      if (cm.getValue() !== next) cm.setValue(next);
    });

    onMounted(initCodeMirror);
    onBeforeUnmount(() => {
      if (cm) {
        cm.toTextArea();
        cm = null;
      }
    });

    expose({ focus, setSelection, focusAtIndex, textarea });
    return { textarea, usingCodeMirror, onInput, onFallbackKeydown };
  },
};
