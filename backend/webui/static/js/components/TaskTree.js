/** @param {Record<string, unknown>|undefined|null} params */
function buildDisplayParams(params) {
  if (!params || typeof params !== 'object') return {};
  const methodDisplay = { YAOSHI: '购买符印之匙', QILING: '购买唤灵之心' };
  const result = {};
  let count = 0;
  for (const [k, v] of Object.entries(params)) {
    if (count >= 3) break;
    if (k === 'param_meta' || k === 'profession') continue;
    if (typeof v === 'boolean' || Array.isArray(v) || (typeof v === 'object' && v !== null)) continue;
    const shown = k === 'method' && methodDisplay[v] ? methodDisplay[v] : v;
    if (typeof shown === 'string' && shown.length > 12) continue;
    result[k] = shown;
    count++;
  }
  return result;
}

function resetTaskActivation(taskItem) {
  delete taskItem.human_takeover;
  delete taskItem.human_takeover_error;
  delete taskItem.human_takeover_at;
  delete taskItem.error;
  delete taskItem.progress;
  delete taskItem.progress_display;
  taskItem.next_exec_time = 0;
  taskItem._due = true;
}

/** 与 buildDisplayParams 相同过滤规则，统计全部可变参数数量（不受 3 条展示上限影响） */
function countVariableParams(params) {
  if (!params || typeof params !== 'object') return 0;
  const methodDisplay = { YAOSHI: '购买符印之匙', QILING: '购买唤灵之心' };
  let n = 0;
  for (const [k, v] of Object.entries(params)) {
    if (k === 'param_meta' || k === 'profession') continue;
    if (typeof v === 'boolean' || Array.isArray(v) || (typeof v === 'object' && v !== null)) continue;
    const shown = k === 'method' && methodDisplay[v] ? methodDisplay[v] : v;
    if (typeof shown === 'string' && shown.length > 12) continue;
    n++;
  }
  return n;
}

const TaskTreeTaskRow = {
  name: 'TaskTreeTaskRow',
  props: {
    taskKey: { type: String, required: true },
    item: { type: Object, required: true },
    taskPath: { type: String, required: true },
    runTaskDisabled: { type: Boolean, default: false },
    reorderDisabled: { type: Boolean, default: false },
  },
  emits: ['edit-task', 'run-task', 'restart-task', 'reorder-task'],
  data() {
    return {
      collapsed: false,
      resizeObserver: null,
    };
  },
  computed: {
    displayParamsObj() {
      return buildDisplayParams(this.item.params);
    },
    variableCount() {
      return countVariableParams(this.item.params);
    },
    hasTags() {
      return Object.keys(this.displayParamsObj).length > 0;
    },
  },
  watch: {
    item: {
      deep: true,
      handler() {
        this.$nextTick(() => this.measure());
      },
    },
  },
  template: `
<div class="task-tree-item bg-gray-50 px-3.5 py-2.5 rounded-lg border border-gray-200 hover:border-primary/40 hover:bg-gray-100 transition-colors flex flex-col gap-1 min-w-0 max-w-full"
     :draggable="!reorderDisabled"
     :title="reorderDisabled ? '' : '拖拽到另一任务上方，保存为软排序'"
     @dragstart="startTaskDrag"
     @dragover.prevent
     @drop.prevent="dropTaskHere">
  <div class="flex items-center gap-2 min-w-0 w-full">
    <span :class="[
            'inline-flex items-start gap-1 min-w-0 max-w-[min(46%,11rem)] shrink',
            runTaskDisabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'
          ]"
          :title="runTaskDisabled ? '执行中不能编辑任务配置' : '编辑任务配置'"
          @click.stop="openTaskEditor">
      <span class="font-medium text-sm text-dark truncate">{{ taskKey }}</span>
      <span v-if="item.custom" class="task-custom-tag">自定义</span>
      <span v-if="item.beta" class="task-beta-tag">Beta</span>
    </span>
    <div class="relative flex-1 min-w-0 flex items-center min-h-[1.5rem]">
      <div ref="measureWrap" class="absolute left-0 top-0 z-[-1] flex items-center gap-2 opacity-0 pointer-events-none whitespace-nowrap" aria-hidden="true">
        <span v-for="(v, k) in displayParamsObj" :key="'m-' + k" class="inline-flex items-center px-2 py-0.5 rounded bg-gray-200 text-gray-600 text-sm whitespace-nowrap">{{ v }}</span>
      </div>
      <div ref="paramsContainer" class="flex-1 min-w-0 overflow-hidden flex items-center gap-2">
        <template v-if="hasTags && collapsed">
          <span class="inline-flex items-center px-2 py-0.5 rounded bg-gray-200 text-gray-600 text-sm truncate min-w-0"
                :title="variableCount + '个可变配置'">{{ variableCount }}个可变配置</span>
        </template>
        <template v-else-if="hasTags">
          <span v-for="(v, k) in displayParamsObj" :key="k"
                class="inline-flex items-center px-2 py-0.5 rounded bg-gray-200 text-gray-600 text-sm whitespace-nowrap shrink-0"
                :title="k">{{ v }}</span>
        </template>
      </div>
    </div>
    <div class="flex items-center gap-2 flex-shrink-0">
      <span :class="[
              'text-sm px-3 py-0.5 rounded-full whitespace-nowrap font-medium',
              runTaskDisabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
              statusTheme(item).badgeClass
            ]"
            :title="runTaskDisabled ? '执行中不能修改任务状态' : (getTaskStatus(item)==='error' ? '点击关闭并重新开启，刷新为待执行' : '点击切换启用状态')"
            @click.stop="handleStatusClick(item)">
        {{ statusTheme(item).label }}
        <span v-if="item.progress_display" class="ml-1 text-[10px] align-super">{{ item.progress_display }}</span>
      </span>
      <button type="button"
              class="w-7 h-7 flex items-center justify-center rounded-full bg-primary/10 hover:bg-primary/25 text-primary transition-colors flex-shrink-0 disabled:opacity-40 disabled:pointer-events-none"
              :disabled="runTaskDisabled"
              @click.stop="$emit('run-task', taskPath)"
              title="运行此任务">
        <i class="fa fa-play text-xs"></i>
      </button>
    </div>
  </div>
</div>`,
  mounted() {
    this.setupResizeObserver();
    this.$nextTick(() => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => this.measure());
      });
    });
  },
  beforeUnmount() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
  },
  methods: {
    getTaskStatus(taskItem) {
      return window.TaskStatusTheme?.getTaskStatus(taskItem) || 'disabled';
    },
    statusTheme(taskItem) {
      return window.TaskStatusTheme?.getTaskTheme(taskItem) || { label: '未知', badgeClass: 'bg-gray-200 text-gray-600' };
    },
    openTaskEditor() {
      if (this.runTaskDisabled) {
        ElementPlus.ElMessage.warning('执行中不能编辑任务配置，请先终止当前任务');
        return;
      }
      this.$emit('edit-task', this.taskKey, this.item, this.taskPath);
    },
    toggleTask(taskItem) {
      if (this.runTaskDisabled) {
        ElementPlus.ElMessage.warning('执行中不能修改任务状态，请先终止当前任务');
        return;
      }
      taskItem.on = !taskItem.on;
      if (taskItem.on) resetTaskActivation(taskItem);
      else taskItem._due = false;
    },
    restartTask(taskItem) {
      if (this.runTaskDisabled) {
        ElementPlus.ElMessage.warning('执行中不能修改任务状态，请先终止当前任务');
        return;
      }
      taskItem.on = false;
      resetTaskActivation(taskItem);
      taskItem.on = true;
      this.$emit('restart-task');
    },
    async handleStatusClick(taskItem) {
      if (this.getTaskStatus(taskItem) === 'error' && taskItem.on) {
        const detail = taskItem.human_takeover_error ? `\n${taskItem.human_takeover_error}` : '';
        try {
          await ElementPlus.ElMessageBox.confirm(
            `关闭并重新开启此任务，将清除错误状态并设为待执行。${detail}`,
            '重新开启任务',
            { confirmButtonText: '重新开启', cancelButtonText: '取消', type: 'warning' },
          );
        } catch { return; }
        this.restartTask(taskItem);
        return;
      }
      this.toggleTask(taskItem);
    },
    startTaskDrag(event) {
      if (this.reorderDisabled) return;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', this.taskPath);
    },
    dropTaskHere(event) {
      if (this.reorderDisabled) return;
      const sourcePath = event.dataTransfer.getData('text/plain');
      if (!sourcePath || sourcePath === this.taskPath) return;
      this.$emit('reorder-task', { sourcePath, targetPath: this.taskPath });
    },
    setupResizeObserver() {
      this.resizeObserver = new ResizeObserver(() => this.measure());
      this.$nextTick(() => {
        const el = this.$refs.paramsContainer;
        if (el) this.resizeObserver.observe(el);
      });
    },
    measure() {
      const pc = this.$refs.paramsContainer;
      const mw = this.$refs.measureWrap;
      if (!pc || !mw || !this.hasTags) {
        this.collapsed = false;
        return;
      }
      const need = mw.scrollWidth;
      const avail = pc.clientWidth;
      this.collapsed = need > avail + 1;
    },
  },
};

const TaskTree = {
  name: 'TaskTree',
  components: { TaskTreeTaskRow },
  props: {
    treeData: { type: Object, required: true },
    basePath: { type: String, default: '' },
    depth: { type: Number, default: 0 },
    runTaskDisabled: { type: Boolean, default: false },
    reorderDisabled: { type: Boolean, default: false },
  },
  emits: ['edit-task', 'expanded-change', 'run-task', 'restart-task', 'reorder-task'],
  data() {
    return {
      expanded: {},
      statusClasses: {
        disabled: 'bg-gray-200 text-gray-600',
        pending: 'bg-yellow-200 text-yellow-600',
        scheduled: 'bg-green-200 text-green-600',
        error: 'bg-red-200 text-red-600',
      },
      statusLabels: {
        disabled: '未启用',
        pending: '待执行',
        scheduled: '已完成',
        error: '错误',
      },
    };
  },
  template: `
<div class="space-y-1 min-w-0">
  <template v-for="key in objectKeys(treeData)" :key="key">
    <!-- 叶子任务行 -->
    <task-tree-task-row v-if="isTask(treeData[key])"
      :task-key="key"
      :item="treeData[key]"
      :task-path="childBasePath(key)"
      :run-task-disabled="runTaskDisabled"
      :reorder-disabled="reorderDisabled"
      @edit-task="(childKey, item, path) => $emit('edit-task', childKey, item, path)"
      @run-task="path => $emit('run-task', path)"
      @restart-task="$emit('restart-task')"
      @reorder-task="payload => $emit('reorder-task', payload)">
    </task-tree-task-row>
    <!-- 一级分组 (depth=0) -->
    <div v-else-if="depth === 0" class="task-group-l1">
      <div class="flex items-center py-3 px-3 cursor-pointer group rounded-xl hover:bg-primary/5 transition-colors" @click.stop="toggleExpand(key)">
        <i :class="[expanded[key] ? 'fa fa-chevron-down' : 'fa fa-chevron-right', 'text-xs text-primary/70 group-hover:text-primary transition-colors w-3.5 flex-shrink-0']"></i>
        <span class="ml-2.5 font-bold text-base text-dark tracking-wide">{{ key }}</span>
        <span v-if="countStatus(treeData[key]).error > 0"
              class="ml-2 text-xs px-2 py-0.5 rounded-full font-semibold" :class="statusClasses['error']">
          {{ countStatus(treeData[key]).error }}
        </span>
        <span v-if="countStatus(treeData[key]).pending > 0"
              class="ml-2 text-xs px-2 py-0.5 rounded-full font-semibold bg-yellow-100 text-yellow-700">
          {{ countStatus(treeData[key]).pending }}
        </span>
      </div>
      <transition name="expand">
        <div v-if="expanded[key]" class="ml-3 pl-3 border-l-2 border-primary/20">
          <task-tree
            :tree-data="treeData[key]" :base-path="childBasePath(key)" :depth="depth + 1"
            :run-task-disabled="runTaskDisabled"
            :reorder-disabled="reorderDisabled"
            @edit-task="(childKey, item, path) => $emit('edit-task', childKey, item, path)"
            @expanded-change="$emit('expanded-change', $event)"
            @run-task="path => $emit('run-task', path)"
            @restart-task="$emit('restart-task')"
            @reorder-task="payload => $emit('reorder-task', payload)">
          </task-tree>
        </div>
      </transition>
    </div>
    <!-- 二级及以下分组 (depth>=1) -->
    <div v-else class="task-group-l2">
      <div class="flex items-center py-2 px-2.5 cursor-pointer group rounded-lg hover:bg-gray-50 transition-colors" @click.stop="toggleExpand(key)">
        <i :class="[expanded[key] ? 'fa fa-chevron-down' : 'fa fa-chevron-right', 'text-xs text-gray-400 group-hover:text-primary/70 transition-colors w-3 flex-shrink-0']"></i>
        <span class="ml-2 text-sm font-semibold text-gray-500">{{ key }}</span>
        <span v-if="countStatus(treeData[key]).error > 0"
              class="ml-2 text-xs px-2 py-0.5 rounded-full font-medium" :class="statusClasses['error']">
          {{ countStatus(treeData[key]).error }}
        </span>
        <span v-if="countStatus(treeData[key]).pending > 0"
              class="ml-1.5 text-xs px-2 py-0.5 rounded-full font-medium bg-yellow-50 text-yellow-600">
          {{ countStatus(treeData[key]).pending }}
        </span>
      </div>
      <transition name="expand">
        <div v-if="expanded[key]" class="ml-2 pl-2 border-l border-gray-200">
          <task-tree
            :tree-data="treeData[key]" :base-path="childBasePath(key)" :depth="depth + 1"
            :run-task-disabled="runTaskDisabled"
            :reorder-disabled="reorderDisabled"
            @edit-task="(childKey, item, path) => $emit('edit-task', childKey, item, path)"
            @expanded-change="$emit('expanded-change', $event)"
            @run-task="path => $emit('run-task', path)"
            @restart-task="$emit('restart-task')"
            @reorder-task="payload => $emit('reorder-task', payload)">
          </task-tree>
        </div>
      </transition>
    </div>
  </template>
</div>`,
  methods: {
    displayParams(params) {
      return buildDisplayParams(params);
    },
    paramTagType(key) {
      return { battle_times: 'success', difficulty: 'warning' }[key] || '';
    },
    isTask(item) {
      return item && item.hasOwnProperty('on');
    },
    objectKeys(obj) {
      return Object.keys(obj || {});
    },
    toggleExpand(key) {
      const willOpen = !this.expanded[key];
      Object.keys(this.expanded).forEach(k => (this.expanded[k] = false));
      if (willOpen) this.expanded[key] = true;
      const path = this.childBasePath(key);
      this.$emit('expanded-change', willOpen ? path : this.basePath);
    },
    toggleTask(item) {
      if (this.runTaskDisabled) {
        ElementPlus.ElMessage.warning('执行中不能修改任务状态，请先终止当前任务');
        return;
      }
      item.on = !item.on;
      if (item.on) resetTaskActivation(item);
      else item._due = false;
    },
    getTaskStatus(item) {
      if (!item.on) return 'disabled';
      if (item.error) return 'error';
      if ((item.human_takeover || item.human_takeover_error) && !item._due) return 'error';
      return item._due ? 'pending' : 'scheduled';
    },
    countStatus(section) {
      const c = { disabled: 0, pending: 0, scheduled: 0, error: 0 };
      Object.values(section).forEach(item => {
        if (this.isTask(item)) {
          c[this.getTaskStatus(item)]++;
        } else if (typeof item === 'object') {
          const s = this.countStatus(item);
          Object.keys(c).forEach(k => (c[k] += s[k]));
        }
      });
      return c;
    },
    childBasePath(key) {
      return this.basePath ? `${this.basePath}/${key}` : key;
    },
  },
};
