/**
 * EditorPanel – WebUI 图片编辑器主面板
 * 左右分栏布局：左侧控制面板(1/3)，右侧 Canvas 画布(2/3)，固定 600px 高度。
 */
const EditorPanel = {
  name: 'EditorPanel',
  components: { EditorCanvas, EditorControls },
  template: `
<div class="flex flex-col lg:flex-row gap-4 h-full min-h-0">
  <!-- 左侧：控制面板 -->
  <div class="lg:w-1/3 bg-white rounded-xl shadow-md p-6 flex flex-col overflow-hidden min-h-0 editor-panel-sidebar">
    <div class="flex justify-between items-center mb-5">
      <h2 class="text-2xl font-semibold text-dark">图片编辑器</h2>
    </div>
    <div class="flex flex-wrap gap-4 mb-6">
      <el-button type="primary" size="large" @click="refreshScreenshot" :loading="loadingScreenshot">
        <i class="fa fa-camera mr-2"></i>刷新截图
      </el-button>
      <el-button size="large" @click="saveSelection" :disabled="!selection">
        <i class="fa fa-save mr-2"></i>保存选区
      </el-button>
    </div>
    <div class="flex-1 overflow-y-auto pr-1">
      <editor-controls
        v-model:name="name"
        v-model:freeze-name="freezeName"
        v-model:free-x="freeX"
        v-model:free-y="freeY"
        v-model:only-ocr="onlyOcr"
        v-model:lock-color="lockColor"
        v-model:threshold="threshold"
        :center-text="centerText"
        :box-text="boxText"
        :t-code="tCode"
        :i-code="iCode"
        :color-text="colorText"
        :name-ok="nameOk"
        @copy="onCopy"
        @threshold-release="onThresholdRelease" />
    </div>
  </div>

  <!-- 右侧：Canvas 画布 -->
  <div class="lg:w-2/3 bg-white rounded-xl shadow-md p-4 overflow-hidden flex items-center justify-center min-h-0">
    <editor-canvas
      :image-src="imageSrc"
      :selection="optimizedSel"
      :locate-boxes="locateBoxes"
      :img-width="imgWidth"
      :img-height="imgHeight"
      @selection-change="onSelectionChange" />
  </div>
</div>`,

  setup() {
    const { ref, computed, watch } = Vue;

    // ── state ──
    const imageSrc = ref('');
    const imgWidth = ref(1280);
    const imgHeight = ref(720);
    const loadingScreenshot = ref(false);

    const selection = ref(null);       // raw selection from mouse {left,top,right,bottom}
    const optimizedSel = ref(null);    // after optimize-rect
    const locateBoxes = ref([]);

    const name = ref('');
    const freezeName = ref(false);
    const freeX = ref(false);
    const freeY = ref(false);
    const onlyOcr = ref(false);
    const lockColor = ref(false);
    const threshold = ref(100);

    const colorText = ref('');
    const nameOk = ref({});

    // ── derived ──
    function effectiveBox() {
      const s = optimizedSel.value;
      if (!s) return null;
      let left = s.left, top = s.top;
      let w = s.right - s.left, h = s.bottom - s.top;
      if (freeX.value) { left = 0; w = 1280; }
      if (freeY.value) { top = 0; h = 720; }
      return { left, top, width: w, height: h };
    }

    const centerText = computed(() => {
      const s = optimizedSel.value;
      if (!s) return '';
      const cx = Math.floor((s.left + s.right) / 2);
      const cy = Math.floor((s.top + s.bottom) / 2);
      return `${cx},${cy}`;
    });

    const boxText = computed(() => {
      const b = effectiveBox();
      if (!b) return '';
      return `Box(${b.left},${b.top},${b.width},${b.height})`;
    });

    function escapeText(s) {
      return (s || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"').trim();
    }

    const tCode = computed(() => {
      const b = effectiveBox();
      if (!b) return '';
      const t = escapeText(name.value);
      let boxPart = `, box=Box(${b.left},${b.top},${b.width},${b.height}).margin()`;
      if (b.left === 0 && b.top === 0 && b.width === 1280 && b.height === 720) boxPart = '';
      let colorPart = '';
      if (lockColor.value && colorText.value) colorPart = `, color="${escapeText(colorText.value)}"`;
      return `T("${t}"${boxPart}${colorPart})`;
    });

    const iCode = computed(() => {
      const b = effectiveBox();
      if (!b) return '';
      const t = escapeText(name.value);
      let boxPart = `, box=Box(${b.left},${b.top},${b.width},${b.height}).margin()`;
      if (b.left === 0 && b.top === 0 && b.width === 1280 && b.height === 720) boxPart = '';
      let colorPart = '';
      if (lockColor.value && colorText.value) colorPart = `, color="${escapeText(colorText.value)}"`;
      return `I("${t}"${boxPart}${colorPart})`;
    });

    // ── API helpers ──
    async function apiGet(url) { return (await fetch('/api/editor' + url)).json(); }
    async function apiPost(url, body) {
      return (await fetch('/api/editor' + url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })).json();
    }

    // ── actions ──
    async function refreshScreenshot() {
      loadingScreenshot.value = true;
      try {
        const data = await apiGet('/screenshot');
        if (data.error) { ElementPlus.ElMessage.error(data.error); return; }
        imageSrc.value = 'data:image/jpeg;base64,' + data.image;
        imgWidth.value = data.width || 1280;
        imgHeight.value = data.height || 720;
        selection.value = null;
        optimizedSel.value = null;
        locateBoxes.value = [];
        nameOk.value = {};
        if (!freezeName.value) name.value = '';
        colorText.value = '';
      } catch (e) {
        ElementPlus.ElMessage.error('截图失败: ' + e);
      } finally {
        loadingScreenshot.value = false;
      }
    }

    async function onSelectionChange(sel) {
      selection.value = { ...sel };
      // optimize rect
      try {
        const opt = await apiPost('/optimize-rect', {
          left: sel.left, top: sel.top, right: sel.right, bottom: sel.bottom,
          threshold: threshold.value,
        });
        optimizedSel.value = { left: opt.left, top: opt.top, right: opt.right, bottom: opt.bottom };
      } catch {
        optimizedSel.value = { ...sel };
      }

      const s = optimizedSel.value;
      // OCR
      try {
        const ocr = await apiPost('/ocr', { left: s.left, top: s.top, right: s.right, bottom: s.bottom });
        if (!freezeName.value || !name.value.trim()) {
          name.value = ocr.text || '';
        }
      } catch { /* ignore */ }

      // Color
      try {
        const w = s.right - s.left, h = s.bottom - s.top;
        const c = await apiPost('/color', { left: s.left, top: s.top, width: w, height: h });
        colorText.value = c.color || '';
      } catch { /* ignore */ }

      // Locate validation
      await validateLocate();
    }

    async function validateLocate() {
      const b = effectiveBox();
      const t = (name.value || '').trim();
      if (!b || !t) {
        nameOk.value = {};
        locateBoxes.value = [];
        return;
      }
      try {
        const color = lockColor.value ? (colorText.value || null) : null;
        const data = await apiPost('/locate', {
          text: t, left: b.left, top: b.top, width: b.width, height: b.height, color,
        });
        if (data.scale_results) {
          const ok = {};
          for (const [s, r] of Object.entries(data.scale_results)) {
            ok[s] = r.found ? '√' : 'X';
          }
          nameOk.value = ok;
        } else {
          nameOk.value = data.found ? { '1.0': '√' } : { '1.0': 'X' };
        }
        locateBoxes.value = data.boxes || [];
      } catch {
        nameOk.value = {};
        locateBoxes.value = [];
      }
    }

    async function onThresholdRelease() {
      if (!selection.value) return;
      const sel = selection.value;
      try {
        const opt = await apiPost('/optimize-rect', {
          left: sel.left, top: sel.top, right: sel.right, bottom: sel.bottom,
          threshold: threshold.value,
        });
        optimizedSel.value = { left: opt.left, top: opt.top, right: opt.right, bottom: opt.bottom };

        // re-run OCR + color + locate
        const s = optimizedSel.value;
        const ocr = await apiPost('/ocr', { left: s.left, top: s.top, right: s.right, bottom: s.bottom });
        if (!freezeName.value || !name.value.trim()) name.value = ocr.text || '';
        const w = s.right - s.left, h = s.bottom - s.top;
        const c = await apiPost('/color', { left: s.left, top: s.top, width: w, height: h });
        colorText.value = c.color || '';
        await validateLocate();
      } catch { /* ignore */ }
    }

    // Re-validate when toggles that affect effective box change
    watch([freeX, freeY, lockColor, name], () => {
      if (optimizedSel.value) validateLocate();
    });

    async function saveSelection() {
      const b = effectiveBox();
      if (!b) { ElementPlus.ElMessage.warning('请先框选区域'); return; }
      if (!name.value.trim()) { ElementPlus.ElMessage.warning('名称不能为空'); return; }
      try {
        const data = await apiPost('/save', {
          name: name.value.trim(),
          left: b.left, top: b.top, width: b.width, height: b.height,
          free_x: freeX.value, free_y: freeY.value, only_ocr: onlyOcr.value,
        });
        if (data.error) { ElementPlus.ElMessage.error(data.error); return; }
        ElementPlus.ElMessage.success(data.message || '保存成功');
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败: ' + e);
      }
    }

    function onCopy(field) {
      const map = {
        center: centerText.value,
        box: boxText.value,
        t: tCode.value,
        i: iCode.value,
        color: colorText.value,
      };
      const text = map[field] || '';
      if (!text) return;
      navigator.clipboard.writeText(text).then(
        () => ElementPlus.ElMessage.success('已复制'),
        () => {
          const ta = document.createElement('textarea');
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          ElementPlus.ElMessage.success('已复制');
        }
      );
    }

    return {
      imageSrc, imgWidth, imgHeight, loadingScreenshot,
      selection, optimizedSel, locateBoxes,
      name, freezeName, freeX, freeY, onlyOcr, lockColor, threshold,
      centerText, boxText, tCode, iCode, colorText, nameOk,
      refreshScreenshot, onSelectionChange, onThresholdRelease,
      saveSelection, onCopy,
    };
  },
};
