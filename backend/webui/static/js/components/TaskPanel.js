const TaskPanel = {
  name: 'TaskPanel',
  components: { TaskPlanningGraph },
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
    'save-task-ordering', 'save-task-graph',
    'reorder-task',
  ],
  data() {
    return {
      taskViewMode: 'hierarchy',
      expandedTaskCategoryPaths: [],
      showOnlyEnabledOrderingItems: false,
      orderingDropHint: null,
      selectedEnabledTaskPath: '',
      guidedOrderingTaskPath: '',
      guidedOrderingTaskTimer: null,
      transientExpandedOrderingGroupIds: [],
      transientCollapsedOrderingGroupIds: [],
      taskSearchQuery: '',
      taskSearchFocused: false,
      taskSearchHighlightedIndex: 0,
      taskSearchBlurTimer: null,
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
    taskHierarchy() {
      const rootNodes = [];
      const categoriesByPath = new Map();
      // Native directories are a display projection, never a manual ordering input.
      for (const row of this.taskRows) {
        const pathParts = row.path.split('/');
        const taskSummary = this.summarizeHierarchyTasks([row]);
        let children = rootNodes;
        for (let depth = 0; depth < pathParts.length - 1; depth += 1) {
          const categoryPath = pathParts.slice(0, depth + 1).join('/');
          let category = categoriesByPath.get(categoryPath);
          if (!category) {
            category = {
              type: 'category', key: categoryPath, path: categoryPath,
              name: pathParts[depth], depth, children: [],
              summary: { total: 0, enabled: 0, pending: 0, errors: 0 },
            };
            categoriesByPath.set(categoryPath, category);
            children.push(category);
          }
          for (const countName of Object.keys(taskSummary)) category.summary[countName] += taskSummary[countName];
          children = category.children;
        }
        children.push({ type: 'task', key: row.path, row, depth: pathParts.length - 1 });
      }
      return rootNodes;
    },
    taskHierarchySummary() {
      return this.summarizeHierarchyTasks(this.taskRows);
    },
    visibleTaskHierarchyNodes() {
      return this.flattenTaskHierarchyForDisplay(this.taskHierarchy);
    },
    taskHierarchyCategoryPaths() {
      const collectPaths = (nodes) => nodes.flatMap((node) => node.type === 'category'
        ? [node.path, ...collectPaths(node.children)]
        : []);
      return collectPaths(this.taskHierarchy);
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
      return this.orderedTaskRows.findIndex((row) => row.path === this.selectedEnabledTaskPath);
    },
    selectedEnabledTaskRows() {
      return this.selectedEnabledTaskIndex >= 0
        ? this.orderedTaskRows.slice(this.selectedEnabledTaskIndex).filter((row) => row.item?.on)
        : [];
    },
    currentRunningTaskPath() {
      const runtimeActive = this.executionBusy || this.runtimeStatus?.running === true || this.runtimeStatus?.busy === true;
      if (!runtimeActive) return '';
      return String(this.runtimeStatus?.current_task_path || '').trim();
    },
    orderingDiagnostics() {
      return Array.isArray(this.orderingProjection?.diagnostics) ? this.orderingProjection.diagnostics : [];
    },
    planningBlockedRows() {
      return this.enabledTaskRows.filter((row) => row.item.planning_status?.error || row.item.planning_status?.blocked_by?.length);
    },
    taskSearchMatches() {
      const normalizedQuery = this.normalizeTaskSearchText(this.taskSearchQuery);
      if (!normalizedQuery) return [];
      const queryTokens = normalizedQuery.split(/\s+/).filter(Boolean);
      if (!queryTokens.length) return [];
      return this.orderedTaskRows
        .map((row) => ({ row, searchableText: this.buildTaskSearchText(row) }))
        .filter((match) => queryTokens.every((token) => this.doesTaskSearchTextMatch(match.searchableText, token)));
    },
    taskSearchDropdownVisible() {
      return this.taskSearchFocused && !!this.normalizeTaskSearchText(this.taskSearchQuery);
    },
  },
  beforeUnmount() {
    if (this.guidedOrderingTaskTimer) window.clearTimeout(this.guidedOrderingTaskTimer);
    if (this.taskSearchBlurTimer) window.clearTimeout(this.taskSearchBlurTimer);
  },
  methods: {
    async setTaskViewMode(viewMode) {
      if (!['hierarchy', 'ordering', 'graph'].includes(viewMode)) return;
      const graphEditor = this.$refs.taskPlanningGraph;
      if (viewMode !== 'graph' && graphEditor?.savePending) return;
      if (viewMode !== 'graph' && graphEditor?.dirty) {
        try {
          await ElementPlus.ElMessageBox.confirm('计算图有未保存的关系修改，放弃修改并切换视图？', '未保存的修改', {
            confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning',
          });
        } catch { return; }
      }
      this.taskViewMode = viewMode;
      this.taskSearchFocused = false;
      if (this.selectedEnabledTaskPath) this.scrollTaskIntoView(this.selectedEnabledTaskPath);
    },
    summarizeHierarchyTasks(rows) {
      const summary = { total: rows.length, enabled: 0, pending: 0, errors: 0 };
      for (const row of rows) {
        if (row.item?.on) summary.enabled += 1;
        if (row.item?.on && row.item?._due) summary.pending += 1;
        if (this.getTaskIssueText(row.item)) summary.errors += 1;
      }
      return summary;
    },
    getTaskIssueText(taskItem) {
      return [taskItem?.error, taskItem?.human_takeover_error, taskItem?.planning_status?.error]
        .filter(Boolean).join('；') || (taskItem?.human_takeover ? '需要人工接管' : '');
    },
    flattenTaskHierarchyForDisplay(nodes) {
      const visibleNodes = [];
      for (const node of nodes) {
        if (node.type === 'category') {
          if (this.showOnlyEnabledOrderingItems && !node.summary.enabled) continue;
          visibleNodes.push(node);
          if (this.isTaskCategoryExpanded(node)) visibleNodes.push(...this.flattenTaskHierarchyForDisplay(node.children));
        } else if (!this.showOnlyEnabledOrderingItems || node.row.item?.on) {
          visibleNodes.push(node);
        }
      }
      return visibleNodes;
    },
    isTaskCategoryExpanded(category) {
      return this.expandedTaskCategoryPaths.includes(category.path);
    },
    toggleTaskCategory(category) {
      this.expandedTaskCategoryPaths = this.isTaskCategoryExpanded(category)
        ? this.expandedTaskCategoryPaths.filter((path) => path !== category.path)
        : [...this.expandedTaskCategoryPaths, category.path];
    },
    expandAllTaskCategories() {
      this.expandedTaskCategoryPaths = [...this.taskHierarchyCategoryPaths];
    },
    collapseAllTaskCategories() {
      this.expandedTaskCategoryPaths = [];
    },
    revealTaskCategoryPath(taskPath) {
      const pathParts = String(taskPath || '').split('/');
      const expandedPaths = new Set(this.expandedTaskCategoryPaths);
      for (let depth = 1; depth < pathParts.length; depth += 1) {
        expandedPaths.add(pathParts.slice(0, depth).join('/'));
      }
      this.expandedTaskCategoryPaths = Array.from(expandedPaths);
    },
    getHierarchyNodeIndentStyle(node) {
      return { '--task-hierarchy-depth': Math.min(node.depth || 0, 6) };
    },
    scrollTaskIntoView(taskPath) {
      if (this.taskViewMode === 'hierarchy') {
        this.revealTaskCategoryPath(taskPath);
        this.guideTaskIntoView(taskPath, 'hierarchyTaskList', 'data-hierarchy-task-path');
      } else if (this.taskViewMode === 'ordering') {
        this.scrollOrderingTaskIntoView(taskPath);
      } else if (this.taskViewMode === 'graph') {
        return this.$nextTick(() => this.$refs.taskPlanningGraph?.revealTask(taskPath));
      }
    },
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
    isOrderingTaskSelected(node) {
      return node?.type === 'task' && !!node.row?.path && node.row.path === this.selectedEnabledTaskPath;
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
    selectTaskForRange(row, options = {}) {
      if (!row?.path) return;
      this.selectedEnabledTaskPath = row.path;
      if (options.reveal !== false) this.scrollTaskIntoView(row.path);
    },
    selectEnabledTask(row) {
      this.selectTaskForRange(row);
    },
    runSelectedEnabledTaskRange() {
      if (this.executionBusy) return;
      if (!this.selectedEnabledTaskRows.length) {
        ElementPlus.ElMessage.info(this.selectedEnabledTaskPath ? '选中位置之后没有已启用任务' : '请先选择一个任务');
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
    normalizeTaskSearchText(value) {
      return String(value ?? '').trim().toLowerCase();
    },
    stringifyTaskSearchValue(value, seenObjects = new WeakSet()) {
      if (value === null || value === undefined) return '';
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
      if (Array.isArray(value)) return value.map((entry) => this.stringifyTaskSearchValue(entry, seenObjects)).join(' ');
      if (typeof value !== 'object') return String(value);
      if (seenObjects.has(value)) return '';
      seenObjects.add(value);
      return Object.entries(value)
        .map(([fieldName, fieldValue]) => `${fieldName} ${this.stringifyTaskSearchValue(fieldValue, seenObjects)}`)
        .join(' ');
    },
    buildTaskSearchText(row) {
      const searchableParts = [
        row?.key,
        row?.path,
        this.displayPath(row?.path),
        row?.group,
        this.taskStatusLabel(row?.item),
        this.stringifyTaskSearchValue(row?.item),
      ];
      return this.normalizeTaskSearchText(searchableParts.filter(Boolean).join(' '));
    },
    doesTaskSearchTextMatch(searchableText, token) {
      if (!token) return true;
      if (searchableText.includes(token)) return true;
      let nextCharacterIndex = 0;
      for (const character of searchableText) {
        if (character === token[nextCharacterIndex]) nextCharacterIndex += 1;
        if (nextCharacterIndex >= token.length) return true;
      }
      return false;
    },
    focusTaskSearch() {
      if (this.taskSearchBlurTimer) window.clearTimeout(this.taskSearchBlurTimer);
      this.taskSearchBlurTimer = null;
      this.taskSearchFocused = true;
    },
    hideTaskSearchDropdown() {
      if (this.taskSearchBlurTimer) window.clearTimeout(this.taskSearchBlurTimer);
      this.taskSearchBlurTimer = window.setTimeout(() => {
        this.taskSearchFocused = false;
        this.taskSearchBlurTimer = null;
      }, 120);
    },
    clearTaskSearch() {
      this.taskSearchQuery = '';
      this.taskSearchHighlightedIndex = 0;
    },
    moveTaskSearchHighlight(offset) {
      const matchCount = this.taskSearchMatches.length;
      if (!matchCount) return;
      this.taskSearchHighlightedIndex = (this.taskSearchHighlightedIndex + offset + matchCount) % matchCount;
    },
    confirmTaskSearchHighlightedMatch() {
      const match = this.taskSearchMatches[this.taskSearchHighlightedIndex] || this.taskSearchMatches[0];
      if (match) this.selectTaskSearchMatch(match);
    },
    selectTaskSearchMatch(match) {
      const row = match?.row;
      if (!row?.path) return;
      if (!row.item?.on && this.showOnlyEnabledOrderingItems) this.showOnlyEnabledOrderingItems = false;
      this.taskSearchQuery = row.path;
      this.taskSearchFocused = false;
      this.taskSearchHighlightedIndex = 0;
      this.selectTaskForRange(row);
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
      if (this.transientCollapsedOrderingGroupIds.includes(groupId)) return false;
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
      this.transientCollapsedOrderingGroupIds = this.transientCollapsedOrderingGroupIds.filter((groupId) => !groupIds.includes(groupId));
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
      this.guideTaskIntoView(normalizedTaskPath, 'orderingTaskList', 'data-ordering-task-path');
    },
    guideTaskIntoView(taskPath, containerRef, pathAttribute) {
      const normalizedTaskPath = String(taskPath || '').trim();
      if (!normalizedTaskPath) return;
      this.guidedOrderingTaskPath = normalizedTaskPath;
      if (this.guidedOrderingTaskTimer) window.clearTimeout(this.guidedOrderingTaskTimer);
      this.guidedOrderingTaskTimer = window.setTimeout(() => {
        if (this.guidedOrderingTaskPath === normalizedTaskPath) this.guidedOrderingTaskPath = '';
        this.guidedOrderingTaskTimer = null;
      }, 1400);
      this.$nextTick(() => {
        const container = this.$refs[containerRef];
        if (!container?.querySelectorAll) return;
        const targetElement = Array.from(container.querySelectorAll(`[${pathAttribute}]`))
          .find((element) => element.getAttribute(pathAttribute) === normalizedTaskPath);
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
      if (this.executionBusy || this.orderingSaving) return;
      const normalizedItems = this.collapseSingletonGroups(items);
      this.$emit('save-task-ordering', {
        schema_version: 1,
        user_order: this.flattenOrderingPaths(normalizedItems),
        items: normalizedItems,
        selection_policy: this.orderingProjection?.overlay?.selection_policy || 'nearest_ready',
      });
    },
    setSelectionPolicy(policy) {
      if (this.executionBusy || this.orderingSaving) return;
      this.$emit('save-task-ordering', { ...this.orderingProjection?.overlay, selection_policy: policy });
    },
    toggleOrderingGroup(groupItem) {
      const groupId = String(groupItem?.id || '').trim();
      if (this.executionBusy || this.orderingSaving) {
        const wasExpanded = this.isOrderingGroupExpanded(groupItem);
        this.transientExpandedOrderingGroupIds = this.transientExpandedOrderingGroupIds.filter((id) => id !== groupId);
        this.transientCollapsedOrderingGroupIds = this.transientCollapsedOrderingGroupIds.filter((id) => id !== groupId);
        if (wasExpanded) this.transientCollapsedOrderingGroupIds.push(groupId);
        else this.transientExpandedOrderingGroupIds.push(groupId);
        return;
      }
      const nextItems = this.cloneOrderingItems();
      const record = this.findOrderingNodeByRef(nextItems, `group:${groupItem.id}`);
      if (!record) return;
      const wasExpanded = this.isOrderingGroupExpanded(groupItem);
      if (groupId) this.transientExpandedOrderingGroupIds = this.transientExpandedOrderingGroupIds.filter((id) => id !== groupId);
      this.transientCollapsedOrderingGroupIds = this.transientCollapsedOrderingGroupIds.filter((id) => id !== groupId);
      record.node.expanded = !wasExpanded;
      this.emitOrderingItems(nextItems);
    },
    collapseAllOrderingGroups() {
      if (this.executionBusy || this.orderingSaving) {
        const collectGroupIds = (items) => items.flatMap((item) => item.type === 'group'
          ? [item.id, ...collectGroupIds(item.items || [])]
          : []);
        this.transientExpandedOrderingGroupIds = [];
        this.transientCollapsedOrderingGroupIds = collectGroupIds(this.orderingItems);
        return;
      }
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
      this.transientCollapsedOrderingGroupIds = [];
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
        if (!nextName || this.executionBusy || this.orderingSaving) return;
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

  <div v-if="activeTab === 'tasks'" class="task-view-bar">
    <div class="task-view-switcher" role="group" aria-label="任务视图">
      <button type="button" :class="{ 'is-active': taskViewMode === 'hierarchy' }"
              :aria-pressed="taskViewMode === 'hierarchy'" @click="setTaskViewMode('hierarchy')">
        <i class="fa fa-folder-open-o" aria-hidden="true"></i>分层管理
      </button>
      <button type="button" :class="{ 'is-active': taskViewMode === 'ordering' }"
              :aria-pressed="taskViewMode === 'ordering'" @click="setTaskViewMode('ordering')">
        <i class="fa fa-list-ol" aria-hidden="true"></i>顺序编排
      </button>
      <button type="button" :class="{ 'is-active': taskViewMode === 'graph' }"
              :aria-pressed="taskViewMode === 'graph'" @click="setTaskViewMode('graph')">
        <i class="fa fa-share-alt" aria-hidden="true"></i>计算图
      </button>
    </div>
    <div class="task-panel-search relative">
      <div class="relative">
        <i class="fa fa-search absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs pointer-events-none"></i>
        <input v-model="taskSearchQuery"
               type="text"
               class="w-full h-8 pl-8 pr-8 rounded-lg border border-slate-200 bg-white text-xs text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
               placeholder="搜索任务/属性/参数"
               aria-label="搜索并定位任意层级任务"
               title="模糊搜索所有任务字段、属性、参数和任务名称"
               @focus="focusTaskSearch"
               @blur="hideTaskSearchDropdown"
               @input="taskSearchHighlightedIndex = 0"
               @keydown.down.prevent="moveTaskSearchHighlight(1)"
               @keydown.up.prevent="moveTaskSearchHighlight(-1)"
               @keydown.enter.prevent="confirmTaskSearchHighlightedMatch"
               @keydown.esc.prevent="taskSearchFocused = false">
        <button v-if="taskSearchQuery"
                type="button"
                class="absolute right-2 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                title="清空搜索"
                aria-label="清空搜索"
                @mousedown.prevent
                @click="clearTaskSearch">
          <i class="fa fa-times text-[10px]"></i>
        </button>
      </div>
      <div v-if="taskSearchDropdownVisible"
           class="absolute left-0 right-0 top-[calc(100%+0.35rem)] z-30 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
        <div v-if="taskSearchMatches.length" class="max-h-72 overflow-y-auto py-1">
          <button v-for="(match, matchIndex) in taskSearchMatches"
                  :key="match.row.path"
                  type="button"
                  class="w-full px-3 py-2 text-left transition-colors"
                  :class="matchIndex === taskSearchHighlightedIndex ? 'bg-primary/10 text-primary' : 'text-slate-700 hover:bg-slate-50'"
                  @mousedown.prevent
                  @click="selectTaskSearchMatch(match)">
            <div class="text-xs font-semibold truncate">{{ match.row.path }}</div>
            <div class="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-400 min-w-0">
              <span class="truncate">{{ taskStatusLabel(match.row.item) }}</span>
              <span v-if="match.row.item.custom" class="task-custom-tag">自定义</span>
            </div>
          </button>
        </div>
        <div v-else class="px-3 py-2 text-xs text-slate-400">没有匹配任务</div>
      </div>
    </div>
    <span v-if="executionBusy" class="task-view-readonly"><i class="fa fa-lock" aria-hidden="true"></i>执行中：可浏览，不可修改</span>
  </div>

  <div v-if="activeTab === 'tasks'" class="task-workbench-main task-list-page grid grid-cols-1 xl:grid-cols-12 gap-4 flex-1 min-h-0"
       :class="{ 'task-workbench-graph-mode': taskViewMode === 'graph' }">
    <task-planning-graph v-if="taskViewMode === 'graph'"
                         ref="taskPlanningGraph"
                         :rows="orderedTaskRows"
                         :ordering-projection="orderingProjection"
                         :execution-busy="executionBusy"
                         :saving="orderingSaving"
                         @edit-task="openTaskEditor"
                         @save-graph="(payload) => $emit('save-task-graph', payload)" />
    <section v-else class="task-management-panel xl:col-span-8 min-w-0 bg-white rounded-xl shadow-md p-4 flex flex-col overflow-hidden min-h-0">
      <div class="task-panel-view-heading flex justify-between items-start gap-3 mb-3 flex-shrink-0">
        <div class="min-w-0">
          <h2 class="page-panel-title">{{ taskViewMode === 'hierarchy' ? '分层管理' : '任务顺序' }}</h2>
          <p class="task-panel-view-description">{{ taskViewMode === 'hierarchy' ? '按原生目录浏览；分类展开仅保留在本页，不改变手动执行顺序。' : '拖拽调整手动执行顺序与分组，修改后自动保存。' }}</p>
        </div>
        <div class="task-panel-view-controls flex items-center gap-3">
          <template v-if="taskViewMode === 'hierarchy'">
            <button type="button" class="task-panel-text-action" @click="expandAllTaskCategories">展开全部</button>
            <button type="button" class="task-panel-text-action" @click="collapseAllTaskCategories">折叠全部</button>
          </template>
          <button v-else type="button"
                  class="text-xs text-slate-600 hover:text-primary transition-colors cursor-pointer select-none disabled:opacity-40 disabled:pointer-events-none"
                  title="折叠任务顺序里的所有分组"
                  @click="collapseAllOrderingGroups">
            折叠全部分组
          </button>
          <label class="inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer select-none"
                 title="仅过滤显示；目录汇总仍包含全部任务，不改变执行顺序">
            <input type="checkbox" v-model="showOnlyEnabledOrderingItems" class="rounded border-slate-300 text-primary focus:ring-primary">
            仅显示启用任务
          </label>
          <span v-if="taskViewMode === 'ordering'" class="text-xs text-slate-500">{{ enabledTaskRows.length }} / {{ orderedTaskRows.length }} 个启用</span>
        </div>
      </div>
      <template v-if="taskViewMode === 'hierarchy'">
        <div class="task-hierarchy-summary" aria-label="全部任务概览">
          <div><span>任务总数</span><strong>{{ taskHierarchySummary.total }}</strong></div>
          <div><span>已启用</span><strong>{{ taskHierarchySummary.enabled }}</strong></div>
          <div title="启用且当前到期的任务，包含等待前置的任务"><span>待执行</span><strong>{{ taskHierarchySummary.pending }}</strong></div>
          <div :class="{ 'has-errors': taskHierarchySummary.errors > 0 }" title="包含任务错误、人工接管与前置约束配置错误；等待前置不算异常">
            <span>异常任务</span><strong>{{ taskHierarchySummary.errors }}</strong>
          </div>
        </div>
        <div ref="hierarchyTaskList" class="task-hierarchy-list task-panel-tasklist flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden">
          <div v-for="node in visibleTaskHierarchyNodes" :key="node.type + ':' + node.key"
               class="task-hierarchy-node" :style="getHierarchyNodeIndentStyle(node)">
            <button v-if="node.type === 'category'" type="button" class="task-hierarchy-category"
                    :aria-expanded="isTaskCategoryExpanded(node)" :title="displayPath(node.path)"
                    @click="toggleTaskCategory(node)">
              <span class="task-hierarchy-category-name">
                <i :class="isTaskCategoryExpanded(node) ? 'fa fa-chevron-down' : 'fa fa-chevron-right'" class="task-hierarchy-chevron" aria-hidden="true"></i>
                <i :class="isTaskCategoryExpanded(node) ? 'fa fa-folder-open' : 'fa fa-folder'" class="task-hierarchy-folder" aria-hidden="true"></i>
                <span>{{ node.name }}</span>
              </span>
              <span class="task-hierarchy-counts">
                <span>任务 <b>{{ node.summary.total }}</b></span>
                <span>启用 <b>{{ node.summary.enabled }}</b></span>
                <span>待执行 <b>{{ node.summary.pending }}</b></span>
                <span :class="{ 'has-errors': node.summary.errors > 0 }">异常 <b>{{ node.summary.errors }}</b></span>
              </span>
            </button>
            <div v-else class="task-hierarchy-task"
                 :class="{ 'is-selected': isEnabledTaskSelected(node.row), 'is-current': isEnabledTaskCurrent(node.row), 'task-order-row-guided': isOrderingTaskGuided(node) }"
                 :data-hierarchy-task-path="node.row.path"
                 @click="selectTaskForRange(node.row, { reveal: false })">
              <button type="button" class="task-hierarchy-select" :aria-pressed="isEnabledTaskSelected(node.row)"
                      :aria-label="'设为手动执行起点：' + node.row.path" title="选择手动执行起点；执行范围按右侧列表，不按目录"
                      @click.stop="selectTaskForRange(node.row, { reveal: false })">
                <i :class="isEnabledTaskSelected(node.row) ? 'fa fa-dot-circle-o' : 'fa fa-circle-o'" aria-hidden="true"></i>
              </button>
              <div class="task-hierarchy-task-details">
                <div class="task-hierarchy-task-title">
                  <span class="task-status-dot" :style="taskStatusDotStyle(node.row.item)" :title="taskStatusLabel(node.row.item)"></span>
                  <button type="button" :disabled="executionBusy" :title="node.row.path" @click.stop="openTaskEditor(node.row)">{{ node.row.key }}</button>
                  <span v-if="node.row.item.custom" class="task-custom-tag">自定义</span>
                  <span v-if="isEnabledTaskCurrent(node.row)" class="task-current-badge">当前</span>
                  <span v-if="getTaskIssueText(node.row.item)" class="task-hierarchy-issue" :title="getTaskIssueText(node.row.item)">异常</span>
                  <span v-else-if="node.row.item.planning_status?.blocked_by?.length" class="task-hierarchy-waiting"
                        :title="node.row.item.planning_status.blocked_by.join('、')">等待前置</span>
                </div>
                <div class="task-hierarchy-task-path" :title="displayPath(node.row.path)">{{ rowSubtitle(node.row) }}</div>
                <div v-if="formatParamChips(node.row.item.params).length" class="task-hierarchy-param-chips">
                  <span v-for="(chip, chipIndex) in formatParamChips(node.row.item.params)" :key="chipIndex">{{ chip }}</span>
                </div>
              </div>
              <div class="task-hierarchy-task-actions">
                <button type="button" :disabled="executionBusy" :class="['task-hierarchy-status', statusTheme(node.row.item).badgeClass]"
                        :title="executionBusy ? '执行中不能修改任务状态' : '点击切换启用状态'" @click.stop="toggleTask(node.row)">
                  {{ taskStatusLabel(node.row.item) }}
                </button>
                <button type="button" class="task-hierarchy-run" :disabled="executionBusy"
                        :aria-label="'运行此任务：' + node.row.path" title="运行此任务" @click.stop="$emit('run-task', node.row.path)">
                  <i class="fa fa-play" aria-hidden="true"></i>
                </button>
              </div>
            </div>
          </div>
          <div v-if="!visibleTaskHierarchyNodes.length" class="task-hierarchy-empty">
            {{ taskRows.length ? '当前没有启用任务，可关闭“仅显示启用任务”查看全部。' : '当前没有任务。' }}
          </div>
        </div>
      </template>
      <div v-else ref="orderingTaskList" class="task-panel-tasklist flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden space-y-2 pr-1">
        <div v-for="node in visibleOrderingNodes" :key="node.type + ':' + node.key"
             class="task-order-row px-4 py-3 rounded-xl border transition-colors flex items-center gap-3 min-w-0"
             :style="orderingNodeIndentStyle(node)"
             :data-ordering-task-path="node.type === 'task' ? node.row.path : null"
             @click="node.type === 'task' ? selectTaskForRange(node.row, { reveal: false }) : null"
               :class="[
                 {
                   'opacity-60': executionBusy || orderingSaving,
                   'task-order-row-selected bg-primary/10 border-primary/40': isOrderingTaskSelected(node),
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
                    :title="isOrderingGroupExpanded(node.item) ? '折叠分组' : '展开分组'"
                    @click.stop="toggleOrderingGroup(node.item)">
              <i :class="isOrderingGroupExpanded(node.item) ? 'fa fa-folder-open' : 'fa fa-folder'"></i>
            </button>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 min-w-0">
                <button class="font-semibold text-sm text-slate-700 truncate hover:text-primary text-left min-w-0" @click.stop="renameOrderingGroup(node.item)">
                  {{ node.item.name || '分组' }}
                </button>
                <span class="inline-flex items-center px-2 py-0.5 rounded bg-slate-200 text-slate-600 text-xs whitespace-nowrap shrink-0">{{ node.childCount }} 个任务</span>
              </div>
              <div class="text-xs text-slate-500 truncate mt-0.5">{{ isOrderingGroupExpanded(node.item) ? '手动执行时，按组内顺序展开' : '已折叠；手动执行时仍按组内顺序展开' }}</div>
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

    <section v-if="taskViewMode !== 'graph'" class="task-execution-sidebar xl:col-span-4 min-w-0 flex flex-col gap-4 min-h-0">
      <div class="bg-white rounded-xl shadow-md p-4 flex flex-col gap-3 shrink-0">
        <h2 class="page-panel-title"><i class="fa fa-list-ol mr-2 text-primary"></i>执行顺序与调度</h2>
        <p v-if="taskViewMode === 'hierarchy'" class="text-sm text-slate-600 leading-relaxed">
          分类只用于浏览，不改变任务路径和执行顺序。范围执行沿用下方列表，单跑只执行所选任务；调整顺序请切换“顺序编排”。
        </p>
        <p v-else class="text-sm text-slate-600 leading-relaxed">
          按住任务或分组拖到想要的位置，松开后自动保存。下方列表是手动执行顺序，不是自动调度的整轮预测。
        </p>
        <p class="text-xs text-slate-500 leading-relaxed">
          自动调度先满足前置约束，再按所选策略选择任务。就近策略：同距先前序就绪，再按列表；未知距离之间也按此规则决胜，排在已知可达距离之后。
        </p>
        <label class="text-xs text-slate-600">自动调度策略</label>
        <el-select :model-value="orderingProjection?.overlay?.selection_policy || 'nearest_ready'"
                   :disabled="executionBusy || orderingSaving" @change="setSelectionPolicy">
          <el-option label="依赖就绪后，就近优先" value="nearest_ready"></el-option>
          <el-option label="依赖就绪后，列表优先" value="list_ready"></el-option>
        </el-select>
        <details v-if="planningBlockedRows.length" class="text-xs text-amber-700 max-h-36 overflow-auto">
          <summary>等待前置 / 配置异常（{{ planningBlockedRows.length }}）</summary>
          <p v-for="row in planningBlockedRows" :key="row.path" class="mt-1 break-words">
            {{ row.key }}：{{ row.item.planning_status.error || row.item.planning_status.blocked_by.join('、') }}
          </p>
        </details>
        <details v-if="schedulerStatus.last_selection?.ranked_paths?.length" class="text-xs text-slate-500 max-h-36 overflow-auto">
          <summary>最近一次实际决策（非整轮预测）</summary>
          <p>位置：{{ schedulerStatus.last_selection.position?.filter(Boolean).join(' / ') || '未知（未定位）' }}</p>
          <p>选择：{{ schedulerStatus.last_selection.ranked_paths[0] }}</p>
          <p v-for="(cost, taskId) in schedulerStatus.last_selection.costs" :key="taskId">
            {{ taskId }}：{{ schedulerStatus.last_selection.destinations[taskId] }}，{{ cost == null ? '不可达 / 未知' : cost + ' 步' }}
          </p>
        </details>
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
                    title="从选中任务开始，按此手动执行列表运行到末尾，不按目录顺序">
              <i class="fa fa-play text-[10px]"></i>
              从选中处执行
            </button>
          </div>
        </div>
        <p class="text-xs text-slate-500 mb-2 shrink-0">手动执行顺序，不随目录展开或视图切换改变</p>
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
