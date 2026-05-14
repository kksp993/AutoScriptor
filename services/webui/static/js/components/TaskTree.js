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
    parentTree: { type: Object, required: true },
    runTaskDisabled: { type: Boolean, default: false },
  },
  emits: ['edit-task', 'run-task'],
  data() {
    return {
      collapsed: false,
      resizeObserver: null,
      statusClasses: {
        disabled: 'bg-gray-200 text-gray-600',
        pending: 'bg-yellow-200 text-yellow-600',
        scheduled: 'bg-green-200 text-green-600',
        error: 'bg-red-200 text-red-600',
      },
      statusLabels: {
        disabled: '未启用',
        pending: '待执行',
        scheduled: '待执行',
        error: '错误',
      },
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
<div class="task-tree-item bg-gray-50 px-3.5 py-2.5 rounded-lg border border-gray-200 hover:border-primary/40 hover:bg-gray-100 transition-colors flex flex-col gap-1 min-w-0 max-w-full">
  <div class="flex items-center gap-2 min-w-0 w-full">
    <span class="inline-flex items-start gap-1 min-w-0 max-w-[min(46%,11rem)] shrink cursor-pointer"
          @click.stop="$emit('edit-task', taskKey, item, taskPath, parentTree)">
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
      <span :class="['text-sm px-3 py-0.5 rounded-full cursor-pointer whitespace-nowrap font-medium', statusClasses[getTaskStatus(item)]]"
            @click.stop="toggleTask(item)">
        {{ statusLabels[getTaskStatus(item)] }}
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
      if (!taskItem.on) return 'disabled';
      if (taskItem.error) return 'error';
      return taskItem._due ? 'pending' : 'scheduled';
    },
    toggleTask(taskItem) {
      taskItem.on = !taskItem.on;
      if (taskItem.on) { taskItem.next_exec_time = 0; taskItem._due = true; }
      else { taskItem._due = false; }
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
  },
  emits: ['edit-task', 'expanded-change', 'run-task'],
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
        scheduled: '待执行',
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
      :parent-tree="treeData"
      :run-task-disabled="runTaskDisabled"
      @edit-task="(childKey, item, path, parent) => $emit('edit-task', childKey, item, path, parent)"
      @run-task="path => $emit('run-task', path)">
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
            @edit-task="(childKey, item, path, parent) => $emit('edit-task', childKey, item, path, parent)"
            @expanded-change="$emit('expanded-change', $event)"
            @run-task="path => $emit('run-task', path)">
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
            @edit-task="(childKey, item, path, parent) => $emit('edit-task', childKey, item, path, parent)"
            @expanded-change="$emit('expanded-change', $event)"
            @run-task="path => $emit('run-task', path)">
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
      item.on = !item.on;
      if (item.on) item.next_exec_time = 0;
    },
    getTaskStatus(item) {
      if (!item.on) return 'disabled';
      if (item.error) return 'error';
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
