/**
 * EditorPanel – WebUI 图片编辑器 + 操作录制主面板
 *
 * 左侧 1/4：图片编辑器控件 + 遥控器
 * 右侧 3/4：横向图 → Canvas 上 + 代码区下；纵向图 → Canvas 右 + 代码区左
 */
const EDITOR_DRAFT_CACHE = {
  recordedCode: '',
  customExecCode: '',
};

const EditorPanel = {
  name: 'EditorPanel',
  components: { EditorCanvas, EditorControls },
  props: {
    /** 由错误汇总等页设置：切换到编辑器后从此 URL 拉取图片并走 /ingest-image */
    pendingImportUrl: { type: String, default: '' },
  },
  emits: ['imported'],
  template: `
<div class="h-full min-h-0">
<div class="flex flex-col lg:flex-row gap-3 h-full min-h-0">
  <!-- 左侧：上下分栏 -->
  <div class="lg:w-1/4 flex flex-col gap-3 min-h-0">

    <!-- 上：图片编辑器 -->
    <div class="bg-white rounded-xl shadow-md p-4 flex flex-col overflow-hidden min-h-0 flex-1 editor-panel-sidebar">
      <div class="flex justify-between items-center mb-2">
        <div class="flex items-center gap-1.5 min-w-0">
          <h2 class="text-base font-semibold text-dark shrink-0">图片编辑器</h2>
          <el-tooltip placement="top" :show-after="0">
            <template #content>
              <div class="max-w-[280px] text-xs leading-relaxed text-left">
                可将图片<strong>拖入右侧画布</strong>加载，用于离线标注与调试图；也可使用「刷新截图」获取当前模拟器画面。
              </div>
            </template>
            <i class="fa fa-info-circle editor-help-icon shrink-0" tabindex="0" aria-label="说明" role="img"></i>
          </el-tooltip>
        </div>
      </div>
      <div class="flex flex-nowrap gap-1.5 mb-2">
        <el-button type="primary" size="small" class="!flex-1 min-w-0" @click="refreshScreenshot" :loading="loadingScreenshot">
          <i class="fa fa-camera mr-0.5"></i><span class="truncate">刷新截图</span>
        </el-button>
        <el-button size="small" class="!flex-1 min-w-0" @click="saveSelection" :disabled="!selection">
          <i class="fa fa-save mr-0.5"></i><span class="truncate">保存选区</span>
        </el-button>
      </div>
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
        <div class="flex items-center gap-2">
          <el-button type="primary" size="small"
                     @click="remoteClick" :disabled="!optimizedSel" :loading="remoteLoading"
                     class="flex-1 min-w-0 editor-remote-click-btn">
            <i class="fa fa-mouse-pointer mr-1"></i>点击
          </el-button>
          <el-tooltip placement="top" :show-after="0">
            <template #content>
              <div class="max-w-[268px] text-xs leading-relaxed text-left space-y-2">
                <p>按当前选区生成 <strong>B/T/I</strong> 点击代码；有名称时优先用 T/I，只有框选无文字时用完整 B 区域。</p>
                <p>操作会<strong>追加到下方录制区</strong>。<strong>模拟模式</strong>下只在画布上标红点，不下发模拟器。</p>
              </div>
            </template>
            <i class="fa fa-info-circle editor-help-icon shrink-0" tabindex="0" aria-label="点击说明" role="img"></i>
          </el-tooltip>
        </div>
        <div class="flex items-center gap-2">
          <div class="flex flex-1 min-w-0 items-center gap-1.5">
            <el-radio-group v-model="swipeDir" size="small" class="remote-dir-group flex-1 min-w-0">
              <el-radio-button label="up"><i class="fa fa-arrow-up"></i></el-radio-button>
              <el-radio-button label="down"><i class="fa fa-arrow-down"></i></el-radio-button>
              <el-radio-button label="left"><i class="fa fa-arrow-left"></i></el-radio-button>
              <el-radio-button label="right"><i class="fa fa-arrow-right"></i></el-radio-button>
            </el-radio-group>
            <el-button size="small" plain :disabled="!optimizedSel" :loading="remoteLoading"
                       @click="remoteSwipe" class="shrink-0">
              <i class="fa fa-hand-pointer-o mr-1"></i>滑动
            </el-button>
          </div>
          <el-tooltip placement="top" :show-after="0">
            <template #content>
              <div class="max-w-[280px] text-xs leading-relaxed text-left space-y-2">
                <p>在选区<strong>内部</strong>沿箭头方向滑动；箭头表示<strong>手指在屏幕上的移动方向</strong>（如「→」= 从左向右滑）。</p>
                <p>会写入录制区。<strong>模拟模式</strong>下只在画布上画蓝线，不下发模拟器。</p>
              </div>
            </template>
            <i class="fa fa-info-circle editor-help-icon shrink-0" tabindex="0" aria-label="滑动说明" role="img"></i>
          </el-tooltip>
        </div>
        <div class="mt-2 pt-2 border-t border-slate-200 flex flex-col gap-2">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-xs text-gray-500 shrink-0">遥控模式</span>
            <el-tooltip placement="top" :show-after="0">
              <template #content>
                <div class="max-w-[300px] text-xs leading-relaxed text-left space-y-2">
                  <p><strong>执行</strong>：遥控器、画布右键与「自定义代码」里的触控会<strong>发到模拟器</strong>。</p>
                  <p><strong>模拟</strong>：只在右侧画布上画红点/滑动线，<strong>不触控真机</strong>；导入图片后默认模拟。</p>
                  <p class="opacity-90">自定义代码在模拟模式下不触发真实点击。</p>
                </div>
              </template>
              <i class="fa fa-info-circle editor-help-icon shrink-0" tabindex="0" aria-label="说明" role="img"></i>
            </el-tooltip>
            <el-switch v-model="virtualRemoteOnly" size="small"
              active-text="模拟"
              inactive-text="执行"
              class="ml-auto shrink-0" />
          </div>
          <el-button v-if="virtualClickMarkers.length || virtualSwipeLines.length" size="small" plain
            @click="clearVirtualOverlays" class="self-start">
            清除虚拟标注
          </el-button>
        </div>
        <div class="mt-2 pt-2 border-t border-slate-200 flex flex-col gap-1.5">
          <span class="text-xs text-gray-500">自定义代码执行</span>
          <el-input type="textarea" v-model="customExecCode" size="small"
            :autosize="{ minRows: 6, maxRows: 18 }"
            @keydown="onCustomExecKeydown"
            placeholder="如 locate(T(&quot;确定&quot;))；最后一行为表达式则返回其值；为赋值（如 info = extract_info(...)）则返回左侧变量。也可用 __result__ = …"
            class="editor-custom-exec-input" />
          <div class="flex gap-1.5">
            <el-button size="small" plain type="danger"
              @click="stopCustomCodeExecution"
              :loading="stopCustomLoading"
              :disabled="!execCustomLoading || stopCustomLoading"
              class="flex-1 min-w-0">
              <i class="fa fa-stop-circle-o mr-1"></i>终止执行
            </el-button>
            <el-button size="small"
              @click="executeCustomCode" :loading="execCustomLoading"
              :disabled="!customExecCode.trim() || execCustomLoading"
              class="flex-1 min-w-0 editor-custom-exec-run-btn">
              <i class="fa fa-terminal mr-1"></i>执行
            </el-button>
          </div>
        </div>
      </div>
    </div>

  </div>

  <!-- 右侧：Canvas + 操作录制 -->
  <div class="lg:w-3/4 flex min-h-0 gap-3 editor-right-zone" :class="isLandscape ? 'flex-col' : 'flex-row'">

    <!-- Canvas 画布（拖放图片至此区域以导入） -->
    <div class="bg-white rounded-xl shadow-md p-3 overflow-hidden flex items-center justify-center min-h-0 min-w-0 editor-canvas-cell transition-shadow relative"
         :class="[isLandscape ? 'shrink-0' : 'order-2 flex-1', canvasDropActive ? 'ring-2 ring-primary ring-inset' : '', loadingImport ? 'opacity-80' : '']"
         :style="canvasCellStyle"
         @dragover.prevent="onCanvasDragOver"
         @dragleave="onCanvasDragLeave"
         @drop.prevent="onCanvasDrop">
      <editor-canvas
        :image-src="imageSrc"
        :selection="optimizedSel"
        :locate-boxes="locateBoxes"
        :virtual-click-markers="virtualClickMarkers"
        :virtual-swipe-lines="virtualSwipeLines"
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
        <el-input type="textarea" v-model="recordedCode" ref="recordedCodeInput" class="flex-1 editor-code-textarea"
                  :autosize="false" resize="none"
                  @keydown="onRecordedCodeKeydown"
                  placeholder="操作后代码将自动生成…" />
      </div>
      <div class="flex shrink-0 editor-recorder-actions"
           :class="isLandscape ? 'flex-col gap-2 justify-start' : 'flex-row flex-wrap gap-2 justify-end items-center'"
           :style="isLandscape ? 'width:120px' : ''">
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left">将录制区<strong>全部代码</strong>复制到剪贴板，便于粘贴到任务脚本。</div>
          </template>
          <span class="inline-flex"><el-button size="small" @click="copyRecordedCode" :disabled="!recordedCode.trim()">
            <i class="fa fa-copy mr-1"></i>复制代码
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left">将录制区与自定义执行区内容发送给后端，保存到 data/custom_task 下作为自定义脚本。</div>
          </template>
          <span class="inline-flex"><el-button size="small" type="primary" plain
            @click="saveCustomScript"
            :loading="saveScriptLoading"
            :disabled="saveScriptDisabled">
            <i class="fa fa-save mr-1"></i>保存脚本
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left">清空录制区文本，不影响画布与左侧选区。</div>
          </template>
          <span class="inline-flex"><el-button size="small" type="danger" plain @click="recordedCode=''" :disabled="!recordedCode.trim()">
            <i class="fa fa-trash-o mr-1"></i>清空
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left space-y-1">
              <p>在当前画面上查找左侧名称对应的 <strong>T / I 目标</strong>，返回 <strong>Box</strong> 或 None（不阻塞等待出现，可与超时配合）。</p>
              <p class="font-mono text-[11px] opacity-90">locate(目标)</p>
            </div>
          </template>
          <span class="inline-flex"><el-button size="small" plain @click="appendLocate" :disabled="!optimizedSel">
            定位
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left space-y-1">
              <p>插入存在判断代码片段；有当前框选时复用点击生成的 T / I / B 目标，否则光标停在括号内。</p>
              <p class="font-mono text-[11px] opacity-90">if ui_T(目标):</p>
            </div>
          </template>
          <span class="inline-flex"><el-button size="small" plain @click="appendUiExists">
            判断存在
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left space-y-1">
              <p>阻塞直到左侧名称对应的 <strong>T / I 目标</strong>在画面上出现（依赖当前选区与名称）。</p>
              <p class="font-mono text-[11px] opacity-90">wait_for_appear(目标)</p>
            </div>
          </template>
          <span class="inline-flex"><el-button size="small" plain @click="appendWaitAppear" :disabled="!optimizedSel">
            等待出现
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left space-y-1">
              <p>阻塞直到该目标从画面上消失。</p>
              <p class="font-mono text-[11px] opacity-90">wait_for_disappear(目标)</p>
            </div>
          </template>
          <span class="inline-flex"><el-button size="small" plain @click="appendWaitDisappear" :disabled="!optimizedSel">
            等待消失
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[288px] text-xs leading-relaxed text-left space-y-2">
              <p class="font-mono text-[11px] opacity-90 leading-snug">extract_info(B(…), post_process=…, ensure_not_empty=…)</p>
              <ul class="list-disc pl-4 space-y-1.5 text-[11px]">
                <li><strong>post_process</strong>：对识别出的<strong>字符串</strong>使用Python语法再加工；<code class="bg-slate-700 px-0.5 rounded">strip</code> </li>
                <li><strong>ensure_not_empty</strong>：为真时若结果是空串/发生错误会重试截图识别，直到有字或达到重试上限。</li>
              </ul>
            </div>
          </template>
          <span class="inline-flex"><el-button size="small" plain @click="appendExtractInfo" :disabled="!optimizedSel" :loading="extractPreviewLoading">
            提取信息
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[300px] text-xs leading-relaxed text-left space-y-1">
              <p>生成数字角标/库存格子的批量提取模板。</p>
              <p class="font-mono text-[11px] opacity-90 leading-snug">extract_info(make_box_grid(...), digital=True)</p>
            </div>
          </template>
          <span class="inline-flex"><el-button size="small" plain @click="appendExtractGridInfo" :disabled="!optimizedSel">
            数字网格
          </el-button></span>
        </el-tooltip>
        <el-tooltip placement="left" :show-after="0">
          <template #content>
            <div class="max-w-[260px] text-xs leading-relaxed text-left space-y-1">
              <p>暂停脚本执行约 1 秒</p>
              <p class="font-mono text-[11px] opacity-90">sleep(1)</p>
            </div>
          </template>
          <span class="inline-flex"><el-button size="small" plain @click="appendSleepWait">
            阻塞等待
          </el-button></span>
        </el-tooltip>
      </div>
    </div>

  </div>
</div>

<el-dialog v-model="saveScriptDialogVisible" title="保存脚本" width="min(760px, calc(100vw - 32px))" append-to-body>
  <el-form label-position="top" class="space-y-3" @submit.prevent>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <el-form-item label="文件名称">
        <el-input v-model="saveScriptForm.filename" placeholder="custom_task.py" />
      </el-form-item>
      <el-form-item label="脚本名称">
        <el-input v-model="saveScriptForm.taskPathTail" placeholder="示例/操作设置">
          <template #prepend>自定义任务/</template>
        </el-input>
      </el-form-item>
    </div>
    <el-form-item label="description（描述）">
      <el-input v-model="saveScriptForm.description" placeholder="一句话描述" />
    </el-form-item>
    <el-form-item label="task_docs">
      <el-input type="textarea" v-model="saveScriptForm.taskDoc" :autosize="{ minRows: 3, maxRows: 8 }" placeholder="补充说明正文" />
    </el-form-item>
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-sm font-medium text-slate-700">参数设置</span>
        <el-button size="small" @click="addSaveScriptParam"><i class="fa fa-plus mr-1"></i>添加参数</el-button>
      </div>
      <div v-for="(param, index) in saveScriptForm.params" :key="index" class="border border-slate-200 rounded-md p-3 mb-2">
        <div class="grid grid-cols-1 md:grid-cols-12 gap-2">
          <el-form-item label="字段名称" class="md:col-span-3 !mb-0">
            <el-input v-model="param.name" placeholder="times" />
          </el-form-item>
          <el-form-item label="字段类型" class="md:col-span-3 !mb-0">
            <el-select v-model="param.type" class="w-full">
              <el-option v-for="item in saveScriptParamTypes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="字段解释" class="md:col-span-5 !mb-0">
            <el-input v-model="param.description" placeholder="参数说明" />
          </el-form-item>
          <div class="md:col-span-1 flex items-end justify-end">
            <el-button circle size="small" type="danger" plain @click="removeSaveScriptParam(index)">
              <i class="fa fa-trash-o"></i>
            </el-button>
          </div>
        </div>
        <el-form-item v-if="saveScriptParamIsEnum(param.type)" label="Enum 选项" class="!mb-0 mt-2">
          <el-input type="textarea" v-model="param.enum_options" :autosize="{ minRows: 2, maxRows: 5 }" placeholder="[&quot;xxx&quot;,&quot;xxx&quot;,&quot;xxx&quot;]" />
        </el-form-item>
      </div>
    </div>
  </el-form>
  <template #footer>
    <el-button @click="saveScriptDialogVisible = false">取消</el-button>
    <el-button type="primary" :loading="saveScriptLoading" @click="submitSaveCustomScript">保存</el-button>
  </template>
</el-dialog>
</div>`,

  setup(props, { emit }) {
    const { ref, computed, watch } = Vue;

    // ── state ──
    const imageSrc = ref('');
    const imgWidth = ref(1280);
    const imgHeight = ref(720);
    const loadingScreenshot = ref(false);
    const loadingImport = ref(false);
    const canvasDropActive = ref(false);

    /** 当前画面是否来自导入图片（离线标注）；刷新截图为 false */
    const imageFromImport = ref(false);
    /** true：遥控操作仅在 canvas 上画红点/线，不 POST /remote/* */
    const virtualRemoteOnly = ref(false);
    const virtualClickMarkers = ref([]);
    const virtualSwipeLines = ref([]);

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
    const customExecCode = ref(EDITOR_DRAFT_CACHE.customExecCode || '');
    const execCustomLoading = ref(false);
    const stopCustomLoading = ref(false);
    const extractPreviewLoading = ref(false);
    const saveScriptLoading = ref(false);
    const saveScriptDialogVisible = ref(false);
    const saveScriptForm = ref({
      filename: 'custom_task.py',
      taskPathTail: '',
      description: '',
      taskDoc: '',
      params: [],
    });
    const saveScriptParamTypes = [
      { label: 'str', value: 'str' },
      { label: 'int', value: 'int' },
      { label: 'float', value: 'float' },
      { label: 'bool', value: 'bool' },
      { label: 'Enum(单选)', value: 'enum' },
      { label: 'Enum(多选)', value: 'enum_multi' },
    ];

    // ── recorded code ──
    const recordedCodeInput = ref(null);
    const recordedCode = ref(EDITOR_DRAFT_CACHE.recordedCode || '');
    const recordedLines = computed(() => recordedCode.value.split('\n').filter(l => l.trim()));
    const saveScriptDisabled = computed(
      () => saveScriptLoading.value || (!recordedCode.value.trim() && !customExecCode.value.trim()),
    );

    watch(recordedCode, (value) => {
      EDITOR_DRAFT_CACHE.recordedCode = value || '';
    });
    watch(customExecCode, (value) => {
      EDITOR_DRAFT_CACHE.customExecCode = value || '';
    });

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

    function templateBox() {
      const s = optimizedSel.value;
      if (!s) return null;
      return {
        left: s.left,
        top: s.top,
        width: s.right - s.left,
        height: s.bottom - s.top,
      };
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

    function apiErrorMessage(data, fallback) {
      if (!data) return fallback;
      if (typeof data === 'string') return data;
      const raw = data.message || data.error || data.detail;
      if (Array.isArray(raw)) {
        return raw.map((item) => {
          if (!item) return '';
          if (typeof item === 'string') return item;
          if (item.msg) return item.msg;
          try { return JSON.stringify(item); } catch (_) { return String(item); }
        }).filter(Boolean).join('；') || fallback;
      }
      if (raw && typeof raw === 'object') {
        try { return JSON.stringify(raw); } catch (_) { return String(raw); }
      }
      return raw ? String(raw) : fallback;
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

    function buildClickCodeAt(x, y) {
      const tgt = buildTarget();
      if (!tgt) return null;
      const b = optimizedSel.value;
      if (!b) return `click(B(${x},${y}))`;
      if (tgt.startsWith('B(')) return `click(${tgt})`;
      const cx = Math.floor((b.left + b.right) / 2);
      const cy = Math.floor((b.top + b.bottom) / 2);
      const dx = x - cx;
      const dy = y - cy;
      const offsetPart = (dx || dy) ? `, offset=(${dx},${dy})` : '';
      return `click(${tgt}${offsetPart})`;
    }

    function appendCode(line) {
      if (!line) return;
      const cur = recordedCode.value;
      recordedCode.value = cur ? cur + '\n' + line : line;
    }

    function recordedTextareaElement() {
      const input = recordedCodeInput.value;
      if (!input) return null;
      return input.textarea || (input.$el ? input.$el.querySelector('textarea') : null);
    }

    function appendRecordedSnippet(line, cursorOffset = null) {
      if (!line) return;
      const cur = recordedCode.value || '';
      const prefix = cur && !cur.endsWith('\n') ? '\n' : '';
      const insertStart = cur.length + prefix.length;
      recordedCode.value = cur + prefix + line;
      if (cursorOffset == null) return;
      Vue.nextTick(() => {
        const ta = recordedTextareaElement();
        if (!ta) return;
        const pos = insertStart + cursorOffset;
        ta.focus();
        ta.setSelectionRange(pos, pos);
      });
    }

    function clearSelection() {
      selection.value = null;
      optimizedSel.value = null;
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

    function appendLocate() {
      const r = requireTOrITarget();
      if (!r.ok) return;
      appendCode(`locate(${r.tgt})`);
      ElementPlus.ElMessage.success('已添加「定位」');
    }

    function appendUiExists() {
      const tgt = buildTarget();
      const line = tgt ? `if ui_T(${tgt}):` : 'if ui_T():';
      appendRecordedSnippet(line, tgt ? null : line.indexOf('(') + 1);
      ElementPlus.ElMessage.success('已添加「判断存在」');
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

    /** 数字角标/库存网格模板：first_box 与 grid_box 先用当前选区占位，便于后续手动改 row/col/整体区域。 */
    function appendExtractGridInfo() {
      const b = effectiveBox();
      if (!b) {
        ElementPlus.ElMessage.warning('请先框选第一个格子区域');
        return;
      }
      const first = `Box(${b.left},${b.top},${b.width},${b.height})`;
      const line = `counts = extract_info(make_box_grid(${first}, ${first}, row=1, col=1), digital=True)`;
      appendCode(line);
      ElementPlus.ElMessage.success('已添加「数字网格」模板');
    }

    // ── actions ──
    /** 与 GET /screenshot、POST /ingest-image 返回结构一致时更新画布与校验状态 */
    async function applyEditorImageData(data, fromImport = false) {
      if (data.error) { ElementPlus.ElMessage.error(data.error); return false; }
      imageSrc.value = 'data:image/jpeg;base64,' + data.image;
      imgWidth.value = data.width || 1280;
      imgHeight.value = data.height || 720;
      locateBoxes.value = [];
      virtualClickMarkers.value = [];
      virtualSwipeLines.value = [];
      imageFromImport.value = fromImport;
      virtualRemoteOnly.value = fromImport;
      nameOk.value = {};
      imageOk.value = {};
      await validateAll();
      return true;
    }

    async function refreshScreenshot() {
      loadingScreenshot.value = true;
      try {
        const data = await apiGet('/screenshot');
        await applyEditorImageData(data, false);
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
        const ok = await applyEditorImageData(data, true);
        if (ok) ElementPlus.ElMessage.success('已导入图片');
      } catch (e) {
        ElementPlus.ElMessage.error('导入失败: ' + e);
      } finally {
        loadingImport.value = false;
      }
    }

    /** 从同源 URL（如 /api/error-archives/file?…）拉取图片并导入编辑器 */
    async function importFromUrl(url) {
      if (!url) return;
      try {
        const r = await fetch(url, { credentials: 'same-origin' });
        if (!r.ok) throw new Error(r.statusText || '请求失败');
        const blob = await r.blob();
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(new Error('读取失败'));
          reader.readAsDataURL(blob);
        });
        await ingestFromDataUrl(dataUrl);
      } catch (e) {
        ElementPlus.ElMessage.error('加载图片失败: ' + e);
      }
    }

    watch(
      () => props.pendingImportUrl,
      async (url) => {
        if (!url) return;
        await importFromUrl(url);
        emit('imported');
      },
      { immediate: true },
    );

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

    function clearVirtualOverlays() {
      virtualClickMarkers.value = [];
      virtualSwipeLines.value = [];
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
      const tb = templateBox();
      if (!b) { ElementPlus.ElMessage.warning('请先框选区域'); return; }
      if (!name.value.trim()) { ElementPlus.ElMessage.warning('名称不能为空'); return; }
      try {
        const data = await apiPost('/save', {
          name: name.value.trim(),
          left: b.left, top: b.top, width: b.width, height: b.height,
          template_left: tb.left, template_top: tb.top, template_width: tb.width, template_height: tb.height,
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

      appendCode(buildClickCodeAt(cx, cy));

      if (virtualRemoteOnly.value) {
        virtualClickMarkers.value = [...virtualClickMarkers.value, { x: cx, y: cy }];
        ElementPlus.ElMessage.success(`虚拟点击 (${cx}, ${cy})（未下发模拟器）`);
        return;
      }

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
      clearSelection();
      const line = buildClickCodeAt(x, y) || `click(B(${x},${y}))`;
      if (virtualRemoteOnly.value) {
        virtualClickMarkers.value = [...virtualClickMarkers.value, { x, y }];
        appendCode(line);
        ElementPlus.ElMessage.success(`虚拟点击 (${x}, ${y})（未下发模拟器）`);
        return;
      }
      remoteLoading.value = true;
      try {
        const res = await apiPost('/remote/click', { x, y });
        if (res.error) { ElementPlus.ElMessage.error(res.error); }
        else { ElementPlus.ElMessage.success(`右键点击 (${x}, ${y})`); appendCode(line); }
      } catch (e) {
        ElementPlus.ElMessage.error('点击失败: ' + e);
      } finally {
        try { await refreshScreenshotAfterRemote(); } catch (_) { /* ignore */ }
        remoteLoading.value = false;
      }
    }

    /** 画布右键拖拽滑动：起止点与遥控器 swipe API 一致 */
    async function onCanvasRemoteSwipe({ x1, y1, x2, y2 }) {
      clearSelection();
      const line = `swipe(B(${x1},${y1}), B(${x2},${y2}), duration_s=1)`;
      if (virtualRemoteOnly.value) {
        virtualSwipeLines.value = [...virtualSwipeLines.value, { x1, y1, x2, y2 }];
        appendCode(line);
        ElementPlus.ElMessage.success('虚拟滑动（未下发模拟器）');
        return;
      }
      remoteLoading.value = true;
      try {
        const res = await apiPost('/remote/swipe', { x1, y1, x2, y2, duration_s: 1 });
        if (res.error) { ElementPlus.ElMessage.error(res.error); }
        else { ElementPlus.ElMessage.success('右键滑动'); appendCode(line); }
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
      // 方向 = 手指移动方向：上=从下往上、下=从上往下、左=从右往左、右=从左往右
      const dirMap = {
        up:    { x1: cx, y1: s.bottom, x2: cx, y2: s.top },
        down:  { x1: cx, y1: s.top,    x2: cx, y2: s.bottom },
        left:  { x1: s.right, y1: cy,  x2: s.left, y2: cy },
        right: { x1: s.left,  y1: cy,  x2: s.right, y2: cy },
      };
      const pts = dirMap[swipeDir.value];

      // generate code in parallel
      appendCode(`swipe(B(${pts.x1},${pts.y1}), B(${pts.x2},${pts.y2}), duration_s=1)`);

      if (virtualRemoteOnly.value) {
        virtualSwipeLines.value = [...virtualSwipeLines.value, {
          x1: pts.x1, y1: pts.y1, x2: pts.x2, y2: pts.y2,
        }];
        const arrow = { up: '↑', down: '↓', left: '←', right: '→' }[swipeDir.value];
        ElementPlus.ElMessage.success(`虚拟滑动 ${arrow}（未下发模拟器）`);
        return;
      }

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

    function buildSaveScriptCode() {
      const hasRecordedCode = !!(recordedCode.value || '').trim();
      const hasCustomExecCode = !!(customExecCode.value || '').trim();
      const sections = [];
      if (hasRecordedCode) sections.push((recordedCode.value || '').trim());
      if (hasCustomExecCode) sections.push((customExecCode.value || '').trim());
      return sections.join('\n\n');
    }

    function normalizeSaveScriptFilename(raw) {
      let filename = String(raw || '').trim() || 'custom_task.py';
      filename = filename.replace(/[\\/:*?"<>|]+/g, '_');
      if (!filename.toLowerCase().endsWith('.py')) filename += '.py';
      return filename;
    }

    function normalizeSaveScriptTaskPath() {
      const tail = String(saveScriptForm.value.taskPathTail || '').trim().replace(/^自定义任务[\\/]+/, '');
      if (!tail) {
        ElementPlus.ElMessage.warning('请填写脚本名称');
        return null;
      }
      return `自定义任务/${tail}`;
    }

    function saveScriptParamIsEnum(type) {
      return type === 'enum' || type === 'enum_multi';
    }

    function addSaveScriptParam() {
      saveScriptForm.value.params.push({
        name: '',
        type: 'str',
        description: '',
        enum_options: '',
      });
    }

    function removeSaveScriptParam(index) {
      saveScriptForm.value.params.splice(index, 1);
    }

    function buildSaveScriptParamPayload() {
      const params = [];
      for (const param of saveScriptForm.value.params) {
        const name = String(param.name || '').trim();
        if (!name) continue;
        const type = String(param.type || 'str').trim() || 'str';
        const item = {
          name,
          type,
          description: String(param.description || '').trim(),
        };
        if (saveScriptParamIsEnum(type)) {
          const raw = String(param.enum_options || '').trim();
          let parsed;
          try {
            parsed = JSON.parse(raw || '[]');
          } catch (_) {
            ElementPlus.ElMessage.warning('Enum 选项请输入 JSON 数组，例如 ["xxx","xxx","xxx"]');
            return null;
          }
          if (!Array.isArray(parsed)) {
            ElementPlus.ElMessage.warning('Enum 选项请输入 JSON 数组，例如 ["xxx","xxx","xxx"]');
            return null;
          }
          const enum_options = parsed.map(item => String(item).trim()).filter(Boolean);
          if (!enum_options.length) {
            ElementPlus.ElMessage.warning('Enum 参数至少需要一个选项');
            return null;
          }
          item.enum_options = enum_options;
        }
        params.push(item);
      }
      return params;
    }

    async function saveCustomScript() {
      if (!buildSaveScriptCode().trim()) {
        ElementPlus.ElMessage.warning('请先输入要保存的脚本内容');
        return;
      }
      saveScriptForm.value.filename = normalizeSaveScriptFilename(saveScriptForm.value.filename);
      saveScriptDialogVisible.value = true;
    }

    async function submitSaveCustomScript() {
      const code = buildSaveScriptCode();
      if (!code.trim()) {
        ElementPlus.ElMessage.warning('请先输入要保存的脚本内容');
        return;
      }
      const filename = normalizeSaveScriptFilename(saveScriptForm.value.filename);
      const taskPath = normalizeSaveScriptTaskPath();
      if (!taskPath) return;
      const params = buildSaveScriptParamPayload();
      if (params === null) return;

      saveScriptForm.value.filename = filename;
      saveScriptLoading.value = true;
      try {
        const form = saveScriptForm.value;
        const payload = {
          filename: filename,
          task_path: taskPath,
          description: String(form.description || '').trim(),
          task_doc: String(form.taskDoc || '').trim(),
          params: params,
          code,
        };
        const res = await apiPost('/save-custom-task', payload);
        if (!res || res.ok === false || res.error || res.detail) {
          ElementPlus.ElMessage.error(apiErrorMessage(res, '保存脚本失败'));
          return;
        }
        saveScriptDialogVisible.value = false;
        ElementPlus.ElMessage.success(res.message || '脚本已保存');
      } catch (e) {
        ElementPlus.ElMessage.error('保存脚本失败: ' + e);
      } finally {
        saveScriptLoading.value = false;
      }
    }

    function handleTextareaTab(e, modelRef) {
      if (e.key !== 'Tab') return;
      e.preventDefault();
      const ta = e.target;
      if (!ta || typeof ta.selectionStart !== 'number') return;
      const value = modelRef.value || '';
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const hasSelection = end > start;
      const lineStart = value.lastIndexOf('\n', start - 1) + 1;
      const lineEnd = hasSelection ? value.indexOf('\n', end - 1) : value.indexOf('\n', start);
      const blockEnd = lineEnd === -1 ? value.length : lineEnd;
      const before = value.slice(0, lineStart);
      const block = value.slice(lineStart, blockEnd);
      const after = value.slice(blockEnd);
      const lines = block.split('\n');

      if (e.shiftKey) {
        let removedBeforeStart = 0;
        let removedTotal = 0;
        const nextLines = lines.map((line, idx) => {
          const remove = line.startsWith('    ') ? 4 : (line.startsWith('\t') ? 1 : 0);
          if (idx === 0) removedBeforeStart = remove;
          removedTotal += remove;
          return remove ? line.slice(remove) : line;
        });
        modelRef.value = before + nextLines.join('\n') + after;
        Vue.nextTick(() => {
          const nextStart = Math.max(lineStart, start - removedBeforeStart);
          const nextEnd = Math.max(nextStart, end - removedTotal);
          ta.focus();
          ta.setSelectionRange(nextStart, nextEnd);
        });
        return;
      }

      const nextBlock = lines.map((line) => '    ' + line).join('\n');
      modelRef.value = before + nextBlock + after;
      Vue.nextTick(() => {
        ta.focus();
        ta.setSelectionRange(start + 4, end + 4 * lines.length);
      });
    }

    function onRecordedCodeKeydown(e) {
      handleTextareaTab(e, recordedCode);
    }

    function onCustomExecKeydown(e) {
      handleTextareaTab(e, customExecCode);
    }

    async function stopCustomCodeExecution() {
      stopCustomLoading.value = true;
      try {
        const res = await apiPost('/execute-code/stop', {});
        if (!res || res.ok === false) {
          const err = (res && (res.message || res.error || res.detail)) ? String(res.message || res.error || res.detail) : '终止请求失败';
          ElementPlus.ElMessage.error(err.length > 800 ? err.slice(0, 800) + '…' : err);
          return;
        }
        ElementPlus.ElMessage.success(res.message || '已发送终止执行请求');
      } catch (e) {
        ElementPlus.ElMessage.error('终止请求失败: ' + e);
      } finally {
        stopCustomLoading.value = false;
      }
    }

    /** 自定义代码：不写入操作录制区；以返回值 repr 为主展示，失败才提示错误 */
    async function executeCustomCode() {
      const code = (customExecCode.value || '').trim();
      if (!code) { ElementPlus.ElMessage.warning('请输入代码'); return; }
      execCustomLoading.value = true;
      try {
        const res = await apiPost('/execute-code', {
          code,
          virtual_only: virtualRemoteOnly.value,
        });
        if (!res || res.ok === false) {
          const err = (res && res.error) ? String(res.error) : '执行失败';
          ElementPlus.ElMessage.error(err.length > 800 ? err.slice(0, 800) + '…' : err);
          return;
        }
        if (virtualRemoteOnly.value) {
          let added = false;
          if (res.virtual_clicks && res.virtual_clicks.length) {
            virtualClickMarkers.value = [...virtualClickMarkers.value, ...res.virtual_clicks];
            added = true;
          }
          if (res.virtual_swipes && res.virtual_swipes.length) {
            virtualSwipeLines.value = [...virtualSwipeLines.value, ...res.virtual_swipes];
            added = true;
          }
          if (added) {
            ElementPlus.ElMessage.success('已在画布标注虚拟点击/滑动（未下发模拟器）');
          }
        }
        const hasResult = Object.prototype.hasOwnProperty.call(res, 'result');
        const stdout = res.stdout ? String(res.stdout).trim() : '';
        if (!hasResult && !stdout) {
          ElementPlus.ElMessage({
            message: '执行完成（无返回值）。最后一行写表达式，或赋值如 info = …（会返回 info），或 __result__ = …',
            type: 'info',
            duration: 4200,
            showClose: true,
            offset: 72,
          });
          return;
        }
        let body = '';
        if (hasResult) body += String(res.result);
        if (stdout) body += (body ? '\n\n' : '') + '【标准输出】\n' + stdout;
        const msgText = body.length > 12000 ? body.slice(0, 12000) + '\n…（已截断）' : body;
        const title = hasResult ? '返回值 (repr)' : '输出';
        ElementPlus.ElMessage({
          message: title + '\n' + msgText,
          type: 'success',
          duration: 3800,
          showClose: true,
          customClass: 'editor-exec-result-message',
          offset: 72,
        });
      } catch (e) {
        ElementPlus.ElMessage.error('请求失败: ' + e);
      } finally {
        execCustomLoading.value = false;
      }
    }

    return {
      imageSrc, imgWidth, imgHeight, loadingScreenshot, loadingImport,
      selection, optimizedSel, locateBoxes,
      name, freezeName, freeX, freeY, useImage, onlyOcr, lockColor, threshold,
      centerText, boxText, tCode, iCode, colorText, nameOk, imageOk,
      swipeDir, remoteLoading, customExecCode, execCustomLoading, stopCustomLoading, extractPreviewLoading,
      saveScriptLoading, saveScriptDisabled, saveScriptDialogVisible, saveScriptForm, saveScriptParamTypes,
      saveScriptParamIsEnum, addSaveScriptParam, removeSaveScriptParam, submitSaveCustomScript,
      virtualRemoteOnly, virtualClickMarkers, virtualSwipeLines,
      recordedCodeInput, recordedCode, recordedLines, isLandscape, canvasCellStyle,
      canvasDropActive, clearVirtualOverlays,
      refreshScreenshot,
      onCanvasDragOver, onCanvasDragLeave, onCanvasDrop,
      onSelectionChange, onThresholdRelease,
      saveSelection, onCopy, remoteClick, remoteSwipe,
      onCanvasRemoteClick, onCanvasRemoteSwipe,
      copyRecordedCode, saveCustomScript, stopCustomCodeExecution, onRecordedCodeKeydown, onCustomExecKeydown, executeCustomCode,
      appendLocate, appendUiExists, appendWaitAppear, appendWaitDisappear, appendSleepWait, appendExtractInfo, appendExtractGridInfo,
    };
  },
};
