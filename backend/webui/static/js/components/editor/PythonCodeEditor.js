/**
 * PythonCodeEditor - Vue wrapper around CodeMirror 5 with textarea fallback.
 */
const PythonCodeEditor = {
  name: 'PythonCodeEditor',
  props: {
    modelValue: { type: String, default: '' },
    placeholder: { type: String, default: '' },
  },
  emits: ['update:modelValue', 'line-dblclick'],
  template: `
<div class="python-code-editor" :class="{ 'is-codemirror': usingCodeMirror }">
  <textarea ref="textarea"
            class="python-code-editor-input"
            spellcheck="false"
            autocomplete="off"
            autocorrect="off"
            autocapitalize="off"
            :value="modelValue"
            :placeholder="placeholder"
            @input="onInput"
            @dblclick="onFallbackDoubleClick"
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

    function lineInfoAtIndex(index) {
      const content = props.modelValue || '';
      const safeIndex = Math.max(0, Math.min(index || 0, content.length));
      const lineStart = content.lastIndexOf('\n', safeIndex - 1) + 1;
      const nextBreak = content.indexOf('\n', safeIndex);
      const lineEnd = nextBreak === -1 ? content.length : nextBreak;
      const lineNumber = content.slice(0, lineStart).split('\n').length - 1;
      return {
        line: content.slice(lineStart, lineEnd),
        lineNumber,
        index: safeIndex,
        lineStart,
        lineEnd,
      };
    }

    function emitLineDoubleClick(info) {
      emit('line-dblclick', info);
    }

    function onFallbackDoubleClick(event) {
      if (cm) return;
      const target = event && event.target;
      if (!target) return;
      emitLineDoubleClick(lineInfoAtIndex(target.selectionStart || 0));
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
      cm.on('dblclick', (editor, event) => {
        if (!event) return;
        const cursor = editor.coordsChar({ left: event.clientX, top: event.clientY });
        const lineStart = editor.indexFromPos({ line: cursor.line, ch: 0 });
        const lineEnd = editor.indexFromPos({ line: cursor.line, ch: (editor.getLine(cursor.line) || '').length });
        emitLineDoubleClick({
          line: editor.getLine(cursor.line) || '',
          lineNumber: cursor.line,
          index: editor.indexFromPos(cursor),
          lineStart,
          lineEnd,
        });
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

    function getSelectionRange() {
      if (cm) {
        return {
          start: cm.indexFromPos(cm.getCursor('from')),
          end: cm.indexFromPos(cm.getCursor('to')),
        };
      }
      const ta = textarea.value;
      if (!ta) return null;
      const start = ta.selectionStart || 0;
      const end = ta.selectionEnd || start;
      return { start, end };
    }

    function replaceRange(start, end, text) {
      const content = props.modelValue || '';
      const safeStart = Math.max(0, Math.min(start || 0, content.length));
      const safeEnd = Math.max(safeStart, Math.min(end || safeStart, content.length));
      const replacement = text || '';
      if (cm) {
        cm.replaceRange(replacement, cm.posFromIndex(safeStart), cm.posFromIndex(safeEnd), 'autoscriptor-menu');
        setSelection(safeStart + replacement.length, safeStart + replacement.length);
        return;
      }
      emitValue(content.slice(0, safeStart) + replacement + content.slice(safeEnd));
      nextTick(() => setSelection(safeStart + replacement.length, safeStart + replacement.length));
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

    expose({ focus, setSelection, focusAtIndex, getSelectionRange, replaceRange, textarea });
    return { textarea, usingCodeMirror, onInput, onFallbackDoubleClick, onFallbackKeydown };
  },
};
