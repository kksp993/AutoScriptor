/**
 * CanvasPanel -- 可视化拖拽脚本画布
 *
 * 使用 Drawflow 库实现节点拖拽编排，支持将节点图导出为 Python 脚本。
 * 左侧：节点面板（可拖拽节点类型）
 * 中间：Drawflow 画布
 * 右侧：属性面板 + 代码预览
 */
const CanvasPanel = {
  name: 'CanvasPanel',
  template: `
<div class="flex h-full min-h-0 gap-3">

  <!-- 左侧：节点面板 -->
  <div class="w-56 flex-shrink-0 bg-white rounded-xl shadow-md flex flex-col min-h-0 overflow-hidden">
    <div class="p-3 border-b border-slate-100">
      <h2 class="text-sm font-semibold text-dark flex items-center gap-1.5">
        <i class="fa fa-th-large text-gray-400"></i>节点面板
      </h2>
    </div>
    <div class="flex-1 overflow-y-auto p-2 space-y-1">
      <div v-for="group in nodeGroups" :key="group.label" class="mb-2">
        <div class="text-xs text-gray-400 font-medium px-2 py-1 uppercase tracking-wide">{{ group.label }}</div>
        <div v-for="node in group.nodes" :key="node.type"
             class="canvas-node-item flex items-center gap-2 px-3 py-2 rounded-lg cursor-grab hover:bg-primary/10 transition-colors text-sm"
             :class="'canvas-node-' + node.category"
             draggable="true"
             @dragstart="onNodeDragStart($event, node)">
          <i :class="['fa', node.icon, 'w-4 text-center']" :style="{color: node.color}"></i>
          <span>{{ node.label }}</span>
        </div>
      </div>
    </div>
  </div>

  <!-- 中间：Drawflow 画布 -->
  <div class="flex-1 flex flex-col min-w-0 min-h-0">
    <!-- 工具栏 -->
    <div class="flex items-center gap-2 mb-2 flex-shrink-0">
      <el-button size="small" @click="clearCanvas" type="danger" plain>
        <i class="fa fa-trash-o mr-1"></i>清空画布
      </el-button>
      <el-button size="small" @click="zoomIn" plain><i class="fa fa-search-plus"></i></el-button>
      <el-button size="small" @click="zoomOut" plain><i class="fa fa-search-minus"></i></el-button>
      <el-button size="small" @click="zoomReset" plain><i class="fa fa-compress"></i></el-button>
      <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-slate-50 border border-slate-100">
        <span class="text-xs text-slate-500 whitespace-nowrap">节点摘要</span>
        <el-switch v-model="showCanvasSummary" size="small" @change="onCanvasSummaryToggle" />
      </div>
      <div class="flex-1"></div>
      <el-input v-model="scriptName" size="small" placeholder="脚本名称" class="!w-48" />
      <el-button size="small" type="primary" @click="generateAndSave" :loading="saving">
        <i class="fa fa-save mr-1"></i>保存脚本
      </el-button>
      <el-button size="small" @click="previewCode" plain>
        <i class="fa fa-code mr-1"></i>预览代码
      </el-button>
      <el-button size="small" @click="openLoadDialog" plain>
        <i class="fa fa-folder-open mr-1"></i>加载
      </el-button>
    </div>
    <!-- 画布 -->
    <div class="flex-1 bg-white rounded-xl shadow-md overflow-hidden min-h-0 relative"
         @drop.prevent="onCanvasDrop" @dragover.prevent="onCanvasDragOver">
      <div ref="drawflowEl" class="drawflow-container canvas-drawflow-vertical"></div>
    </div>
  </div>

  <!-- 右侧：属性 + 预览 -->
  <div class="w-72 flex-shrink-0 flex flex-col gap-3 min-h-0">

    <!-- 属性面板 -->
    <div class="bg-white rounded-xl shadow-md p-4 flex flex-col overflow-hidden flex-1 min-h-0">
      <h2 class="text-sm font-semibold text-dark mb-3 flex-shrink-0 flex items-center gap-1.5">
        <i class="fa fa-sliders text-gray-400"></i>节点属性
      </h2>
      <div v-if="!selectedNode" class="flex-1 flex items-center justify-center text-gray-400 text-sm">
        点击画布中的节点查看属性
      </div>
      <div v-else class="flex-1 overflow-y-auto space-y-3">
        <div class="text-xs text-gray-500">类型: <span class="font-medium text-dark">{{ selectedNodeDef?.label }}</span></div>
        <div class="text-xs text-gray-500">节点ID: <span class="font-mono text-dark">#{{ selectedNode.id }}</span></div>
        <template v-for="param in selectedNodeParams" :key="param.key">
          <div class="space-y-1">
            <label class="text-xs font-medium text-gray-600">{{ param.label }}</label>
            <el-select v-if="param.options" v-model="param.value" size="small" class="w-full"
                       @change="onParamChange(param)">
              <el-option v-for="o in param.options" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <el-switch v-else-if="param.type === 'boolean'" v-model="param.value" size="small"
                       @change="onParamChange(param)" />
            <el-input-number v-else-if="param.type === 'number'" v-model="param.value" size="small"
                             :min="param.min ?? 0" :max="param.max ?? 9999" :step="param.step ?? 1" class="!w-full"
                             @change="onParamChange(param)" />
            <div v-else-if="isTargetParam(param.key)" class="space-y-1">
              <el-input v-model="param.value" size="small" :placeholder="param.placeholder || ''"
                        @input="onParamChange(param)" />
              <el-button size="small" type="primary" plain class="w-full" @click="openTargetPicker(param)">
                <i class="fa fa-crosshairs mr-1"></i>从截图选择
              </el-button>
            </div>
            <el-input v-else v-model="param.value" size="small" :placeholder="param.placeholder || ''"
                      @input="onParamChange(param)" />
          </div>
        </template>
      </div>
    </div>

    <!-- 代码预览 -->
    <div class="bg-white rounded-xl shadow-md p-4 flex flex-col overflow-hidden min-h-0" style="max-height:40%">
      <h2 class="text-sm font-semibold text-dark mb-2 flex-shrink-0 flex items-center gap-1.5">
        <i class="fa fa-code text-gray-400"></i>代码预览
      </h2>
      <pre class="flex-1 overflow-auto text-xs bg-slate-50 rounded-lg p-3 font-mono text-slate-700 whitespace-pre-wrap">{{ previewText || '// 拖入节点并连线以生成代码' }}</pre>
    </div>
  </div>

  <!-- 画布管理对话框 -->
  <teleport to="body">
    <el-dialog v-model="saveListVisible" title="已保存的画布" width="500px" destroy-on-close>
      <div v-if="savedCanvasList.length === 0" class="text-center text-gray-400 py-4">暂无保存的画布</div>
      <div v-else class="space-y-2 max-h-80 overflow-y-auto">
        <div v-for="c in savedCanvasList" :key="c.name"
             class="flex items-center justify-between p-3 bg-slate-50 rounded-lg hover:bg-slate-100 transition-colors">
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium text-dark truncate">{{ c.name }}</div>
            <div class="text-xs text-gray-400">{{ c.updated_at }}</div>
          </div>
          <div class="flex gap-1 ml-2">
            <el-button size="small" type="primary" plain @click="loadCanvas(c.name)">加载</el-button>
            <el-button size="small" type="danger" plain @click="deleteCanvas(c.name)">删除</el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="saveListVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </teleport>

  <!-- 代码预览对话框 -->
  <teleport to="body">
    <el-dialog v-model="codeDialogVisible" title="生成的 Python 代码" width="680px" destroy-on-close>
      <pre class="bg-slate-900 text-green-300 rounded-lg p-4 overflow-auto text-sm font-mono whitespace-pre-wrap" style="max-height:60vh">{{ fullCodePreview }}</pre>
      <template #footer>
        <el-button @click="copyGeneratedCode" type="primary"><i class="fa fa-copy mr-1"></i>复制代码</el-button>
        <el-button @click="codeDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </teleport>

  <!-- Target 拾取对话框 -->
  <teleport to="body">
    <el-dialog v-model="targetPickerVisible" title="选择目标 (Target)" width="780px" destroy-on-close top="5vh">
      <div class="space-y-3">
        <div class="flex items-center gap-3">
          <el-radio-group v-model="targetPickerMode" size="small">
            <el-radio-button label="text">文字识别 T()</el-radio-button>
            <el-radio-button label="image">图片匹配 I()</el-radio-button>
            <el-radio-button label="box">坐标区域 B()</el-radio-button>
          </el-radio-group>
          <el-button size="small" type="primary" @click="targetPickerRefresh" :loading="targetPickerLoading">
            <i class="fa fa-camera mr-1"></i>截图
          </el-button>
        </div>
        <div v-if="targetPickerImage" class="canvas-target-picker-wrap relative bg-slate-100 rounded-lg overflow-hidden select-none" style="max-height:400px">
          <img :src="targetPickerImage" draggable="false"
               class="canvas-target-picker-img w-full object-contain cursor-crosshair block max-h-[400px]"
               @dragstart.prevent
               @mousedown="onTargetImgMouseDown"
               ref="targetPickerImg" />
          <div v-if="targetPickerSel" class="absolute border-2 border-primary bg-primary/10 pointer-events-none"
               :style="targetPickerSelStyle"></div>
        </div>
        <div v-else class="text-center text-gray-400 py-8">
          点击「截图」获取模拟器当前画面，然后框选目标区域
        </div>
        <div v-if="targetPickerSel" class="flex items-center gap-3 flex-wrap">
          <template v-if="targetPickerMode === 'text'">
            <el-input v-model="targetPickerText" size="small" placeholder="OCR识别文本" class="!w-48">
              <template #prepend>文本</template>
            </el-input>
            <span class="text-xs text-gray-500 font-mono">{{ targetPickerResultCode }}</span>
          </template>
          <template v-else-if="targetPickerMode === 'image'">
            <el-input v-model="targetPickerText" size="small" placeholder="图片名称" class="!w-48">
              <template #prepend>名称</template>
            </el-input>
            <span class="text-xs text-gray-500 font-mono">{{ targetPickerResultCode }}</span>
          </template>
          <template v-else>
            <span class="text-xs text-gray-500 font-mono">{{ targetPickerResultCode }}</span>
          </template>
        </div>
      </div>
      <template #footer>
        <el-button @click="targetPickerVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmTargetPicker" :disabled="!targetPickerResultCode">
          <i class="fa fa-check mr-1"></i>确认选择
        </el-button>
      </template>
    </el-dialog>
  </teleport>

</div>`,

  setup() {
    const { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } = Vue;

    // ── Node definitions ──
    const NODE_DEFS = {
      start:             { label: '开始',       icon: 'fa-play-circle',    color: '#22c55e', category: 'flow',   inputs: 0, outputs: 1, params: [] },
      end:               { label: '结束',       icon: 'fa-stop-circle',    color: '#ef4444', category: 'flow',   inputs: 1, outputs: 0, params: [] },
      click:             { label: '点击',       icon: 'fa-mouse-pointer',  color: '#3b82f6', category: 'action', inputs: 1, outputs: 1, params: [
        { key: 'target',   label: '目标',    type: 'string', default: 'T("确定")' },
        { key: 'timeout',  label: '超时(秒)', type: 'number', default: 3, min: 0 },
        { key: 'if_exist', label: '仅存在时', type: 'boolean', default: false },
        { key: 'repeat',   label: '重复次数', type: 'number', default: 1, min: 1 },
      ]},
      swipe:             { label: '滑动',       icon: 'fa-hand-pointer-o', color: '#8b5cf6', category: 'action', inputs: 1, outputs: 1, params: [
        { key: 'start_target', label: '起点', type: 'string', default: 'B(640,500,1,1)' },
        { key: 'end_target',   label: '终点', type: 'string', default: 'B(640,200,1,1)' },
        { key: 'duration_s',   label: '时长(秒)', type: 'number', default: 1, min: 0 },
      ]},
      sleep:             { label: '等待',       icon: 'fa-clock-o',        color: '#f59e0b', category: 'action', inputs: 1, outputs: 1, params: [
        { key: 'seconds', label: '秒数', type: 'number', default: 1, min: 0, step: 0.5 },
      ]},
      input_text:        { label: '输入文本',   icon: 'fa-keyboard-o',     color: '#06b6d4', category: 'action', inputs: 1, outputs: 1, params: [
        { key: 'text',         label: '文本内容', type: 'string', default: '' },
        { key: 'target_field', label: '目标输入框', type: 'string', default: '' },
      ]},
      key_event:         { label: '按键',       icon: 'fa-keyboard-o',     color: '#6366f1', category: 'action', inputs: 1, outputs: 1, params: [
        { key: 'key_code', label: '键码', type: 'number', default: 4 },
      ]},
      locate:            { label: '定位',       icon: 'fa-crosshairs',     color: '#06b6d4', category: 'detect', inputs: 1, outputs: 1, params: [
        { key: 'target',  label: '目标', type: 'string', default: 'T("确定")' },
        { key: 'timeout', label: '超时(秒)', type: 'number', default: 0, min: 0 },
      ]},
      wait_for_appear:   { label: '等待出现',   icon: 'fa-eye',            color: '#10b981', category: 'detect', inputs: 1, outputs: 1, params: [
        { key: 'target',  label: '目标', type: 'string', default: 'T("确定")' },
        { key: 'timeout', label: '超时(秒)', type: 'number', default: 30, min: 0 },
      ]},
      wait_for_disappear:{ label: '等待消失',   icon: 'fa-eye-slash',      color: '#f97316', category: 'detect', inputs: 1, outputs: 1, params: [
        { key: 'target',  label: '目标', type: 'string', default: 'T("确定")' },
        { key: 'timeout', label: '超时(秒)', type: 'number', default: 30, min: 0 },
      ]},
      extract_info:      { label: '提取信息',   icon: 'fa-file-text-o',    color: '#ec4899', category: 'detect', inputs: 1, outputs: 1, params: [
        { key: 'target',  label: '区域', type: 'string', default: 'B(0,0,1280,720)' },
        { key: 'post_process', label: '后处理', type: 'string', default: 'lambda s: s.strip()' },
        { key: 'ensure_not_empty', label: '确保非空', type: 'boolean', default: true },
        { key: 'digit_only', label: '数字角标', type: 'boolean', default: false },
      ]},
      ensure_in:         { label: '确保场景',   icon: 'fa-map-marker',     color: '#14b8a6', category: 'nav',    inputs: 1, outputs: 1, params: [
        { key: 'scene', label: '场景名', type: 'string', default: '主界面' },
      ]},
      switch_base:       { label: '切换基础',   icon: 'fa-exchange',       color: '#64748b', category: 'nav',    inputs: 1, outputs: 1, params: [
        { key: 'base', label: '基础场景', type: 'string', default: '' },
      ]},
      if_branch:         { label: '条件分支',   icon: 'fa-code-fork',      color: '#a855f7', category: 'flow',   inputs: 1, outputs: 2, params: [
        { key: 'condition', label: '条件表达式', type: 'string', default: 'ui_T(T("确定"))' },
      ]},
      loop:              { label: '循环',       icon: 'fa-refresh',        color: '#0ea5e9', category: 'flow',   inputs: 1, outputs: 1, params: [
        { key: 'times', label: '循环次数', type: 'number', default: 3, min: 1 },
      ]},
      loop_end:          { label: '循环结束',   icon: 'fa-level-up',       color: '#0ea5e9', category: 'flow',   inputs: 1, outputs: 1, params: [] },
      set_var:           { label: '设置变量',   icon: 'fa-tag',            color: '#7c3aed', category: 'flow',   inputs: 1, outputs: 1, params: [
        { key: 'var_name',  label: '变量名', type: 'string', default: 'result' },
        { key: 'expression', label: '表达式', type: 'string', default: '' },
      ]},
      comment:           { label: '注释',       icon: 'fa-comment-o',      color: '#94a3b8', category: 'flow',   inputs: 0, outputs: 0, params: [
        { key: 'text', label: '注释内容', type: 'string', default: '' },
      ]},
    };

    const nodeGroups = [
      { label: '流程控制', nodes: [
        { type: 'start',     ...NODE_DEFS.start },
        { type: 'end',       ...NODE_DEFS.end },
        { type: 'if_branch', ...NODE_DEFS.if_branch },
        { type: 'loop',      ...NODE_DEFS.loop },
        { type: 'loop_end',  ...NODE_DEFS.loop_end },
        { type: 'set_var',   ...NODE_DEFS.set_var },
        { type: 'comment',   ...NODE_DEFS.comment },
      ]},
      { label: '动作', nodes: [
        { type: 'click',      ...NODE_DEFS.click },
        { type: 'swipe',      ...NODE_DEFS.swipe },
        { type: 'sleep',      ...NODE_DEFS.sleep },
        { type: 'input_text', ...NODE_DEFS.input_text },
        { type: 'key_event',  ...NODE_DEFS.key_event },
      ]},
      { label: '检测', nodes: [
        { type: 'locate',             ...NODE_DEFS.locate },
        { type: 'wait_for_appear',    ...NODE_DEFS.wait_for_appear },
        { type: 'wait_for_disappear', ...NODE_DEFS.wait_for_disappear },
        { type: 'extract_info',       ...NODE_DEFS.extract_info },
      ]},
      { label: '导航', nodes: [
        { type: 'ensure_in',   ...NODE_DEFS.ensure_in },
        { type: 'switch_base', ...NODE_DEFS.switch_base },
      ]},
    ];

    // ── Drawflow instance ──
    let editor = null;
    const drawflowEl = ref(null);

    // ── State ──
    const scriptName = ref('我的脚本');
    const saving = ref(false);
    const selectedNode = ref(null);
    const selectedNodeDef = ref(null);
    const selectedNodeParams = ref([]);
    const previewText = ref('');
    const codeDialogVisible = ref(false);
    const fullCodePreview = ref('');
    const saveListVisible = ref(false);
    const savedCanvasList = ref([]);
    /** 默认关闭：节点只显示图标+名称；开启后在同一行右侧显示一行截断摘要 */
    const showCanvasSummary = ref(false);

    // Track dragged node type
    let dragNodeType = null;

    function escapeHtmlText(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function getNodeSummarySnippet(type, data) {
      const d = data || {};
      const trunc = (s, n = 44) => {
        const t = String(s ?? '');
        return t.length > n ? `${t.slice(0, n)}…` : t;
      };
      switch (type) {
        case 'start':
        case 'end':
        case 'loop_end':
          return '';
        case 'click':
          return trunc(d.target);
        case 'swipe':
          return trunc(`${d.start_target || '?'} → ${d.end_target || '?'}`);
        case 'sleep':
          return `${d.seconds ?? 1}s`;
        case 'input_text':
          return trunc(d.text);
        case 'key_event':
          return `key ${d.key_code ?? ''}`;
        case 'locate':
        case 'wait_for_appear':
        case 'wait_for_disappear':
          return trunc(d.target);
        case 'extract_info':
          return trunc(d.target);
        case 'ensure_in':
          return trunc(d.scene);
        case 'switch_base':
          return trunc(d.base);
        case 'if_branch':
          return trunc(d.condition);
        case 'loop':
          return `×${d.times ?? 3}`;
        case 'set_var':
          return trunc(`${d.var_name || ''} = ${d.expression || ''}`);
        case 'comment':
          return trunc(d.text, 40);
        default:
          return '';
      }
    }

    // ── Drawflow helpers ──
    function createNodeHtml(type, data) {
      const def = NODE_DEFS[type];
      if (!def) return '<div>Unknown</div>';
      const snippet = getNodeSummarySnippet(type, data);
      const showSum = showCanvasSummary.value && snippet;
      const safeSnippet = escapeHtmlText(snippet);
      const titleAttr = snippet ? ` title="${escapeHtmlText(snippet).replace(/"/g, '&quot;')}"` : '';
      return `<div class="canvas-node-content canvas-node-compact canvas-node-${def.category}">
        <div class="canvas-node-header">
          <span class="canvas-node-head-main">
            <i class="fa ${def.icon}" style="color:${def.color}"></i>
            <span class="canvas-node-title">${def.label}</span>
          </span>
          ${showSum ? `<span class="canvas-node-summary-inline"${titleAttr}>${safeSnippet}</span>` : ''}
        </div>
      </div>`;
    }

    function refreshAllNodesHtml() {
      if (!editor) return;
      const data = editor.export();
      const mod = data.drawflow?.Home?.data;
      if (!mod) return;
      Object.keys(mod).forEach((id) => updateNodeHtml(id));
    }

    function refreshConnectionPositions() {
      if (!editor || typeof editor.updateConnectionNodes !== 'function') return;
      const data = editor.export();
      const mod = data.drawflow?.Home?.data;
      if (!mod) return;
      Object.keys(mod).forEach((id) => {
        editor.updateConnectionNodes(`node-${id}`);
      });
    }

    function onCanvasSummaryToggle() {
      nextTick(() => {
        refreshAllNodesHtml();
        refreshConnectionPositions();
      });
    }

    function addNodeToCanvas(type, posX, posY, data) {
      const def = NODE_DEFS[type];
      if (!def || !editor) return;
      const nodeData = {};
      (def.params || []).forEach(p => {
        nodeData[p.key] = (data && data[p.key] !== undefined) ? data[p.key] : p.default;
      });
      nodeData._type = type;
      const html = createNodeHtml(type, nodeData);
      editor.addNode(
        type,
        def.inputs,
        def.outputs,
        posX, posY,
        'canvas-df-node',
        nodeData,
        html
      );
      updatePreview();
    }

    /** Drawflow 的 getNodeFromId 返回 JSON 深拷贝，改 node.data 不会写回内部；必须用 updateNodeDataFromId。 */
    function updateNodeHtml(nodeId) {
      if (!editor) return;
      const node = editor.getNodeFromId(nodeId);
      if (!node) return;
      const type = node.data._type;
      const html = createNodeHtml(type, node.data);
      const el = document.querySelector(`#node-${nodeId} .drawflow_content_node`);
      if (el) el.innerHTML = html;
    }

    function persistNodeData(nodeId, newData) {
      if (!editor || typeof editor.updateNodeDataFromId !== 'function') return;
      editor.updateNodeDataFromId(nodeId, newData);
    }

    // ── Node selection ──
    function onNodeSelected(nodeId) {
      if (!editor) return;
      const node = editor.getNodeFromId(nodeId);
      if (!node) { selectedNode.value = null; return; }
      const type = node.data._type;
      const def = NODE_DEFS[type];
      selectedNode.value = { id: nodeId, data: node.data };
      selectedNodeDef.value = def ? { ...def, type } : null;
      selectedNodeParams.value = (def?.params || []).map(p => ({
        ...p,
        value: node.data[p.key] !== undefined ? node.data[p.key] : p.default,
      }));
    }

    function onNodeUnselected() {
      selectedNode.value = null;
      selectedNodeDef.value = null;
      selectedNodeParams.value = [];
    }

    function onParamChange(param) {
      if (!editor || !selectedNode.value) return;
      const nodeId = selectedNode.value.id;
      const node = editor.getNodeFromId(nodeId);
      if (!node) return;
      const newData = { ...node.data, [param.key]: param.value };
      persistNodeData(nodeId, newData);
      if (selectedNode.value) selectedNode.value.data = newData;
      updateNodeHtml(nodeId);
      nextTick(() => {
        if (editor && typeof editor.updateConnectionNodes === 'function') {
          editor.updateConnectionNodes(`node-${nodeId}`);
        }
      });
      updatePreview();
    }

    // ── Drag & Drop ──
    function onNodeDragStart(ev, node) {
      dragNodeType = node.type;
      ev.dataTransfer.setData('text/plain', node.type);
      ev.dataTransfer.effectAllowed = 'move';
    }

    function onCanvasDragOver(ev) {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'move';
    }

    function onCanvasDrop(ev) {
      ev.preventDefault();
      const type = dragNodeType || ev.dataTransfer.getData('text/plain');
      if (!type || !NODE_DEFS[type]) return;
      if (!editor) return;
      const rect = drawflowEl.value.getBoundingClientRect();
      const zoom = editor.zoom;
      const x = (ev.clientX - rect.left) / zoom - editor.precanvas.getBoundingClientRect().left / zoom + rect.left / zoom;
      const y = (ev.clientY - rect.top) / zoom - editor.precanvas.getBoundingClientRect().top / zoom + rect.top / zoom;
      const canvasX = (ev.clientX - rect.left - editor.canvas_x) / zoom;
      const canvasY = (ev.clientY - rect.top - editor.canvas_y) / zoom;
      addNodeToCanvas(type, canvasX, canvasY);
      dragNodeType = null;
    }

    // ── Zoom controls ──
    function zoomIn()    { if (editor) editor.zoom_in(); }
    function zoomOut()   { if (editor) editor.zoom_out(); }
    function zoomReset() { if (editor) editor.zoom_reset(); }

    function clearCanvas() {
      ElementPlus.ElMessageBox.confirm('确定清空画布？所有节点和连线将被删除。', '清空画布', {
        confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning',
      }).then(() => {
        if (editor) editor.clear();
        selectedNode.value = null;
        previewText.value = '';
      }).catch(() => {});
    }

    // ── Code generation ──
    function getOrderedNodes() {
      if (!editor) return [];
      const data = editor.export();
      const module = data.drawflow?.Home?.data;
      if (!module) return [];

      const nodes = {};
      const incoming = {};
      const outEdges = {};
      for (const [id, node] of Object.entries(module)) {
        nodes[id] = node;
        incoming[id] = new Set();
        outEdges[id] = {};
      }
      for (const [id, node] of Object.entries(module)) {
        for (const outKey of Object.keys(node.outputs || {})) {
          const targets = [];
          for (const conn of (node.outputs[outKey]?.connections || [])) {
            incoming[conn.node]?.add(id);
            targets.push(conn.node);
          }
          outEdges[id][outKey] = targets;
        }
      }

      // For if_branch nodes, track which output port leads where
      const branchInfo = {};
      for (const [id, node] of Object.entries(module)) {
        if (node.data?._type === 'if_branch') {
          branchInfo[id] = {
            trueTargets: outEdges[id]?.['output_1'] || [],
            falseTargets: outEdges[id]?.['output_2'] || [],
          };
        }
      }

      const ordered = [];
      const visited = new Set();
      const queue = Object.keys(nodes).filter(id => incoming[id].size === 0);
      while (queue.length) {
        const id = queue.shift();
        if (visited.has(id)) continue;
        visited.add(id);
        const nodeEntry = { id, ...nodes[id] };
        if (branchInfo[id]) nodeEntry._branchInfo = branchInfo[id];
        ordered.push(nodeEntry);
        for (const outKey of Object.keys(nodes[id].outputs || {})) {
          for (const conn of (nodes[id].outputs[outKey]?.connections || [])) {
            incoming[conn.node]?.delete(id);
            if (incoming[conn.node]?.size === 0) queue.push(conn.node);
          }
        }
      }
      for (const id of Object.keys(nodes)) {
        if (!visited.has(id)) ordered.push({ id, ...nodes[id] });
      }
      return ordered;
    }

    function nodeToCode(node, indent = '    ') {
      const d = node.data || {};
      const type = d._type;
      switch (type) {
        case 'start':
        case 'end':
        case 'loop_end':
        case 'comment':
          return '';
        case 'click': {
          const parts = [d.target || 'T("确定")'];
          parts.push(`timeout=${d.timeout ?? 3}`);
          if (d.if_exist) parts.push('if_exist=True');
          if (d.repeat !== undefined && d.repeat > 1) parts.push(`repeat=${d.repeat}`);
          return `${indent}click(${parts.join(', ')})`;
        }
        case 'swipe':
          return `${indent}swipe(${d.start_target || 'B(640,500,1,1)'}, ${d.end_target || 'B(640,200,1,1)'}, duration_s=${d.duration_s ?? 1})`;
        case 'sleep':
          return `${indent}sleep(${d.seconds ?? 1})`;
        case 'input_text': {
          const field = d.target_field ? `, ${d.target_field}` : '';
          return `${indent}input("${(d.text || '').replace(/"/g, '\\"')}"${field})`;
        }
        case 'key_event':
          return `${indent}key_event(${d.key_code ?? 4})`;
        case 'locate':
          return `${indent}locate(${d.target || 'T("确定")'}${d.timeout !== undefined && d.timeout !== 0 ? ', timeout=' + d.timeout : ''})`;
        case 'wait_for_appear':
          return `${indent}wait_for_appear(${d.target || 'T("确定")'}${d.timeout !== 30 ? ', timeout=' + d.timeout : ''})`;
        case 'wait_for_disappear':
          return `${indent}wait_for_disappear(${d.target || 'T("确定")'}${d.timeout !== 30 ? ', timeout=' + d.timeout : ''})`;
        case 'extract_info':
          return `${indent}info = extract_info(${d.target || 'B(0,0,1280,720)'}, post_process=${d.post_process || 'lambda s: s.strip()'}, ensure_not_empty=${d.ensure_not_empty ? 'True' : 'False'}, digit_only=${d.digit_only ? 'True' : 'False'})`;
        case 'ensure_in':
          return `${indent}ensure_in("${(d.scene || '主界面').replace(/"/g, '\\"')}")`;
        case 'switch_base':
          return `${indent}switch_base("${(d.base || '').replace(/"/g, '\\"')}")`;
        case 'if_branch':
          return `${indent}if ${d.condition || 'ui_T(T("确定"))'}:`;
        case 'loop':
          return `${indent}for _i in range(${d.times ?? 3}):`;
        case 'set_var': {
          const vn = d.var_name || 'result';
          const expr = d.expression || 'None';
          return `${indent}${vn} = ${expr}`;
        }
        default:
          return '';
      }
    }

    function generateFullCode() {
      const nodes = getOrderedNodes();
      const name = (scriptName.value || '我的脚本').replace(/"/g, '\\"');
      const fnName = 'canvas_script_' + Date.now().toString(36);
      let lines = [
        'from AutoScriptor import *',
        'from ZmxyOL.task.task_register import register_task',
        '',
        `@register_task(path_cn="自定义任务/画布脚本/${name}")`,
        `def ${fnName}():`,
      ];

      let indent = '    ';
      let hasBody = false;
      const indentStack = [];
      for (const node of nodes) {
        const type = node.data?._type;

        // Handle loop_end: pop indent
        if (type === 'loop_end' && indent.length > 4) {
          indent = indent.substring(4);
          continue;
        }

        const code = nodeToCode(node, indent);
        if (!code) continue;
        hasBody = true;
        lines.push(code);

        // If/else: push indent, add placeholder for else branch
        if (type === 'if_branch') {
          indentStack.push(indent);
          indent += '    ';
          // Check if there's a false branch (output_2)
          if (node._branchInfo?.falseTargets?.length) {
            lines.push(indent + 'pass  # true branch body');
            indent = indentStack.pop() || '    ';
            lines.push(indent + 'else:');
            indentStack.push(indent);
            indent += '    ';
          }
        }
        if (type === 'loop') {
          indent += '    ';
        }
      }
      if (!hasBody) lines.push('    pass');
      return lines.join('\n');
    }

    function updatePreview() {
      const nodes = getOrderedNodes();
      const lines = [];
      for (const node of nodes) {
        const code = nodeToCode(node, '');
        if (code) lines.push(code.trim());
      }
      previewText.value = lines.join('\n') || '';
    }

    function previewCode() {
      fullCodePreview.value = generateFullCode();
      codeDialogVisible.value = true;
    }

    function copyGeneratedCode() {
      navigator.clipboard.writeText(fullCodePreview.value).then(
        () => ElementPlus.ElMessage.success('已复制代码'),
        () => ElementPlus.ElMessage.error('复制失败')
      );
    }

    // ── Target picker ──
    const targetPickerVisible = ref(false);
    const targetPickerMode = ref('text');
    const targetPickerImage = ref('');
    const targetPickerLoading = ref(false);
    const targetPickerSel = ref(null);
    const targetPickerText = ref('');
    const targetPickerImg = ref(null);
    let _targetPickerParam = null;
    let _tpDragging = false;
    let _tpStartX = 0, _tpStartY = 0;
    let _tpImgW = 1280, _tpImgH = 720;
    let _tpDocMove = null;
    let _tpDocUp = null;

    const TARGET_PARAM_KEYS = new Set(['target', 'start_target', 'end_target', 'target_field']);

    function isTargetParam(key) {
      return TARGET_PARAM_KEYS.has(key);
    }

    function openTargetPicker(param) {
      _targetPickerParam = param;
      targetPickerVisible.value = true;
      targetPickerSel.value = null;
      targetPickerText.value = '';
    }

    async function targetPickerRefresh() {
      targetPickerLoading.value = true;
      try {
        const res = await fetch('/api/editor/screenshot', { credentials: 'same-origin' });
        const data = await res.json();
        if (data.error) { ElementPlus.ElMessage.error(data.error); return; }
        targetPickerImage.value = 'data:image/jpeg;base64,' + data.image;
        _tpImgW = data.width || 1280;
        _tpImgH = data.height || 720;
        targetPickerSel.value = null;
      } catch (e) {
        ElementPlus.ElMessage.error('截图失败: ' + e);
      } finally {
        targetPickerLoading.value = false;
      }
    }

    function _tpCoords(ev) {
      const img = targetPickerImg.value;
      if (!img) return { x: 0, y: 0 };
      const rect = img.getBoundingClientRect();
      const scaleX = _tpImgW / rect.width;
      const scaleY = _tpImgH / rect.height;
      return {
        x: Math.round((ev.clientX - rect.left) * scaleX),
        y: Math.round((ev.clientY - rect.top) * scaleY),
      };
    }

    function _tpRemoveDocListeners() {
      if (_tpDocMove) {
        document.removeEventListener('mousemove', _tpDocMove);
        document.removeEventListener('mouseup', _tpDocUp);
        _tpDocMove = null;
        _tpDocUp = null;
      }
    }

    function onTargetImgMouseDown(ev) {
      ev.preventDefault();
      ev.stopPropagation();
      _tpDragging = true;
      const c = _tpCoords(ev);
      _tpStartX = c.x;
      _tpStartY = c.y;
      targetPickerSel.value = null;

      _tpDocMove = (e) => onTargetImgMouseMove(e);
      _tpDocUp = (e) => { onTargetImgMouseUp(e); };
      document.addEventListener('mousemove', _tpDocMove);
      document.addEventListener('mouseup', _tpDocUp, { capture: true });
    }

    function onTargetImgMouseMove(ev) {
      if (!_tpDragging) return;
      ev.preventDefault();
      const c = _tpCoords(ev);
      const img = targetPickerImg.value;
      if (!img) return;
      const rect = img.getBoundingClientRect();
      targetPickerSel.value = {
        left: Math.min(_tpStartX, c.x),
        top: Math.min(_tpStartY, c.y),
        right: Math.max(_tpStartX, c.x),
        bottom: Math.max(_tpStartY, c.y),
        dispLeft: Math.min(ev.clientX - rect.left, (_tpStartX / _tpImgW) * rect.width),
        dispTop: Math.min(ev.clientY - rect.top, (_tpStartY / _tpImgH) * rect.height),
        dispWidth: Math.abs(ev.clientX - rect.left - (_tpStartX / _tpImgW) * rect.width),
        dispHeight: Math.abs(ev.clientY - rect.top - (_tpStartY / _tpImgH) * rect.height),
      };
    }

    async function onTargetImgMouseUp(ev) {
      _tpRemoveDocListeners();
      if (!_tpDragging) return;
      _tpDragging = false;
      const c = _tpCoords(ev);
      const sel = {
        left: Math.min(_tpStartX, c.x),
        top: Math.min(_tpStartY, c.y),
        right: Math.max(_tpStartX, c.x),
        bottom: Math.max(_tpStartY, c.y),
      };
      if (sel.right - sel.left < 5 || sel.bottom - sel.top < 5) return;

      const img = targetPickerImg.value;
      const rect = img ? img.getBoundingClientRect() : { left: 0, top: 0, width: 1, height: 1 };
      targetPickerSel.value = {
        ...sel,
        dispLeft: (sel.left / _tpImgW) * rect.width,
        dispTop: (sel.top / _tpImgH) * rect.height,
        dispWidth: ((sel.right - sel.left) / _tpImgW) * rect.width,
        dispHeight: ((sel.bottom - sel.top) / _tpImgH) * rect.height,
      };

      if (targetPickerMode.value === 'text') {
        try {
          const res = await fetch('/api/editor/ocr', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ left: sel.left, top: sel.top, right: sel.right, bottom: sel.bottom }),
          });
          const data = await res.json();
          targetPickerText.value = data.text || '';
        } catch { /* ignore */ }
      }
    }

    const targetPickerSelStyle = computed(() => {
      const s = targetPickerSel.value;
      if (!s) return {};
      return {
        left: s.dispLeft + 'px',
        top: s.dispTop + 'px',
        width: s.dispWidth + 'px',
        height: s.dispHeight + 'px',
      };
    });

    const targetPickerResultCode = computed(() => {
      const s = targetPickerSel.value;
      if (!s) return '';
      const mode = targetPickerMode.value;
      if (mode === 'box') {
        const w = s.right - s.left;
        const h = s.bottom - s.top;
        return `B(${s.left},${s.top},${w},${h})`;
      }
      const t = (targetPickerText.value || '').trim();
      if (!t) return '';
      const w = s.right - s.left;
      const h = s.bottom - s.top;
      const boxPart = (s.left === 0 && s.top === 0 && w >= 1280 && h >= 720)
        ? '' : `, box=Box(${s.left},${s.top},${w},${h}).margin()`;
      if (mode === 'text') return `T("${t}"${boxPart})`;
      if (mode === 'image') return `I("${t}"${boxPart})`;
      return '';
    });

    function confirmTargetPicker() {
      const code = targetPickerResultCode.value;
      if (!code || !_targetPickerParam) return;
      _targetPickerParam.value = code;
      onParamChange(_targetPickerParam);
      targetPickerVisible.value = false;
    }

    // ── Canvas load dialog ──
    async function openLoadDialog() {
      await fetchCanvasList();
      saveListVisible.value = true;
    }

    // ── Save / Load ──
    async function generateAndSave() {
      if (!scriptName.value.trim()) {
        ElementPlus.ElMessage.warning('请输入脚本名称');
        return;
      }
      if (!editor) return;
      saving.value = true;
      try {
        const graphData = editor.export();
        const code = generateFullCode();
        const res = await fetch('/api/canvas/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            name: scriptName.value.trim(),
            graph: graphData,
            code,
            _timestamp: Date.now() / 1000,
          }),
        });
        const data = await res.json();
        if (data.error) {
          ElementPlus.ElMessage.error(data.error);
        } else {
          ElementPlus.ElMessage.success(data.message || '保存成功');
        }
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败: ' + e);
      } finally {
        saving.value = false;
      }
    }

    async function fetchCanvasList() {
      try {
        const res = await fetch('/api/canvas/list', { credentials: 'same-origin' });
        const data = await res.json();
        savedCanvasList.value = data.canvases || [];
      } catch (e) {
        console.error('fetchCanvasList', e);
      }
    }

    async function loadCanvas(name) {
      try {
        const res = await fetch('/api/canvas/load?name=' + encodeURIComponent(name), { credentials: 'same-origin' });
        const data = await res.json();
        if (data.error) { ElementPlus.ElMessage.error(data.error); return; }
        if (editor && data.graph) {
          editor.import(data.graph);
          scriptName.value = name;
          nextTick(() => {
            refreshAllNodesHtml();
            refreshConnectionPositions();
          });
          updatePreview();
          ElementPlus.ElMessage.success('已加载画布: ' + name);
          saveListVisible.value = false;
        }
      } catch (e) {
        ElementPlus.ElMessage.error('加载失败: ' + e);
      }
    }

    async function deleteCanvas(name) {
      try {
        await ElementPlus.ElMessageBox.confirm(`确定删除「${name}」？`, '删除画布', {
          confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
        });
        const res = await fetch('/api/canvas/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ name, _timestamp: Date.now() / 1000 }),
        });
        const data = await res.json();
        if (data.error) { ElementPlus.ElMessage.error(data.error); return; }
        ElementPlus.ElMessage.success('已删除');
        fetchCanvasList();
      } catch { /* cancelled */ }
    }

    // ── Lifecycle ──
    onMounted(() => {
      nextTick(() => {
        if (!drawflowEl.value) return;
        editor = new Drawflow(drawflowEl.value);
        editor.reroute = true;
        editor.reroute_fix_curvature = true;
        editor.force_first_input = false;
        editor.start();

        editor.on('nodeSelected', onNodeSelected);
        editor.on('nodeUnselected', onNodeUnselected);
        editor.on('connectionCreated', () => updatePreview());
        editor.on('connectionRemoved', () => updatePreview());
        editor.on('nodeRemoved', () => { onNodeUnselected(); updatePreview(); });
        editor.on('nodeMoved', () => updatePreview());

        // 默认起始节点（竖向编排时从上往下拖线）
        addNodeToCanvas('start', 140, 40);
      });
    });

    onBeforeUnmount(() => {
      if (editor) {
        editor.on('nodeSelected', null);
        editor.on('nodeUnselected', null);
      }
      editor = null;
    });

    return {
      nodeGroups, drawflowEl,
      scriptName, saving,
      selectedNode, selectedNodeDef, selectedNodeParams,
      previewText, codeDialogVisible, fullCodePreview,
      saveListVisible, savedCanvasList,
      onNodeDragStart, onCanvasDragOver, onCanvasDrop,
      onParamChange,
      zoomIn, zoomOut, zoomReset, clearCanvas,
      previewCode, copyGeneratedCode,
      generateAndSave, fetchCanvasList, loadCanvas, deleteCanvas,
      updatePreview, openLoadDialog,
      isTargetParam, openTargetPicker,
      targetPickerVisible, targetPickerMode, targetPickerImage, targetPickerLoading,
      targetPickerSel, targetPickerSelStyle, targetPickerText,
      targetPickerResultCode, targetPickerImg,
      targetPickerRefresh, onTargetImgMouseDown, onTargetImgMouseMove, onTargetImgMouseUp,
      confirmTargetPicker,
      showCanvasSummary,
      onCanvasSummaryToggle,
    };
  },
};
