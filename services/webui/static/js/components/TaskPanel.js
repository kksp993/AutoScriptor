const TaskPanel = {
  name: 'TaskPanel',
  props: {
    activeTab: { type: String, default: '' },
    currentTasks: { type: Object, required: true },
    logs: { type: Array, required: true },
    characterName: { type: String, default: '' },
    schedulerStatus: { type: Object, required: true },
    executionBusy: { type: Boolean, default: false },
    runtimeStatus: { type: Object, default: null },
    orderingProjection: { type: Object, default: null },
    orderingSaving: { type: Boolean, default: false },
  },
  emits: [
    'edit-task', 'expanded-change', 'start-run', 'stop-dispatch',
    'save-tasks', 'restart-task',
    'clear-logs', 'refresh-config', 'reset-scheduler', 'run-task', 'run-task-range',
    'save-task-ordering',
    'reorder-task',
  ],
  data() {
    return {
      showOnlyEnabledOrderingItems: false,
      orderingDropHint: null,
      selectedEnabledTaskPath: '',
      guidedOrderingTaskPath: '',
      guidedOrderingTaskTimer: null,
      transientExpandedOrderingGroupIds: [],
    };
  },
  computed: {
    taskRows() {
      const rows = [];
      const visit = (node, prefix = '') => {
        for (const [key, value] of Object.entries(node || {})) {
          if (!value || typeof value !== 'object') continue;
          const path = prefix ? `${prefix}/${key}` : key;
          if (Object.prototype.hasOwnProperty.call(value, 'on')) {
            rows.push({ key, path, item: value, group: path.split('/')[0] || '', depth: path.split('/').length });
          } else {
            visit(value, path);
          }
        }
      };
      visit(this.currentTasks || {});
      return rows;
    },
    orderedTaskRows() {
      const rowByPath = new Map(this.taskRows.map((row) => [row.path, row]));
      const projectionOrder = Array.isArray(this.orderingProjection?.effective_order)
        ? this.orderingProjection.effective_order
        : [];
      const orderedRows = [];
      for (const path of projectionOrder) {
        const row = rowByPath.get(path);
        if (row && !orderedRows.includes(row)) orderedRows.push(row);
      }
      for (const row of this.taskRows) {
        if (!orderedRows.includes(row)) orderedRows.push(row);
      }
      return orderedRows;
    },
    orderingItems() {
      return this.buildOrderingItemsFromProjection();
    },
    visibleOrderingNodes() {
      return this.flattenOrderingItemsForDisplay(this.orderingItems);
    },
    enabledTaskRows() {
      return this.orderedTaskRows.filter((row) => row.item?.on);
    },
    selectedEnabledTaskIndex() {
      return this.enabledTaskRows.findIndex((row) => row.path === this.selectedEnabledTaskPath);
    },
    selectedEnabledTaskRows() {
      return this.selectedEnabledTaskIndex >= 0 ? this.enabledTaskRows.slice(this.selectedEnabledTaskIndex) : [];
    },
    currentRunningTaskPath() {
      const runtimeActive = this.executionBusy || this.runtimeStatus?.running === true || this.runtimeStatus?.busy === true;
      if (!runtimeActive) return '';
      return String(this.runtimeStatus?.current_task_path || '').trim();
    },
    orderingDiagnostics() {
      return Array.isArray(this.orderingProjection?.diagnostics) ? this.orderingProjection.diagnostics : [];
    },
  },
  methods: {
    getTaskStatus(taskItem) {
      return window.TaskStatusTheme?.getTaskStatus(taskItem) || (taskItem?.on ? 'pending' : 'disabled');
    },
    statusTheme(taskItem) {
      return window.TaskStatusTheme?.getTaskTheme(taskItem) || { label: taskItem?.on ? '待执行' : '未启用', badgeClass: 'bg-gray-200 text-gray-600' };
    },
    taskStatusDotStyle(taskItem) {
      const status = this.getTaskStatus(taskItem);
      const theme = this.statusTheme(taskItem);
      const color = theme.nodeStroke || { scheduled: '#22c55e', pending: '#f59e0b', error: '#ef4444', disabled: '#cbd5e1' }[status] || '#cbd5e1';
      return {
        backgroundColor: color,
        boxShadow: status === 'pending' ? `0 0 0 3px ${color}22` : 'none',
      };
    },
    taskStatusLabel(taskItem) {
      return this.statusTheme(taskItem).label || '未知';
    },
    orderingNumberClass(node) {
      return node?.row?.item?.on ? 'bg-primary/10 text-primary' : 'bg-slate-100 text-slate-400';
    },
    isEnabledTaskSelected(row) {
      return !!row?.path && row.path === this.selectedEnabledTaskPath;
    },
    isEnabledTaskCurrent(row) {
      return !!row?.path && !!this.currentRunningTaskPath && row.path === this.currentRunningTaskPath;
    },
    isEnabledTaskHighlighted(row) {
      return this.isEnabledTaskSelected(row) || this.isEnabledTaskCurrent(row);
    },
    enabledTaskRowClass(row) {
      if (this.isEnabledTaskCurrent(row)) {
        return 'task-enabled-row-selected task-enabled-row-current bg-primary/10 border-primary/50 text-slate-900';
      }
      if (this.isEnabledTaskSelected(row)) {
        return 'task-enabled-row-selected bg-primary/10 border-primary/40 text-slate-900';
      }
      return 'border-transparent hover:border-primary/20 hover:bg-slate-50';
    },
    selectEnabledTask(row) {
      if (!row?.path) return;
      this.selectedEnabledTaskPath = row.path;
      this.scrollOrderingTaskIntoView(row.path);
    },
    runSelectedEnabledTaskRange() {
      if (this.executionBusy) return;
      if (!this.selectedEnabledTaskRows.length) {
        ElementPlus.ElMessage.info('请先选择一个已启用任务');
        return;
      }
      this.$emit('run-task-range', this.selectedEnabledTaskRows.map((row) => row.path));
    },
    displayPath(path) {
      return String(path || '').split('/').join(' / ');
    },
    rowSubtitle(row) {
      const parts = String(row.path || '').split('/');
      return parts.length > 1 ? parts.slice(0, -1).join(' / ') : '根目录';
    },
    formatParamChips(params) {
      const formatter = window.buildDisplayParams || (typeof buildDisplayParams === 'function' ? buildDisplayParams : null);
      const displayParams = formatter ? formatter(params) : {};
      return Object.values(displayParams).slice(0, 3);
    },
    openTaskEditor(row) {
      if (this.executionBusy) {
        ElementPlus.ElMessage.warning('执行中不能编辑任务配置，请先终止当前任务');
        return;
      }
      this.$emit('edit-task', row.key, row.item, row.path);
    },
    resetTaskActivation(taskItem) {
      delete taskItem.human_takeover;
      delete taskItem.human_takeover_error;
      delete taskItem.human_takeover_at;
      delete taskItem.error;
      delete taskItem.progress;
      delete taskItem.progress_display;
      taskItem.next_exec_time = 0;
      taskItem._due = true;
    },
    toggleTask(row) {
      if (this.executionBusy) {
        ElementPlus.ElMessage.warning('执行中不能修改任务状态，请先终止当前任务');
        return;
      }
      row.item.on = !row.item.on;
      if (row.item.on) this.resetTaskActivation(row.item);
      else row.item._due = false;
    },
    makeTaskOrderingNode(path) {
      return { type: 'task', path };
    },
    makeGroupOrderingNode(children, name = '分组') {
      return {
        type: 'group',
        id: `group-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        name,
        expanded: true,
        items: children,
      };
    },
    normalizeOrderingItemForUi(rawItem) {
      if (!rawItem || typeof rawItem !== 'object') return null;
      if (rawItem.type === 'group' || Array.isArray(rawItem.items)) {
        const children = (rawItem.items || [])
          .map((child) => this.normalizeOrderingItemForUi(child))
          .filter(Boolean);
        if (!children.length) return null;
        if (children.length === 1) return children[0];
        return {
          type: 'group',
          id: String(rawItem.id || `group-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
          name: String(rawItem.name || '分组').trim() || '分组',
          expanded: rawItem.expanded !== false,
          items: children,
        };
      }
      const path = String(rawItem.path || rawItem.task_path || '').trim();
      if (!path) return null;
      return this.makeTaskOrderingNode(path);
    },
    buildOrderingItemsFromProjection() {
      const rowByPath = new Map(this.orderedTaskRows.map((row) => [row.path, row]));
      const seenPaths = new Set();
      const sourceItems = Array.isArray(this.orderingProjection?.overlay?.items)
        ? this.orderingProjection.overlay.items
        : [];
      const normalizedItems = [];
      const appendItem = (item) => {
        const normalizedItem = this.normalizeOrderingItemForUi(item);
        if (!normalizedItem) return;
        const cleanedItem = this.removeMissingAndDuplicateTasks(normalizedItem, rowByPath, seenPaths);
        if (cleanedItem) normalizedItems.push(cleanedItem);
      };
      for (const item of sourceItems) appendItem(item);
      for (const row of this.orderedTaskRows) {
        if (!seenPaths.has(row.path)) {
          seenPaths.add(row.path);
          normalizedItems.push(this.makeTaskOrderingNode(row.path));
        }
      }
      return this.collapseSingletonGroups(normalizedItems);
    },
    removeMissingAndDuplicateTasks(item, rowByPath, seenPaths) {
      if (!item || typeof item !== 'object') return null;
      if (item.type === 'group') {
        const children = (item.items || [])
          .map((child) => this.removeMissingAndDuplicateTasks(child, rowByPath, seenPaths))
          .filter(Boolean);
        if (!children.length) return null;
        if (children.length === 1) return children[0];
        return { ...item, items: children };
      }
      const path = String(item.path || '').trim();
      if (!path || !rowByPath.has(path) || seenPaths.has(path)) return null;
      seenPaths.add(path);
      return this.makeTaskOrderingNode(path);
    },
    collapseSingletonGroups(items) {
      const collapsedItems = [];
      for (const item of items || []) {
        if (!item || typeof item !== 'object') continue;
        if (item.type !== 'group') {
          collapsedItems.push(item);
          continue;
        }
        const children = this.collapseSingletonGroups(item.items || []);
        if (!children.length) continue;
        if (children.length === 1) {
          collapsedItems.push(children[0]);
          continue;
        }
        collapsedItems.push({ ...item, items: children });
      }
      return collapsedItems;
    },
    flattenOrderingPaths(items) {
      const paths = [];
      const visit = (nodes) => {
        for (const item of nodes || []) {
          if (item?.type === 'group') {
            visit(item.items || []);
          } else if (item?.path) {
            paths.push(item.path);
          }
        }
      };
      visit(items);
      return paths;
    },
    flattenOrderingItemsForDisplay(items, depth = 0) {
      const nodes = [];
      const rowByPath = new Map(this.taskRows.map((row) => [row.path, row]));
      for (const item of items || []) {
        if (item?.type === 'group') {
          const childNodes = this.flattenOrderingItemsForDisplay(item.items || [], depth + 1);
          if (this.showOnlyEnabledOrderingItems && !childNodes.length) continue;
          nodes.push({ type: 'group', item, key: item.id, depth, childCount: this.flattenOrderingPaths(item.items || []).length });
          if (this.isOrderingGroupExpanded(item)) nodes.push(...childNodes);
          continue;
        }
        const row = rowByPath.get(item?.path);
        if (!row) continue;
        if (this.showOnlyEnabledOrderingItems && !row.item?.on) continue;
        nodes.push({ type: 'task', item, row, key: row.path, depth });
      }
      return nodes;
    },
    isOrderingGroupExpanded(groupItem) {
      const groupId = String(groupItem?.id || '').trim();
      return groupItem?.expanded !== false || (!!groupId && this.transientExpandedOrderingGroupIds.includes(groupId));
    },
    isOrderingTaskGuided(node) {
      return node?.type === 'task' && !!node.row?.path && node.row.path === this.guidedOrderingTaskPath;
    },
    findOrderingGroupIdsContainingTask(items, taskPath) {
      const normalizedTaskPath = String(taskPath || '').trim();
      if (!normalizedTaskPath) return [];
      const visit = (nodes, ancestorGroupIds) => {
        for (const item of nodes || []) {
          if (item?.type === 'task' && item.path === normalizedTaskPath) return ancestorGroupIds;
          if (item?.type === 'group') {
            const groupId = String(item.id || '').trim();
            const nextAncestorGroupIds = groupId ? [...ancestorGroupIds, groupId] : ancestorGroupIds;
            const result = visit(item.items || [], nextAncestorGroupIds);
            if (result) return result;
          }
        }
        return null;
      };
      return visit(items || [], []) || [];
    },
    revealOrderingTaskPath(taskPath) {
      const groupIds = this.findOrderingGroupIdsContainingTask(this.orderingItems, taskPath);
      if (!groupIds.length) return;
      const nextGroupIds = new Set(this.transientExpandedOrderingGroupIds.map((groupId) => String(groupId)));
      let changed = false;
      for (const groupId of groupIds) {
        if (!nextGroupIds.has(groupId)) {
          nextGroupIds.add(groupId);
          changed = true;
        }
      }
      if (changed) this.transientExpandedOrderingGroupIds = Array.from(nextGroupIds);
    },
    scrollOrderingTaskIntoView(taskPath) {
      const normalizedTaskPath = String(taskPath || '').trim();
      if (!normalizedTaskPath) return;
      this.revealOrderingTaskPath(normalizedTaskPath);
      this.guidedOrderingTaskPath = normalizedTaskPath;
      if (this.guidedOrderingTaskTimer) window.clearTimeout(this.guidedOrderingTaskTimer);
      this.guidedOrderingTaskTimer = window.setTimeout(() => {
        if (this.guidedOrderingTaskPath === normalizedTaskPath) this.guidedOrderingTaskPath = '';
        this.guidedOrderingTaskTimer = null;
      }, 1400);
      this.$nextTick(() => {
        const container = this.$refs.orderingTaskList;
        if (!container?.querySelectorAll) return;
        const targetElement = Array.from(container.querySelectorAll('[data-ordering-task-path]'))
          .find((element) => element.getAttribute('data-ordering-task-path') === normalizedTaskPath);
        if (targetElement?.scrollIntoView) targetElement.scrollIntoView({ block: 'center', behavior: 'smooth' });
      });
    },
    orderingNodeIndentStyle(node) {
      return { marginLeft: `${Math.min(node.depth || 0, 6) * 1.25}rem` };
    },
    orderingNodeFlatIndex(node) {
      if (node.type !== 'task') return '';
      const index = this.orderedTaskRows.findIndex((row) => row.path === node.row.path);
      return index >= 0 ? index + 1 : '';
    },
    taskRowByPath(path) {
      return this.taskRows.find((row) => row.path === path) || null;
    },
    cloneOrderingItems() {
      return JSON.parse(JSON.stringify(this.orderingItems));
    },
    nodeDragRef(node) {
      if (node.type === 'group') return `group:${node.item.id}`;
      return `task:${node.row.path}`;
    },
    startOrderingDrag(event, node) {
      if (this.executionBusy || this.orderingSaving) return;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('application/json', JSON.stringify({ ref: this.nodeDragRef(node) }));
      event.dataTransfer.setData('text/plain', this.nodeDragRef(node));
    },
    dragOverOrderingNode(event, targetNode) {
      if (this.executionBusy || this.orderingSaving) return;
      event.dataTransfer.dropEffect = 'move';
      this.orderingDropHint = {
        ref: this.nodeDragRef(targetNode),
        position: this.resolveOrderingDropPosition(event, targetNode),
      };
    },
    clearOrderingDropHint() {
      this.orderingDropHint = null;
    },
    resolveOrderingDropPosition(event, targetNode) {
      const bounds = event.currentTarget?.getBoundingClientRect?.();
      if (!bounds || !Number.isFinite(bounds.height) || bounds.height <= 0) {
        return targetNode.type === 'group' ? 'inside' : 'group';
      }
      const relativeY = (event.clientY - bounds.top) / bounds.height;
      if (relativeY <= 0.28) return 'before';
      if (relativeY >= 0.72) return 'after';
      return targetNode.type === 'group' ? 'inside' : 'group';
    },
    isOrderingDropHint(node, position) {
      return this.orderingDropHint?.ref === this.nodeDragRef(node)
        && this.orderingDropHint?.position === position;
    },
    dropOrderingNode(event, targetNode) {
      if (this.executionBusy || this.orderingSaving) return;
      const sourceRef = this.readOrderingDragRef(event);
      const targetRef = this.nodeDragRef(targetNode);
      if (!sourceRef || sourceRef === targetRef) return;
      const dropPosition = this.resolveOrderingDropPosition(event, targetNode);
      const nextItems = this.moveOrGroupOrderingNode(this.cloneOrderingItems(), sourceRef, targetRef, dropPosition);
      this.clearOrderingDropHint();
      if (!nextItems) return;
      this.emitOrderingItems(nextItems);
    },
    readOrderingDragRef(event) {
      try {
        const data = JSON.parse(event.dataTransfer.getData('application/json') || '{}');
        if (data.ref) return String(data.ref);
      } catch { /* fallback to plain text */ }
      return String(event.dataTransfer.getData('text/plain') || '').trim();
    },
    moveOrGroupOrderingNode(items, sourceRef, targetRef, dropPosition = 'group') {
      const sourceRecord = this.removeOrderingNodeByRef(items, sourceRef);
      if (!sourceRecord) return null;
      const targetRecord = this.findOrderingNodeByRef(items, targetRef);
      if (!targetRecord) return null;
      if (sourceRecord.node.type === 'group' && this.containsOrderingNodeRef(sourceRecord.node.items || [], targetRef)) return null;

      if (dropPosition === 'before' || dropPosition === 'after') {
        const targetIndex = targetRecord.parent.indexOf(targetRecord.node);
        if (targetIndex < 0) return null;
        const insertIndex = dropPosition === 'before' ? targetIndex : targetIndex + 1;
        targetRecord.parent.splice(insertIndex, 0, sourceRecord.node);
        return this.collapseSingletonGroups(items);
      }

      if (targetRecord.node.type === 'group') {
        targetRecord.node.expanded = true;
        targetRecord.node.items = targetRecord.node.items || [];
        targetRecord.node.items.push(sourceRecord.node);
        return this.collapseSingletonGroups(items);
      }

      const targetIndex = targetRecord.parent.indexOf(targetRecord.node);
      if (targetIndex < 0) return null;
      const children = this.orderGroupedChildrenByCurrentSequence([targetRecord.node, sourceRecord.node]);
      targetRecord.parent.splice(targetIndex, 1, this.makeGroupOrderingNode(children));
      return this.collapseSingletonGroups(items);
    },
    orderGroupedChildrenByCurrentSequence(children) {
      const flatOrder = this.orderedTaskRows.map((row) => row.path);
      const firstPathOf = (item) => {
        if (item?.type !== 'group') return item?.path || '';
        return this.flattenOrderingPaths(item.items || [])[0] || '';
      };
      return [...children].sort((left, right) => {
        const leftIndex = flatOrder.indexOf(firstPathOf(left));
        const rightIndex = flatOrder.indexOf(firstPathOf(right));
        return (leftIndex < 0 ? Number.MAX_SAFE_INTEGER : leftIndex) - (rightIndex < 0 ? Number.MAX_SAFE_INTEGER : rightIndex);
      });
    },
    containsOrderingNodeRef(items, ref) {
      return !!this.findOrderingNodeByRef(items, ref);
    },
    findOrderingNodeByRef(items, ref, parent = null) {
      const currentParent = parent || items;
      for (const item of items || []) {
        const itemRef = item?.type === 'group' ? `group:${item.id}` : `task:${item?.path || ''}`;
        if (itemRef === ref) return { node: item, parent: currentParent };
        if (item?.type === 'group') {
          const childRecord = this.findOrderingNodeByRef(item.items || [], ref, item.items || []);
          if (childRecord) return childRecord;
        }
      }
      return null;
    },
    removeOrderingNodeByRef(items, ref) {
      for (let index = 0; index < (items || []).length; index += 1) {
        const item = items[index];
        const itemRef = item?.type === 'group' ? `group:${item.id}` : `task:${item?.path || ''}`;
        if (itemRef === ref) {
          const [node] = items.splice(index, 1);
          return { node, parent: items };
        }
        if (item?.type === 'group') {
          const childRecord = this.removeOrderingNodeByRef(item.items || [], ref);
          if (childRecord) return childRecord;
        }
      }
      return null;
    },
    emitOrderingItems(items) {
      const normalizedItems = this.collapseSingletonGroups(items);
      this.$emit('save-task-ordering', {
        schema_version: 1,
        user_order: this.flattenOrderingPaths(normalizedItems),
        items: normalizedItems,
      });
    },
    toggleOrderingGroup(groupItem) {
      const nextItems = this.cloneOrderingItems();
      const record = this.findOrderingNodeByRef(nextItems, `group:${groupItem.id}`);
      if (!record) return;
      const groupId = String(groupItem?.id || '').trim();
      if (groupId) this.transientExpandedOrderingGroupIds = this.transientExpandedOrderingGroupIds.filter((id) => id !== groupId);
      record.node.expanded = record.node.expanded === false;
      this.emitOrderingItems(nextItems);
    },
    collapseAllOrderingGroups() {
      if (this.orderingSaving) return;
      const nextItems = this.cloneOrderingItems();
      const hadTransientExpandedGroups = this.transientExpandedOrderingGroupIds.length > 0;
      let persistedStateChanged = false;
      const collapseGroupItems = (items) => {
        for (const item of items || []) {
          if (item?.type !== 'group') continue;
          if (item.expanded !== false) {
            item.expanded = false;
            persistedStateChanged = true;
          }
          collapseGroupItems(item.items || []);
        }
      };
      this.transientExpandedOrderingGroupIds = [];
      collapseGroupItems(nextItems);
      if (persistedStateChanged) {
        this.emitOrderingItems(nextItems);
      } else if (!hadTransientExpandedGroups) {
        ElementPlus.ElMessage.info('分组已经全部折叠');
      }
    },
    async renameOrderingGroup(groupItem) {
      if (this.executionBusy || this.orderingSaving) return;
      try {
        const { value } = await ElementPlus.ElMessageBox.prompt('请输入分组名称', '重命名分组', {
          inputValue: groupItem.name || '分组',
          confirmButtonText: '保存',
          cancelButtonText: '取消',
        });
        const nextName = String(value || '').trim();
        if (!nextName) return;
        const nextItems = this.cloneOrderingItems();
        const record = this.findOrderingNodeByRef(nextItems, `group:${groupItem.id}`);
        if (!record) return;
        record.node.name = nextName;
        this.emitOrderingItems(nextItems);
      } catch { /* cancelled */ }
    },
    ungroupOrderingGroup(groupItem) {
      if (this.executionBusy || this.orderingSaving) return;
      const nextItems = this.cloneOrderingItems();
      const record = this.findOrderingNodeByRef(nextItems, `group:${groupItem.id}`);
      if (!record || record.node.type !== 'group') return;
      const index = record.parent.indexOf(record.node);
      if (index < 0) return;
      record.parent.splice(index, 1, ...(record.node.items || []));
      this.emitOrderingItems(nextItems);
    },
  },
  template: `
<div class="task-workbench flex flex-col gap-4 h-full min-h-0">
  <div v-if="activeTab === 'tasks'" class="task-workbench-toolbar bg-white rounded-xl shadow-md p-4 flex flex-wrap gap-2.5 items-center min-w-0">
    <button @click="$emit('start-run')" :disabled="executionBusy"
            class="px-4 py-2.5 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium shrink-0 disabled:opacity-50 disabled:pointer-events-none">
      <i class="fa fa-play mr-1.5"></i>开始运行
    </button>
    <button class="px-4 py-2.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors text-sm font-medium shrink-0" @click="$emit('stop-dispatch')">
      <i class="fa fa-stop mr-1.5"></i>终止执行
    </button>
    <button class="px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium shrink-0 disabled:opacity-50 disabled:pointer-events-none"
            @click="$emit('save-tasks')" :disabled="executionBusy">
      <i class="fa fa-save mr-1.5"></i>保存任务配置
    </button>
    <button class="px-4 py-2.5 bg-white border border-slate-200 text-primary rounded-lg hover:bg-slate-50 transition-colors text-sm font-medium shrink-0 disabled:opacity-50 disabled:pointer-events-none"
            @click="$emit('refresh-config')" :disabled="executionBusy">
      <i class="fa fa-refresh mr-1.5"></i>刷新
    </button>
    <span v-if="characterName" class="px-3 py-1.5 bg-secondary/10 text-secondary rounded text-sm shrink-0">角色ID：{{ characterName }}</span>
    <span class="px-3 py-1.5 rounded text-sm font-medium shrink-0"
          :style="{ backgroundColor: schedulerStatus.color==='green'?'#dcfce7':schedulerStatus.color==='orange'?'#fef3c7':schedulerStatus.color==='red'?'#fecaca':'#f1f5f9',
                    color: schedulerStatus.color==='green'?'#166534':schedulerStatus.color==='orange'?'#92400e':schedulerStatus.color==='red'?'#991b1b':'#475569' }">
      {{ schedulerStatus.color==='green'?'🟢':schedulerStatus.color==='orange'?'🟡':'🔴' }}
      调度: {{ schedulerStatus.label || '未知' }}
    </span>
    <button v-if="schedulerStatus.state==='error'"
            class="px-3 py-1.5 bg-red-100 text-red-700 rounded text-sm hover:bg-red-200 transition-colors font-medium shrink-0 disabled:opacity-50 disabled:pointer-events-none"
            :disabled="executionBusy"
            @click="$emit('reset-scheduler')">
      <i class="fa fa-refresh mr-1"></i>恢复调度
    </button>
  </div>

  <div v-if="activeTab === 'tasks'" class="task-workbench-main task-list-page grid grid-cols-1 xl:grid-cols-12 gap-4 flex-1 min-h-0">
    <section class="xl:col-span-8 min-w-0 bg-white rounded-xl shadow-md p-4 flex flex-col overflow-hidden min-h-0">
      <div class="flex justify-between items-start gap-3 mb-3 flex-shrink-0">
        <div>
          <h2 class="page-panel-title">任务顺序</h2>
          <p class="text-xs text-slate-500 mt-1">拖到上/下边缘会插入排序；拖到任务中部会创建分组，拖到分组中部会加入分组。分组只影响顺序展开，不记录计算图或偏序关系。</p>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <button type="button"
                  class="text-xs text-slate-600 hover:text-primary transition-colors cursor-pointer select-none disabled:opacity-40 disabled:pointer-events-none"
                  :disabled="orderingSaving"
                  title="折叠任务顺序里的所有分组"
                  @click="collapseAllOrderingGroups">
            折叠全部分组
          </button>
          <label class="inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer select-none">
            <input type="checkbox" v-model="showOnlyEnabledOrderingItems" class="rounded border-slate-300 text-primary focus:ring-primary">
            仅显示执行任务
          </label>
          <span class="text-xs text-slate-500">{{ enabledTaskRows.length }} / {{ orderedTaskRows.length }} 个启用</span>
        </div>
      </div>
      <div ref="orderingTaskList" class="task-panel-tasklist flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden space-y-2 pr-1">
        <div v-for="node in visibleOrderingNodes" :key="node.type + ':' + node.key"
             class="task-order-row px-4 py-3 rounded-xl border transition-colors flex items-center gap-3 min-w-0"
             :style="orderingNodeIndentStyle(node)"
             :data-ordering-task-path="node.type === 'task' ? node.row.path : null"
               :class="[
                 {
                   'opacity-60': executionBusy || orderingSaving,
                   'task-order-row-guided': isOrderingTaskGuided(node),
                   'task-order-drop-before': isOrderingDropHint(node, 'before'),
                   'task-order-drop-after': isOrderingDropHint(node, 'after'),
                   'task-order-drop-inside': isOrderingDropHint(node, 'inside') || isOrderingDropHint(node, 'group'),
                 },
                 node.type === 'group'
                   ? 'bg-slate-100 border-slate-300 hover:border-slate-400 hover:bg-slate-50 text-slate-700'
                   : 'bg-gray-50 border-gray-200 hover:border-primary/50 hover:bg-white'
               ]"
               :draggable="!executionBusy && !orderingSaving"
               :title="node.type === 'group' ? '拖到上/下边缘可排序，拖到中部加入分组' : '拖到上/下边缘可排序，拖到中部创建分组'"
               @dragstart="startOrderingDrag($event, node)"
               @dragover.prevent="dragOverOrderingNode($event, node)"
               @dragleave="clearOrderingDropHint"
               @dragend="clearOrderingDropHint"
               @drop.prevent="dropOrderingNode($event, node)">
          <template v-if="node.type === 'group'">
            <button type="button"
                    class="w-9 h-9 rounded-full bg-slate-200 text-slate-600 flex items-center justify-center text-sm font-bold shrink-0 hover:bg-slate-300 transition-colors"
                    :title="node.item.expanded === false ? '展开分组' : '折叠分组'"
                    @click.stop="toggleOrderingGroup(node.item)">
              <i :class="node.item.expanded === false ? 'fa fa-folder' : 'fa fa-folder-open'"></i>
            </button>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 min-w-0">
                <button class="font-semibold text-sm text-slate-700 truncate hover:text-primary text-left min-w-0" @click.stop="renameOrderingGroup(node.item)">
                  {{ node.item.name || '分组' }}
                </button>
                <span class="inline-flex items-center px-2 py-0.5 rounded bg-slate-200 text-slate-600 text-xs whitespace-nowrap shrink-0">{{ node.childCount }} 个任务</span>
              </div>
              <div class="text-xs text-slate-500 truncate mt-0.5">{{ node.item.expanded === false ? '已折叠；执行时仍按组内顺序展开' : '轮到此分组时，按组内顺序展开执行' }}</div>
            </div>
            <button type="button"
                    class="w-8 h-8 flex items-center justify-center rounded-full bg-white/70 hover:bg-white text-slate-600 transition-colors shrink-0 disabled:opacity-40 disabled:pointer-events-none"
                    :disabled="executionBusy || orderingSaving"
                    @click.stop="renameOrderingGroup(node.item)"
                    title="重命名分组">
              <i class="fa fa-pencil text-xs"></i>
            </button>
            <button type="button"
                    class="w-8 h-8 flex items-center justify-center rounded-full bg-white/70 hover:bg-white text-slate-600 transition-colors shrink-0 disabled:opacity-40 disabled:pointer-events-none"
                    :disabled="executionBusy || orderingSaving"
                    @click.stop="ungroupOrderingGroup(node.item)"
                    title="移除此分组，保留组内顺序">
              <i class="fa fa-chain-broken text-xs"></i>
            </button>
          </template>
          <template v-else>
            <div class="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0" :class="orderingNumberClass(node)">{{ orderingNodeFlatIndex(node) }}</div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 min-w-0">
                <button class="font-semibold text-sm text-slate-800 truncate hover:text-primary text-left min-w-0" @click.stop="openTaskEditor(node.row)">
                  {{ node.row.key }}
                </button>
                <span v-if="node.row.item.custom" class="task-custom-tag">自定义</span>
                <span v-if="node.row.item.beta" class="task-beta-tag">Beta</span>
                <span v-for="chip in formatParamChips(node.row.item.params)" :key="node.row.path + ':' + chip"
                      class="inline-flex items-center px-2 py-0.5 rounded bg-gray-200 text-gray-600 text-xs whitespace-nowrap shrink-0">{{ chip }}</span>
              </div>
              <div class="text-xs text-slate-500 truncate mt-0.5">{{ rowSubtitle(node.row) }}</div>
            </div>
            <span :class="['text-xs px-3 py-1 rounded-full whitespace-nowrap font-medium cursor-pointer', statusTheme(node.row.item).badgeClass]"
                  :title="executionBusy ? '执行中不能修改任务状态' : '点击切换启用状态'"
                  @click.stop="toggleTask(node.row)">
              {{ statusTheme(node.row.item).label }}
            </span>
            <button type="button"
                    class="w-8 h-8 flex items-center justify-center rounded-full bg-primary/10 hover:bg-primary/25 text-primary transition-colors shrink-0 disabled:opacity-40 disabled:pointer-events-none"
                    :disabled="executionBusy"
                    @click.stop="$emit('run-task', node.row.path)"
                    title="运行此任务">
              <i class="fa fa-play text-xs"></i>
            </button>
          </template>
        </div>
      </div>
    </section>

    <section class="xl:col-span-4 min-w-0 flex flex-col gap-4 min-h-0">
      <div class="bg-white rounded-xl shadow-md p-4 flex flex-col gap-3 shrink-0">
        <h2 class="page-panel-title"><i class="fa fa-list-ol mr-2 text-primary"></i>分组顺序说明</h2>
        <p class="text-sm text-slate-600 leading-relaxed">
          当前保存一个可嵌套的全局顺序列表。拖拽后会写入 <code class="text-xs bg-slate-100 px-1 rounded">task_ordering.items</code>，执行时递归展开为 <code class="text-xs bg-slate-100 px-1 rounded">user_order</code>。
        </p>
        <div v-if="orderingDiagnostics.length"
             class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          <div class="font-semibold mb-1">排序诊断</div>
          <div v-for="(diagnostic, index) in orderingDiagnostics" :key="index">{{ diagnostic.code || diagnostic }}</div>
        </div>
      </div>
      <div class="bg-white rounded-xl shadow-md p-4 flex flex-col min-h-[320px] flex-1 overflow-hidden">
        <div class="flex items-center justify-between mb-3 shrink-0">
          <h2 class="page-panel-title"><i class="fa fa-check-square-o mr-2 text-primary"></i>已启用任务</h2>
          <div class="flex items-center gap-2">
            <span class="text-xs text-slate-500">{{ enabledTaskRows.length }} 个</span>
            <button type="button"
                    class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-40 disabled:pointer-events-none"
                    :disabled="executionBusy || !selectedEnabledTaskRows.length"
                    @click="runSelectedEnabledTaskRange"
                    title="从右侧选中的任务开始，一直执行到列表末尾">
              <i class="fa fa-play text-[10px]"></i>
              从选中处执行
            </button>
          </div>
        </div>
        <div class="flex-1 min-h-0 overflow-y-auto pr-1">
          <ol class="space-y-1 text-xs text-slate-600">
            <li v-for="(row, index) in enabledTaskRows"
                :key="row.path"
                class="task-enabled-row flex items-center gap-2 min-w-0 py-1.5 px-2 rounded-lg border cursor-pointer"
                :class="enabledTaskRowClass(row)"
                @click="selectEnabledTask(row)">
              <span class="w-6 text-right text-slate-400 shrink-0">{{ index + 1 }}.</span>
              <span class="task-status-dot" :style="taskStatusDotStyle(row.item)" :title="taskStatusLabel(row.item)"></span>
              <span class="truncate" :class="isEnabledTaskHighlighted(row) ? 'text-sm font-bold' : 'text-xs font-medium'" :title="displayPath(row.path)">{{ displayPath(row.path) }}</span>
              <span v-if="isEnabledTaskCurrent(row)" class="task-current-badge">当前</span>
            </li>
          </ol>
          <div v-if="!enabledTaskRows.length" class="text-sm text-slate-400 py-6 text-center">当前没有启用任务</div>
        </div>
      </div>
    </section>
  </div>
</div>`,
};
