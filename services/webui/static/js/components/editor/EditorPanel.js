/**
 * EditorPanel – WebUI 图片编辑器 + 操作录制主面板
 *
 * 左侧 1/4：图片编辑器控件 + 遥控器
 * 右侧 3/4：横向图 → Canvas 上 + 代码区下；纵向图 → Canvas 右 + 代码区左
 */
const EditorPanel = {
  name: 'EditorPanel',
  components: { EditorCanvas, EditorControls },
  template: `
<div class="flex flex-col lg:flex-row gap-3 h-full min-h-0">
  <!-- 左侧：上下分栏 -->
  <div class="lg:w-1/4 flex flex-col gap-3 min-h-0">

    <!-- 上：图片编辑器 -->
    <div class="bg-white rounded-xl shadow-md p-4 flex flex-col overflow-hidden min-h-0 flex-1 editor-panel-sidebar">
      <div class="flex justify-between items-center mb-3">
        <h2 class="text-base font-semibold text-dark">图片编辑器</h2>
      </div>
      <div class="flex flex-wrap gap-2 mb-3">
        <el-button type="primary" size="default" @click="refreshScreenshot" :loading="loadingScreenshot">
          <i class="fa fa-camera mr-1"></i>刷新截图
        </el-button>
        <el-button size="default" @click="triggerImportImage" :loading="loadingImport" :disabled="loadingScreenshot">
          <i class="fa fa-picture-o mr-1"></i>导入图片
        </el-button>
        <input ref="importFileInput" type="file" accept="image/*" class="hidden" @change="onImportFileChange" />
        <el-button size="default" @click="saveSelection" :disabled="!selection">
          <i class="fa fa-save mr-1"></i>保存选区
        </el-button>
      </div>
      <p class="text-xs text-gray-400 mb-2">可将图片拖入右侧画布加载，或点击「导入图片」选择文件（离线标注 / 调试图）。</p>
      <div class="flex-1 overflow-y-auto pr-1">
        <editor-controls
          v-model:name="name"
          v-model:freeze-name="freezeName"
          v-model:free-x="freeX"
          v-model:free-y="freeY"
          v-model:use-image="useImage"
          v-model:only-ocr="onlyOcr"
          v-model:lock-color="lockColor"
          v-model:threshold="threshold"
          :center-text="centerText"
          :box-text="boxText"
          :t-code="tCode"
          :i-code="iCode"
          :color-text="colorText"
          :name-ok="nameOk"
          :image-ok="imageOk"
          @copy="onCopy"
          @threshold-release="onThresholdRelease" />
      </div>
    </div>

    <!-- 下：遥控器 -->
    <div class="bg-white rounded-xl shadow-md p-4 flex flex-col editor-panel-remote">
      <div class="flex justify-between items-center mb-3 flex-shrink-0">
        <h2 class="text-base font-semibold text-dark">
          <i class="fa fa-gamepad mr-1 text-gray-400"></i>遥控器
        </h2>
        <button type="button"
                class="text-primary hover:text-primary/80 text-sm inline-flex items-center shrink-0 disabled:opacity-50"
                :disabled="loadingScreenshot"
                @click="refreshScreenshot">
          <i class="fa fa-refresh mr-1"></i>刷新
        </button>
      </div>
      <div class="flex flex-col gap-2">
        <el-button type="primary" size="small"
                   @click="remoteClick" :disabled="!optimizedSel" :loading="remoteLoading"
                   class="w-full editor-remote-click-btn">
          <i class="fa fa-mouse-pointer mr-1"></i>点击
        </el-button>
        <div class="flex items-center gap-2">
          <el-radio-group v-model="swipeDir" size="small" class="remote-dir-group">
            <el-radio-button label="up"><i class="fa fa-arrow-up"></i></el-radio-button>
            <el-radio-button label="down"><i class="fa fa-arrow-down"></i></el-radio-button>
            <el-radio-button label="left"><i class="fa fa-arrow-left"></i></el-radio-button>
            <el-radio-button label="right"><i class="fa fa-arrow-right"></i></el-radio-button>
          </el-radio-group>
          <el-button size="small" plain :disabled="!optimizedSel" :loading="remoteLoading"
                     @click="remoteSwipe" class="flex-1">
            <i class="fa fa-hand-pointer-o mr-1"></i>滑动
          </el-button>
        </div>
        <div class="mt-2 pt-2 border-t border-slate-200 flex flex-col gap-1.5">
          <span class="text-xs text-gray-500">自定义代码执行</span>
          <el-input type="textarea" v-model="customExecCode" size="small"
            :autosize="{ minRows: 6, maxRows: 18 }"
            placeholder="如 click(B(100,200,10,10))；多行末尾可写 __result__ = 值 作为返回值"
            class="editor-custom-exec-input" />
          <el-button size="small"
            @click="executeCustomCode" :loading="execCustomLoading"
            :disabled="!customExecCode.trim()"
            class="w-full editor-custom-exec-run-btn">
            <i class="fa fa-terminal mr-1"></i>执行
          </el-button>
        </div>
      </div>
    </div>

  </div>

  <!-- 右侧：Canvas + 操作录制 -->
  <div class="lg:w-3/4 flex min-h-0 gap-3 editor-right-zone" :class="isLandscape ? 'flex-col' : 'flex-row'">

    <!-- Canvas 画布（拖放图片至此区域以导入） -->
    <div class="bg-white rounded-xl shadow-md p-3 overflow-hidden flex items-center justify-center min-h-0 min-w-0 editor-canvas-cell transition-shadow"
         :class="[isLandscape ? 'shrink-0' : 'order-2 flex-1', canvasDropActive ? 'ring-2 ring-primary ring-inset' : '']"
         :style="canvasCellStyle"
         @dragover.prevent="onCanvasDragOver"
         @dragleave="onCanvasDragLeave"
         @drop.prevent="onCanvasDrop">
      <editor-canvas
        :image-src="imageSrc"
        :selection="optimizedSel"
        :locate-boxes="locateBoxes"
        :img-width="imgWidth"
        :img-height="imgHeight"
        @selection-change="onSelectionChange"
        @canvas-remote-click="onCanvasRemoteClick"
        @canvas-remote-swipe="onCanvasRemoteSwipe" />
    </div>

    <!-- 操作录制区 -->
    <div class="bg-white rounded-xl shadow-md p-4 flex min-h-0 min-w-0 editor-recorder-zone"
         :class="isLandscape ? 'flex-1 flex-row gap-3' : 'order-1 flex-col gap-3'"
         :style="!isLandscape ? 'width:45%;min-width:280px' : ''">
      <div class="flex flex-col flex-1 min-h-0 min-w-0">
        <div class="flex items-center justify-between mb-2 shrink-0">
          <h2 class="text-sm font-semibold text-dark">
            <i class="fa fa-circle text-red-400 mr-1" style="font-size:8px"></i>操作录制
          </h2>
          <span class="text-xs text-gray-400">{{ recordedLines.length }} 行</span>
        </div>
        <el-input type="textarea" v-model="recordedCode" class="flex-1 editor-code-textarea"
                  :autosize="false" resize="none"
                  placeholder="操作后代码将自动生成…" />
      </div>
      <div class="flex shrink-0 editor-recorder-actions"
           :class="isLandscape ? 'flex-col gap-2 justify-start' : 'flex-row flex-wrap gap-2 justify-end items-center'"
           :style="isLandscape ? 'width:120px' : ''">
        <el-button size="small" @click="copyRecordedCode" :disabled="!recordedCode.trim()">
          <i class="fa fa-copy mr-1"></i>复制代码
        </el-button>
        <el-button size="small" type="danger" plain @click="recordedCode=''" :disabled="!recordedCode.trim()">
          <i class="fa fa-trash-o mr-1"></i>清空
        </el-button>
        <el-button size="small" plain @click="appendWaitAppear" :disabled="!optimizedSel">
          等待出现
        </el-button>
        <el-button size="small" plain @click="appendWaitDisappear" :disabled="!optimizedSel">
          等待消失
        </el-button>
        <el-button size="small" plain @click="appendExtractInfo" :disabled="!optimizedSel" :loading="extractPreviewLoading">
          提取信息
        </el-button>
        <el-button size="small" plain @click="appendSleepWait">
          阻塞等待
        </el-button>
      </div>
    </div>

  </div>
</div>`,

  setup() {
    const { ref, computed, watch } = Vue;

    // ── state ──
    const imageSrc = ref('');
    const imgWidth = ref(1280);
    const imgHeight = ref(720);
    const loadingScreenshot = ref(false);
    const loadingImport = ref(false);
    const importFileInput = ref(null);
    const canvasDropActive = ref(false);

    const selection = ref(null);
    const optimizedSel = ref(null);
    const locateBoxes = ref([]);

    const name = ref('');
    const freezeName = ref(false);
    const freeX = ref(false);
    const freeY = ref(false);
    const useImage = ref(false);
    const onlyOcr = ref(false);
    const lockColor = ref(false);
    const threshold = ref(100);

    const colorText = ref('');
    const nameOk = ref({});
    const imageOk = ref({});

    // ── remote control state ──
    const swipeDir = ref('down');
    const remoteLoading = ref(false);
    const customExecCode = ref('');
    const execCustomLoading = ref(false);
    const extractPreviewLoading = ref(false);

    // ── recorded code ──
    const recordedCode = ref('');
    const recordedLines = computed(() => recordedCode.value.split('\n').filter(l => l.trim()));

    // ── layout ──
    const isLandscape = computed(() => imgWidth.value >= imgHeight.value);

    const canvasCellStyle = computed(() => {
      if (isLandscape.value) {
        const ratio = imgHeight.value / imgWidth.value;
        return { aspectRatio: `${imgWidth.value}/${imgHeight.value}`, width: '100%', maxHeight: '55%' };
      }
      return {};
    });

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
      return `${Math.floor((s.left + s.right) / 2)},${Math.floor((s.top + s.bottom) / 2)}`;
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

    // ── code generation helpers ──
    function buildTarget() {
      const b = effectiveBox();
      const t = (name.value || '').trim();
      if (t) {
        if (useImage.value) return iCode.value;
        return tCode.value;
      }
      if (b) return `B(${b.left},${b.top},${b.width},${b.height})`;
      return null;
    }

    function appendCode(line) {
      if (!line) return;
      const cur = recordedCode.value;
      recordedCode.value = cur ? cur + '\n' + line : line;
    }

    /** 需有名称以生成 T/I；纯框选 B 不可用 */
    function requireTOrITarget() {
      if (!optimizedSel.value) {
        ElementPlus.ElMessage.warning('请先框选区域');
        return { ok: false };
      }
      const t = (name.value || '').trim();
      if (!t) {
        ElementPlus.ElMessage.warning('请先输入名称以生成 T 或 I 目标（纯坐标 B 无法用于此项）');
        return { ok: false };
      }
      const tgt = useImage.value ? iCode.value : tCode.value;
      if (!tgt) {
        ElementPlus.ElMessage.warning('无法生成 T 或 I 代码');
        return { ok: false };
      }
      return { ok: true, tgt };
    }

    function appendWaitAppear() {
      const r = requireTOrITarget();
      if (!r.ok) return;
      appendCode(`wait_for_appear(${r.tgt})`);
      ElementPlus.ElMessage.success('已添加「等待出现」');
    }

    function appendWaitDisappear() {
      const r = requireTOrITarget();
      if (!r.ok) return;
      appendCode(`wait_for_disappear(${r.tgt})`);
      ElementPlus.ElMessage.success('已添加「等待消失」');
    }

    /** 阻塞等待：与脚本层 sleep(1) 一致（秒） */
    function appendSleepWait() {
      appendCode('sleep(1)');
      ElementPlus.ElMessage.success('已添加「阻塞等待」sleep(1)');
    }

    /** extract_info 需 BoxTarget，代码使用当前选区 B（与 T/I 区域一致）；并请求预览结果 */
    async function appendExtractInfo() {
      const r = requireTOrITarget();
      if (!r.ok) return;
      const b = effectiveBox();
      if (!b) {
        ElementPlus.ElMessage.warning('请先框选区域');
        return;
      }
      const line = `info = extract_info(B(${b.left},${b.top},${b.width},${b.height}), post_process=lambda s: s.strip(), ensure_not_empty=True)`;
      appendCode(line);
      ElementPlus.ElMessage.success('已添加「提取信息」');
      extractPreviewLoading.value = true;
      try {
        const res = await apiPost('/preview-extract', {
          left: b.left, top: b.top, width: b.width, height: b.height,
        });
        if (!res || res.ok === false) {
          ElementPlus.ElMessage.error('预览提取失败: ' + ((res && res.error) || '?'));
          return;
        }
        const txt = res.info == null ? '(空/None)' : String(res.info);
        ElementPlus.ElNotification({
          title: '提取信息预览',
          message: txt.length > 2000 ? txt.slice(0, 2000) + '…' : txt,
          type: 'success',
          duration: 8000,
        });
      } catch (e) {
        ElementPlus.ElMessage.error('预览请求失败: ' + e);
      } finally {
        extractPreviewLoading.value = false;
      }
    }

    // ── actions ──
    /** 与 GET /screenshot、POST /ingest-image 返回结构一致时更新画布与校验状态 */
    async function applyEditorImageData(data) {
      if (data.error) { ElementPlus.ElMessage.error(data.error); return false; }
      imageSrc.value = 'data:image/jpeg;base64,' + data.image;
      imgWidth.value = data.width || 1280;
      imgHeight.value = data.height || 720;
      locateBoxes.value = [];
      nameOk.value = {};
      imageOk.value = {};
      await validateAll();
      return true;
    }

    async function refreshScreenshot() {
      loadingScreenshot.value = true;
      try {
        const data = await apiGet('/screenshot');
        await applyEditorImageData(data);
      } catch (e) {
        ElementPlus.ElMessage.error('截图失败: ' + e);
      } finally {
        loadingScreenshot.value = false;
      }
    }

    async function ingestFromDataUrl(dataUrl) {
      loadingImport.value = true;
      try {
        const data = await apiPost('/ingest-image', { image: dataUrl });
        const ok = await applyEditorImageData(data);
        if (ok) ElementPlus.ElMessage.success('已导入图片');
      } catch (e) {
        ElementPlus.ElMessage.error('导入失败: ' + e);
      } finally {
        loadingImport.value = false;
      }
    }

    function triggerImportImage() {
      importFileInput.value && importFileInput.value.click();
    }

    function loadImageFile(f) {
      if (!f || !f.type || !f.type.startsWith('image/')) {
        ElementPlus.ElMessage.warning('请选择图片文件');
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const url = reader.result;
        if (typeof url === 'string') ingestFromDataUrl(url);
      };
      reader.onerror = () => ElementPlus.ElMessage.error('读取文件失败');
      reader.readAsDataURL(f);
    }

    function onImportFileChange(e) {
      const input = e.target;
      const f = input.files && input.files[0];
      input.value = '';
      if (!f) return;
      loadImageFile(f);
    }

    function onCanvasDragOver(e) {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      canvasDropActive.value = true;
    }

    function onCanvasDragLeave(e) {
      if (e.currentTarget.contains(e.relatedTarget)) return;
      canvasDropActive.value = false;
    }

    function onCanvasDrop(e) {
      canvasDropActive.value = false;
      const dt = e.dataTransfer;
      if (!dt) return;
      const files = dt.files;
      if (files && files.length) {
        const f = Array.from(files).find((x) => x.type && x.type.startsWith('image/'));
        if (f) {
          loadImageFile(f);
          return;
        }
      }
      ElementPlus.ElMessage.warning('请拖入图片文件');
    }

    /** 遥控器/画布远程操作后：等待 0.5s 再刷新，避免截到过渡态 */
    async function refreshScreenshotAfterRemote() {
      await new Promise((r) => setTimeout(r, 500));
      await refreshScreenshot();
    }

    async function onSelectionChange(sel) {
      selection.value = { ...sel };
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

      // Store template (fire & forget, lightweight since no image payload)
      apiPost('/store-template', { left: s.left, top: s.top, right: s.right, bottom: s.bottom }).catch(() => {});

      await validateAll();
    }

    async function validateAll() {
      await Promise.all([validateLocate(), validateImage()]);
    }

    async function validateLocate() {
      const b = effectiveBox();
      const t = (name.value || '').trim();
      if (!b || !t) { nameOk.value = {}; locateBoxes.value = []; return; }
      try {
        const color = lockColor.value ? (colorText.value || null) : null;
        const data = await apiPost('/locate', {
          text: t, left: b.left, top: b.top, width: b.width, height: b.height, color,
        });
        if (data.scale_results) {
          const ok = {};
          for (const [s, r] of Object.entries(data.scale_results)) ok[s] = r.found ? '√' : 'X';
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

    async function validateImage() {
      if (!useImage.value) { imageOk.value = {}; return; }
      const b = effectiveBox();
      if (!b) { imageOk.value = {}; return; }
      try {
        const data = await apiPost('/locate-image', {
          left: b.left, top: b.top, width: b.width, height: b.height,
        });
        if (data.scale_results) {
          const ok = {};
          for (const [s, r] of Object.entries(data.scale_results)) ok[s] = r.found ? '√' : 'X';
          imageOk.value = ok;
        } else {
          imageOk.value = data.found ? { '1.0': '√' } : { '1.0': 'X' };
        }
      } catch {
        imageOk.value = {};
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
        const s = optimizedSel.value;
        const ocr = await apiPost('/ocr', { left: s.left, top: s.top, right: s.right, bottom: s.bottom });
        if (!freezeName.value || !name.value.trim()) name.value = ocr.text || '';
        const w = s.right - s.left, h = s.bottom - s.top;
        const c = await apiPost('/color', { left: s.left, top: s.top, width: w, height: h });
        colorText.value = c.color || '';
        apiPost('/store-template', { left: s.left, top: s.top, right: s.right, bottom: s.bottom }).catch(() => {});
        await validateAll();
      } catch { /* ignore */ }
    }

    watch([freeX, freeY, lockColor, name], () => {
      if (optimizedSel.value) validateAll();
    });

    watch(useImage, () => {
      if (optimizedSel.value) validateImage();
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

    // ── remote control actions ──
    async function remoteClick() {
      const s = optimizedSel.value;
      if (!s) { ElementPlus.ElMessage.warning('请先框选区域'); return; }
      const cx = Math.floor((s.left + s.right) / 2);
      const cy = Math.floor((s.top + s.bottom) / 2);

      // generate code in parallel
      const tgt = buildTarget();
      if (tgt) appendCode(`click(${tgt})`);

      remoteLoading.value = true;
      try {
        const res = await apiPost('/remote/click', { x: cx, y: cy });
        if (res.error) { ElementPlus.ElMessage.error(res.error); }
        else { ElementPlus.ElMessage.success(`已点击 (${cx}, ${cy})`); }
      } catch (e) {
        ElementPlus.ElMessage.error('点击失败: ' + e);
      } finally {
        try {
          await refreshScreenshotAfterRemote();
        } catch (_) { /* ignore */ }
        remoteLoading.value = false;
      }
    }

    /** 画布右键单击：同遥控器点击，坐标为像素点 */
    async function onCanvasRemoteClick({ x, y }) {
      appendCode(`click(B(${x},${y},1,1))`);
      remoteLoading.value = true;
      try {
        const res = await apiPost('/remote/click', { x, y });
        if (res.error) { ElementPlus.ElMessage.error(res.error); }
        else { ElementPlus.ElMessage.success(`右键点击 (${x}, ${y})`); }
      } catch (e) {
        ElementPlus.ElMessage.error('点击失败: ' + e);
      } finally {
        try { await refreshScreenshotAfterRemote(); } catch (_) { /* ignore */ }
        remoteLoading.value = false;
      }
    }

    /** 画布右键拖拽滑动：起止点与遥控器 swipe API 一致 */
    async function onCanvasRemoteSwipe({ x1, y1, x2, y2 }) {
      appendCode(`swipe(B(${x1},${y1},1,1), B(${x2},${y2},1,1))`);
      remoteLoading.value = true;
      try {
        const res = await apiPost('/remote/swipe', { x1, y1, x2, y2, duration_s: 1 });
        if (res.error) { ElementPlus.ElMessage.error(res.error); }
        else { ElementPlus.ElMessage.success('右键滑动'); }
      } catch (e) {
        ElementPlus.ElMessage.error('滑动失败: ' + e);
      } finally {
        try { await refreshScreenshotAfterRemote(); } catch (_) { /* ignore */ }
        remoteLoading.value = false;
      }
    }

    async function remoteSwipe() {
      const s = optimizedSel.value;
      if (!s) { ElementPlus.ElMessage.warning('请先框选区域'); return; }
      const cx = Math.floor((s.left + s.right) / 2);
      const cy = Math.floor((s.top + s.bottom) / 2);
      // 与「手指在屏幕上的划动方向」对齐：↑=从上往下划、↓=从下往上划；←→ 同理对调
      const dirMap = {
        up:    { x1: cx, y1: s.top,    x2: cx, y2: s.bottom },
        down:  { x1: cx, y1: s.bottom, x2: cx, y2: s.top },
        left:  { x1: s.left,  y1: cy,  x2: s.right, y2: cy },
        right: { x1: s.right, y1: cy,  x2: s.left, y2: cy },
      };
      const pts = dirMap[swipeDir.value];

      // generate code in parallel
      appendCode(`swipe(B(${pts.x1},${pts.y1},1,1), B(${pts.x2},${pts.y2},1,1))`);

      remoteLoading.value = true;
      try {
        const res = await apiPost('/remote/swipe', { ...pts, duration_s: 1 });
        if (res.error) { ElementPlus.ElMessage.error(res.error); }
        else {
          const arrow = { up: '↑', down: '↓', left: '←', right: '→' }[swipeDir.value];
          ElementPlus.ElMessage.success(`已滑动 ${arrow}`);
        }
      } catch (e) {
        ElementPlus.ElMessage.error('滑动失败: ' + e);
      } finally {
        try {
          await refreshScreenshotAfterRemote();
        } catch (_) { /* ignore */ }
        remoteLoading.value = false;
      }
    }

    function onCopy(field) {
      const map = {
        center: centerText.value, box: boxText.value,
        t: tCode.value, i: iCode.value, color: colorText.value,
      };
      const text = map[field] || '';
      if (!text) return;
      navigator.clipboard.writeText(text).then(
        () => ElementPlus.ElMessage.success('已复制'),
        () => {
          const ta = document.createElement('textarea');
          ta.value = text; document.body.appendChild(ta); ta.select();
          document.execCommand('copy'); document.body.removeChild(ta);
          ElementPlus.ElMessage.success('已复制');
        }
      );
    }

    function copyRecordedCode() {
      const text = recordedCode.value;
      if (!text) return;
      navigator.clipboard.writeText(text).then(
        () => ElementPlus.ElMessage.success('已复制代码'),
        () => {
          const ta = document.createElement('textarea');
          ta.value = text; document.body.appendChild(ta); ta.select();
          document.execCommand('copy'); document.body.removeChild(ta);
          ElementPlus.ElMessage.success('已复制代码');
        }
      );
    }

    /** 自定义代码：不写入操作录制区；成功/失败/返回值均用消息提示 */
    async function executeCustomCode() {
      const code = (customExecCode.value || '').trim();
      if (!code) { ElementPlus.ElMessage.warning('请输入代码'); return; }
      execCustomLoading.value = true;
      try {
        const res = await apiPost('/execute-code', { code });
        if (!res || res.ok === false) {
          const err = (res && res.error) ? String(res.error) : '执行失败';
          ElementPlus.ElMessage.error(err.length > 800 ? err.slice(0, 800) + '…' : err);
          return;
        }
        const parts = ['执行成功'];
        if (res.result != null && res.result !== '') parts.push(`返回值: ${res.result}`);
        if (res.stdout) parts.push(`输出: ${res.stdout}`);
        let msg = parts.join(' · ');
        if (msg.length > 600) msg = msg.slice(0, 600) + '…';
        ElementPlus.ElMessage({ message: msg, type: 'success', duration: 8000, showClose: true });
      } catch (e) {
        ElementPlus.ElMessage.error('请求失败: ' + e);
      } finally {
        execCustomLoading.value = false;
      }
    }

    return {
      imageSrc, imgWidth, imgHeight, loadingScreenshot, loadingImport, importFileInput,
      selection, optimizedSel, locateBoxes,
      name, freezeName, freeX, freeY, useImage, onlyOcr, lockColor, threshold,
      centerText, boxText, tCode, iCode, colorText, nameOk, imageOk,
      swipeDir, remoteLoading, customExecCode, execCustomLoading, extractPreviewLoading,
      recordedCode, recordedLines, isLandscape, canvasCellStyle,
      canvasDropActive,
      refreshScreenshot, triggerImportImage, onImportFileChange,
      onCanvasDragOver, onCanvasDragLeave, onCanvasDrop,
      onSelectionChange, onThresholdRelease,
      saveSelection, onCopy, remoteClick, remoteSwipe,
      onCanvasRemoteClick, onCanvasRemoteSwipe,
      copyRecordedCode, executeCustomCode,
      appendWaitAppear, appendWaitDisappear, appendSleepWait, appendExtractInfo,
    };
  },
};
