const assert = require('node:assert/strict');
const filesystem = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const virtualMachine = require('node:vm');

const staticDirectory = path.resolve(__dirname, '../../backend/webui/static');
const source = filesystem.readFileSync(path.join(staticDirectory, 'js/components/TaskPanel.js'), 'utf8');
const themeSource = filesystem.readFileSync(path.join(staticDirectory, 'js/core/taskStatusTheme.js'), 'utf8');
const layoutSource = filesystem.readFileSync(path.join(staticDirectory, 'js/core/taskPlanningLayout.js'), 'utf8');
const vueSource = filesystem.readFileSync(path.resolve(staticDirectory, '../vendor/vue.global.prod.js'), 'utf8');

function createPanel(overrides = {}) {
  const events = [];
  const notifications = [];
  const timers = new Map();
  let nextTimerIdentifier = 1;
  const context = virtualMachine.createContext({
    TaskPlanningGraph: { name: 'TaskPlanningGraph' },
    window: {
      WebUIApi: {
        request: async () => ({ ok: true, data: { locations: [], costs: {} } }),
        errorMessage: data => data.message,
      },
      setTimeout(callback) {
        const identifier = nextTimerIdentifier++;
        timers.set(identifier, callback);
        return identifier;
      },
      clearTimeout(identifier) { timers.delete(identifier); },
    },
    ElementPlus: {
      ElMessageBox: {
        async confirm() {
          notifications.push('confirm-discard');
          if (overrides.rejectConfirmation) throw new Error('cancel');
        },
      },
      ElMessage: {
        info: message => notifications.push(message),
        warning: message => notifications.push(message),
      },
    },
  });
  virtualMachine.runInContext(vueSource, context);
  const Vue = virtualMachine.runInContext('Vue', context);
  virtualMachine.runInContext(themeSource, context);
  virtualMachine.runInContext(layoutSource, context);
  virtualMachine.runInContext(source, context);
  const definition = virtualMachine.runInContext('TaskPanel', context);
  const currentTasks = {
    daily: {
      village: {
        mail: { on: true, _due: true, params: { keyword: 'deep-mail' } },
        training: { on: false, _due: false },
      },
      rewards: { on: true, _due: false },
    },
    custom: {
      nested: { deeper: { probe: { on: true, _due: true, planning_status: { error: 'invalid predecessor' } } } },
      recovery: { on: true, _due: true, error: 'failed run' },
    },
    dormant: { disabled: { on: false, _due: true, error: 'disabled error' } },
    rootTask: { on: true, _due: false },
  };
  const effectiveOrder = [
    'custom/nested/deeper/probe', 'daily/rewards', 'daily/village/training',
    'rootTask', 'daily/village/mail', 'custom/recovery', 'dormant/disabled',
  ];
  const panel = {
    currentTasks,
    orderingProjection: {
      effective_order: effectiveOrder,
      overlay: {
        selection_policy: 'list_ready',
        items: [
          { type: 'group', id: 'manual-group', name: 'Manual group', expanded: false, items: [
            { type: 'task', path: 'custom/nested/deeper/probe' },
            { type: 'task', path: 'daily/rewards' },
          ] },
          ...effectiveOrder.slice(2).map(taskPath => ({ type: 'task', path: taskPath })),
        ],
      },
    },
    executionBusy: false,
    orderingSaving: false,
    runtimeStatus: null,
    schedulerStatus: {},
    $refs: {},
    $emit: (...argumentsList) => events.push(argumentsList),
    $nextTick: callback => callback(),
    ...definition.data(),
    ...overrides,
  };
  const reactivePanel = Vue.reactive(panel);
  for (const [methodName, method] of Object.entries(definition.methods)) {
    panel[methodName] = method.bind(reactivePanel);
  }
  for (const [propertyName, getter] of Object.entries(definition.computed)) {
    const computedValue = Vue.computed(() => getter.call(reactivePanel));
    Object.defineProperty(panel, propertyName, { get: () => computedValue.value });
  }
  return { panel: reactivePanel, definition, events, notifications, timers, Vue, api: context.window.WebUIApi };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('ordering and enabled lists expand the same complete graph queue before opening the graph view', () => {
  const currentTasks = { tasks: {
    after: { id: 'after', on: true, _due: false, ensure_in: ['home'], after_tasks: ['before'] },
    peer: { id: 'peer', on: true, _due: true, ensure_in: ['home'] },
    before: { id: 'before', on: true, _due: true, ensure_in: ['far'] },
    broken: { id: 'broken', on: true, ensure_in: ['home'], after_tasks: ['missing'] },
    disabled: { id: 'disabled', on: false, ensure_in: null },
  } };
  const effectiveOrder = Object.keys(currentTasks.tasks).map(identifier => `tasks/${identifier}`);
  const orderingProjection = { effective_order: effectiveOrder, overlay: { items: [
    { type: 'task', path: 'tasks/after' },
    { type: 'group', id: 'split-group', name: 'Keep stored group', expanded: true, items: [
      { type: 'task', path: 'tasks/peer' }, { type: 'task', path: 'tasks/before' },
    ] },
    { type: 'task', path: 'tasks/broken' }, { type: 'task', path: 'tasks/disabled' },
  ] } };
  const { panel, events } = createPanel({ currentTasks, orderingProjection,
    locationCosts: { home: { home: 0 }, far: { far: 0, home: 5 } },
  });
  const snapshot = JSON.stringify([panel.currentTasks, panel.orderingProjection]);
  const expected = ['tasks/before', 'tasks/after', 'tasks/peer', 'tasks/broken'];
  assert.deepEqual(plain(panel.enabledTaskRows.map(row => row.path)), expected);
  assert.deepEqual(plain(panel.flattenOrderingPaths(panel.orderingItems)), [...expected, 'tasks/disabled'],
    'A manual group must not reorder or hide the graph queue when its members become noncontiguous');
  assert.deepEqual(plain(panel.cloneOrderingItems()), plain(orderingProjection.overlay.items),
    'Graph projection must not be saved back as the manual ordering overlay');
  panel.taskViewMode = 'ordering';
  panel.showOnlyEnabledOrderingItems = true;
  assert.deepEqual(plain(panel.visibleOrderingNodes.filter(node => node.type === 'task').map(node => node.row.path)), expected);
  panel.selectTaskForRange(panel.taskRowByPath('tasks/after'), { reveal: false });
  panel.runSelectedEnabledTaskRange();
  assert.deepEqual(plain(events.pop()), ['run-task-range', expected.slice(1)]);
  panel.taskViewMode = 'graph';
  assert.deepEqual(plain(panel.enabledTaskRows.map(row => row.path)), expected);
  panel.currentTasks.tasks.after._due = true;
  panel.currentTasks.tasks.after.planning_status = { blocked_by: ['before'] };
  assert.deepEqual(plain(panel.enabledTaskRows.map(row => row.path)), expected,
    'Due/ready changes must not truncate or reorder the structural queue');
  delete panel.currentTasks.tasks.after.planning_status;
  panel.currentTasks.tasks.after._due = false;
  assert.equal(JSON.stringify([panel.currentTasks, panel.orderingProjection]), snapshot);
  assert.deepEqual(events, []);
});

test('refocusing search cancels an earlier graph-card blur timer', () => {
  const { panel, timers, definition } = createPanel({ taskViewMode: 'graph' });
  panel.focusTaskSearch();
  panel.hideTaskSearchDropdown();
  assert.equal(timers.size, 1);
  panel.focusTaskSearch();
  assert.equal(timers.size, 0, 'The old blur must not hide results after the input regains focus');
  assert.equal(panel.taskSearchFocused, true);
  panel.hideTaskSearchDropdown();
  definition.beforeUnmount.call(panel);
  assert.equal(timers.size, 0);
});

test('navigation data loads once for all views and failed loads are visible and retryable', async () => {
  const { panel, definition, api, events } = createPanel();
  let finishRequest;
  let requestCount = 0;
  api.request = async (method, route) => {
    assert.equal(method, 'GET');
    assert.equal(route, '/task-planning/locations');
    requestCount += 1;
    return new Promise(resolve => { finishRequest = resolve; });
  };
  definition.mounted.call(panel);
  assert.equal(panel.loadingLocations, true);
  await panel.loadLocations();
  assert.equal(requestCount, 1, 'Repeated refreshes must not race');
  panel.selectedEnabledTaskPath = panel.enabledTaskRows[0].path;
  panel.runSelectedEnabledTaskRange();
  assert.deepEqual(events, []);
  finishRequest({ ok: false, data: { message: 'offline' } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(panel.locationError, 'offline');
  assert.equal(panel.loadingLocations, false);
  panel.runSelectedEnabledTaskRange();
  assert.deepEqual(events, []);
  api.request = async () => ({ ok: true, data: { locations: ['home'], costs: { home: { home: 0 } } } });
  await panel.loadLocations();
  assert.equal(panel.locationError, '');
  assert.equal(panel.locationCosts.home.home, 0);
  assert.deepEqual(plain(panel.locations), ['home']);
  await panel.setTaskViewMode('graph');
  await panel.setTaskViewMode('ordering');
  assert.equal(requestCount, 1, 'View switches reuse loaded navigation data, not a second independent graph request');
});

test('default hierarchy exposes collapsed native directories without changing manual order', () => {
  const { panel, events } = createPanel();
  const before = JSON.stringify([panel.currentTasks, panel.orderingProjection]);
  assert.equal(panel.taskViewMode, 'hierarchy');
  assert.deepEqual(plain(panel.visibleTaskHierarchyNodes.map(node => node.key)), ['daily', 'custom', 'dormant', 'rootTask']);
  assert.deepEqual(plain(panel.taskHierarchySummary), { total: 7, enabled: 5, pending: 3, errors: 3 });
  assert.deepEqual(plain(panel.taskHierarchy[0].summary), { total: 3, enabled: 2, pending: 1, errors: 0 });
  panel.expandAllTaskCategories();
  assert.equal(panel.visibleTaskHierarchyNodes.filter(node => node.type === 'task').length, 7);
  panel.collapseAllTaskCategories();
  assert.equal(panel.visibleTaskHierarchyNodes.length, 4);
  assert.equal(JSON.stringify([panel.currentTasks, panel.orderingProjection]), before);
  assert.equal(events.length, 0, 'Directory expansion must never save ordering or task data');
});

test('enabled filter prunes empty categories but keeps aggregate counts and directory state', () => {
  const { panel } = createPanel();
  panel.expandAllTaskCategories();
  const expandedBefore = [...panel.expandedTaskCategoryPaths];
  panel.showOnlyEnabledOrderingItems = true;
  const visibleNodes = panel.visibleTaskHierarchyNodes;
  assert.equal(visibleNodes.some(node => node.key === 'dormant'), false);
  assert.equal(visibleNodes.some(node => node.key === 'daily/village/training'), false);
  assert.equal(visibleNodes.filter(node => node.type === 'task').length, 5);
  assert.deepEqual(plain(visibleNodes.find(node => node.key === 'daily').summary), {
    total: 3, enabled: 2, pending: 1, errors: 0,
  });
  assert.deepEqual([...panel.expandedTaskCategoryPaths], expandedBefore);
  panel.showOnlyEnabledOrderingItems = false;
  assert.equal(panel.visibleTaskHierarchyNodes.filter(node => node.type === 'task').length, 7);
});

test('search reveals arbitrary native ancestors and can locate disabled tasks', () => {
  const { panel, events } = createPanel();
  const scrolledPaths = [];
  panel.$refs.hierarchyTaskList = {
    querySelectorAll: () => panel.visibleTaskHierarchyNodes.filter(node => node.type === 'task').map(node => ({
      getAttribute: () => node.row.path,
      scrollIntoView: () => scrolledPaths.push(node.row.path),
    })),
  };
  panel.taskSearchQuery = 'deeper probe';
  panel.confirmTaskSearchHighlightedMatch();
  assert.deepEqual(plain(panel.expandedTaskCategoryPaths), ['custom', 'custom/nested', 'custom/nested/deeper']);
  assert.equal(panel.selectedEnabledTaskPath, 'custom/nested/deeper/probe');
  assert.deepEqual(scrolledPaths, ['custom/nested/deeper/probe']);
  panel.showOnlyEnabledOrderingItems = true;
  panel.taskSearchQuery = 'village training';
  panel.confirmTaskSearchHighlightedMatch();
  assert.equal(panel.showOnlyEnabledOrderingItems, false);
  assert.ok(panel.visibleTaskHierarchyNodes.some(node => node.key === 'daily/village/training'));
  assert.equal(events.length, 0);
});

test('graph reveal waits for the mounted ref and forwards its asynchronous cancellation', async () => {
  let renderTicks = 0;
  const { panel, events, notifications } = createPanel({
    taskViewMode: 'graph',
    $nextTick(callback) {
      renderTicks += 1;
      return Promise.resolve().then(callback);
    },
  });
  const revealedPaths = [];
  const pendingReveal = panel.scrollTaskIntoView('daily/village/training');
  assert.equal(renderTicks, 1, 'Graph lookup must wait until the view has mounted');
  assert.deepEqual(revealedPaths, []);
  panel.$refs.taskPlanningGraph = {
    dirty: true,
    async revealTask(taskPath) {
      revealedPaths.push(taskPath);
      await Promise.resolve();
      return false;
    },
  };
  assert.equal(await pendingReveal, false);
  assert.deepEqual(revealedPaths, ['daily/village/training']);
  assert.equal(panel.$refs.taskPlanningGraph.dirty, true);
  assert.deepEqual(notifications, [], 'The graph owns confirmation when revealing another card');
  assert.deepEqual(events, [], 'Revealing a disabled task must never save or activate it');
});

test('graph search reuses fuzzy field matches and keyboard selection without changing task data', async () => {
  const { panel, events } = createPanel({
    taskViewMode: 'graph',
    showOnlyEnabledOrderingItems: true,
    $nextTick: callback => Promise.resolve().then(callback),
  });
  const before = JSON.stringify([panel.currentTasks, panel.orderingProjection]);
  const revealedPaths = [];
  panel.$refs.taskPlanningGraph = {
    async revealTask(taskPath) { revealedPaths.push(taskPath); return true; },
  };
  panel.taskSearchQuery = 'keyword dpmail';
  assert.deepEqual(plain(panel.taskSearchMatches.map(match => match.row.path)), ['daily/village/mail']);
  panel.confirmTaskSearchHighlightedMatch();
  await Promise.resolve();
  assert.deepEqual(revealedPaths, ['daily/village/mail']);

  panel.taskSearchQuery = 'daily';
  panel.taskSearchFocused = true;
  assert.equal(panel.taskSearchMatches.length, 3, 'Graph filtering must not narrow the search catalog');
  panel.moveTaskSearchHighlight(-1);
  assert.equal(panel.taskSearchHighlightedIndex, 2);
  panel.moveTaskSearchHighlight(1);
  panel.moveTaskSearchHighlight(1);
  panel.confirmTaskSearchHighlightedMatch();
  await Promise.resolve();
  assert.deepEqual(revealedPaths, ['daily/village/mail', 'daily/village/training']);
  assert.equal(panel.taskSearchQuery, 'daily/village/training');
  assert.equal(panel.taskSearchFocused, false);
  assert.equal(panel.showOnlyEnabledOrderingItems, false);
  assert.equal(panel.selectedEnabledTaskPath, 'daily/village/training');
  assert.deepEqual(plain(panel.selectedEnabledTaskRows.map(row => row.path)), [
    'rootTask', 'daily/village/mail', 'custom/recovery',
  ]);
  assert.equal(JSON.stringify([panel.currentTasks, panel.orderingProjection]), before);
  assert.deepEqual(events, []);
});

test('dozens of search matches remain reachable and runtime status refreshes summaries', () => {
  const currentTasks = { catalog: { deeper: { nested: {} } } };
  for (let taskIndex = 0; taskIndex < 64; taskIndex += 1) {
    currentTasks.catalog.deeper.nested[`task-${taskIndex}`] = { on: true, _due: true };
  }
  const { panel, events } = createPanel({ currentTasks, orderingProjection: null });
  panel.taskSearchQuery = 'catalog';
  assert.equal(panel.taskSearchMatches.length, 64, 'Search must not truncate large native categories');
  panel.selectTaskSearchMatch(panel.taskSearchMatches.at(-1));
  assert.equal(panel.selectedEnabledTaskPath, 'catalog/deeper/nested/task-63');
  assert.equal(panel.visibleTaskHierarchyNodes.filter(node => node.type === 'task').length, 64);
  panel.currentTasks.catalog.deeper.nested['task-63']._due = false;
  panel.currentTasks.catalog.deeper.nested['task-0'].planning_status = { blocked_by: ['task-1'] };
  assert.equal(panel.taskHierarchySummary.pending, 63);
  assert.equal(panel.taskHierarchy[0].summary.pending, 63);
  assert.equal(panel.taskHierarchySummary.errors, 0, 'A pending prerequisite is not a configuration error');
  panel.currentTasks.catalog.deeper.nested['task-1'].human_takeover = true;
  assert.equal(panel.taskHierarchySummary.errors, 1);
  assert.equal(events.length, 0);
});

test('selection and execution ranges always follow effective_order rather than directory order', () => {
  const { panel, events } = createPanel();
  panel.selectTaskForRange(panel.taskRowByPath('daily/rewards'));
  panel.runSelectedEnabledTaskRange();
  assert.deepEqual(plain(events.pop()), [
    'run-task-range', ['daily/rewards', 'rootTask', 'daily/village/mail', 'custom/recovery'],
  ]);
  panel.setTaskViewMode('ordering');
  assert.equal(panel.taskViewMode, 'ordering');
  assert.ok(panel.visibleOrderingNodes.some(node => node.row?.path === 'daily/rewards'));
  panel.setTaskViewMode('hierarchy');
  assert.equal(panel.selectedEnabledTaskPath, 'daily/rewards');
  assert.equal(panel.orderedTaskRows[0].path, 'custom/nested/deeper/probe');
  assert.equal(events.length, 0);
});

test('graph view changes require confirmation for dirty drafts and wait for saves', async () => {
  const { panel, notifications } = createPanel({ taskViewMode: 'graph', rejectConfirmation: true });
  panel.$refs.taskPlanningGraph = { dirty: true, savePending: false };
  await panel.setTaskViewMode('hierarchy');
  assert.equal(panel.taskViewMode, 'graph');
  assert.deepEqual(notifications, ['confirm-discard']);
  const accepted = createPanel({ taskViewMode: 'graph' }).panel;
  accepted.$refs.taskPlanningGraph = { dirty: true, savePending: true };
  await accepted.setTaskViewMode('ordering');
  assert.equal(accepted.taskViewMode, 'graph');
  accepted.$refs.taskPlanningGraph.savePending = false;
  await accepted.setTaskViewMode('ordering');
  assert.equal(accepted.taskViewMode, 'ordering');
});

test('running state allows browsing but blocks editing and ordering persistence', () => {
  const { panel, events } = createPanel({ executionBusy: true });
  const before = JSON.stringify([panel.currentTasks, panel.orderingProjection]);
  panel.expandAllTaskCategories();
  panel.toggleTaskCategory(panel.taskHierarchy[0]);
  panel.taskSearchQuery = 'deep-mail';
  panel.confirmTaskSearchHighlightedMatch();
  panel.toggleTask(panel.taskRowByPath('daily/village/mail'));
  panel.openTaskEditor(panel.taskRowByPath('daily/village/mail'));
  panel.runSelectedEnabledTaskRange();
  panel.setSelectionPolicy('nearest_ready');
  panel.emitOrderingItems(panel.orderingItems);
  panel.toggleOrderingGroup(panel.orderingItems[0]);
  assert.equal(panel.isOrderingGroupExpanded(panel.orderingItems[0]), true);
  panel.collapseAllOrderingGroups();
  assert.equal(panel.isOrderingGroupExpanded(panel.orderingItems[0]), false);
  assert.equal(events.length, 0);
  assert.equal(JSON.stringify([panel.currentTasks, panel.orderingProjection]), before);
});

test('existing drag grouping, order saving and activation semantics are retained', () => {
  const { panel, events } = createPanel();
  const overlayBefore = JSON.stringify(panel.orderingProjection);
  const reordered = panel.moveOrGroupOrderingNode(
    panel.cloneOrderingItems(), 'task:daily/village/mail', 'task:rootTask', 'before',
  );
  panel.emitOrderingItems(reordered);
  const [eventName, payload] = events.pop();
  assert.equal(eventName, 'save-task-ordering');
  assert.equal(payload.selection_policy, 'list_ready');
  assert.ok(payload.user_order.indexOf('daily/village/mail') < payload.user_order.indexOf('rootTask'));
  assert.equal(JSON.stringify(panel.orderingProjection), overlayBefore);
  const grouped = panel.moveOrGroupOrderingNode(
    panel.cloneOrderingItems(), 'task:daily/village/mail', 'task:rootTask', 'group',
  );
  assert.ok(grouped.some(node => node.type === 'group' && node.items.some(child => child.path === 'daily/village/mail')));
  const disabledRow = panel.taskRowByPath('dormant/disabled');
  panel.toggleTask(disabledRow);
  assert.equal(disabledRow.item.on, true);
  assert.equal(disabledRow.item._due, true);
  assert.equal(disabledRow.item.next_exec_time, 0);
  assert.equal(disabledRow.item.error, undefined);
  panel.openTaskEditor(disabledRow);
  assert.equal(events.at(-1)[0], 'edit-task');
  assert.equal(events.at(-1)[3], 'dormant/disabled');
});

test('empty data, task reload and delayed highlighting cannot mutate persistent state', () => {
  const { panel, definition, timers } = createPanel({ currentTasks: {} });
  assert.deepEqual(plain(panel.visibleTaskHierarchyNodes), []);
  assert.deepEqual(plain(panel.taskHierarchySummary), { total: 0, enabled: 0, pending: 0, errors: 0 });
  panel.currentTasks = { replacement: { deep: { fresh: { on: true, _due: true } } } };
  panel.taskSearchQuery = 'fresh';
  panel.confirmTaskSearchHighlightedMatch();
  assert.equal(panel.selectedEnabledTaskPath, 'replacement/deep/fresh');
  assert.ok(timers.size > 0);
  definition.beforeUnmount.call(panel);
  assert.equal(timers.size, 0);
});

test('graph integration uses the declared component, props and save event', () => {
  const { definition } = createPanel();
  assert.equal(definition.components.TaskPlanningGraph.name, 'TaskPlanningGraph');
  assert.ok(definition.emits.includes('save-task-graph'));
  assert.match(definition.template, /<task-planning-graph[\s\S]*?:rows="baseOrderedTaskRows"/);
  assert.match(definition.template, /:location-costs="locationCosts"/);
  assert.match(definition.template, /@refresh-locations="loadLocations"/);
  assert.match(definition.template, /:ordering-projection="orderingProjection"/);
  assert.match(definition.template, /:execution-busy="executionBusy"/);
  assert.match(definition.template, /:saving="orderingSaving"/);
  assert.match(definition.template, /@save-graph="\(payload\) => \$emit\('save-task-graph', payload\)"/);
  assert.match(definition.template, /<section v-if="taskViewMode !== 'graph'"[^>]*task-execution-sidebar/);
});

test('Vue compiles the full task-panel template without additional dependencies', () => {
  const { definition } = createPanel();
  const compilerContext = virtualMachine.createContext({ console });
  virtualMachine.runInContext(vueSource, compilerContext);
  compilerContext.panelTemplate = definition.template;
  virtualMachine.runInContext('Vue.compile(panelTemplate, { decodeEntities: value => value, onError(error) { throw error; } })', compilerContext);
});

test('rendered views preserve task actions and forward graph events without an execution sidebar', async () => {
  const { panel, definition, Vue } = createPanel();
  const events = [];
  const renderErrors = [];
  const graphRevealedPaths = [];
  let graphProps;
  let graphEmit;
  const createHostNode = (type, text = '') => ({
    type, tagName: type.toUpperCase(), text, props: {}, children: [], parent: null,
    addEventListener() {}, removeEventListener() {},
  });
  function detachNode(node) {
    if (!node.parent) return;
    const siblings = node.parent.children;
    siblings.splice(siblings.indexOf(node), 1);
    node.parent = null;
  }
  const renderer = Vue.createRenderer({
    createElement: type => createHostNode(type),
    createText: text => createHostNode('#text', text),
    createComment: text => createHostNode('#comment', text),
    setText: (node, text) => { node.text = text; },
    setElementText: (node, text) => { node.text = text; node.children = []; },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
    patchProp: (node, property, previous, value) => { node.props[property] = value; },
    insert(node, parent, anchor = null) {
      detachNode(node);
      const anchorIndex = anchor ? parent.children.indexOf(anchor) : -1;
      parent.children.splice(anchorIndex < 0 ? parent.children.length : anchorIndex, 0, node);
      node.parent = parent;
    },
    remove: detachNode,
  });
  const render = Vue.compile(definition.template, {
    decodeEntities: value => value,
    hoistStatic: false,
    isCustomElement: tagName => tagName.startsWith('el-'),
    onError(error) { throw error; },
  });
  const component = {
    ...definition,
    render,
    components: {
      TaskPlanningGraph: {
        name: 'TaskPlanningGraph',
        props: ['rows', 'orderingProjection', 'executionBusy', 'saving', 'locationCosts', 'locations', 'loadingLocations', 'locationError'],
        emits: ['edit-task', 'save-graph', 'refresh-locations'],
        setup(props, { emit, expose }) {
          graphProps = props;
          graphEmit = emit;
          expose({
            async revealTask(taskPath) { graphRevealedPaths.push(taskPath); return true; },
          });
          return () => Vue.h('div', { class: 'graph-test-stub' });
        },
      },
    },
  };
  const properties = Vue.reactive({
    activeTab: 'tasks', currentTasks: panel.currentTasks, orderingProjection: panel.orderingProjection,
    logs: [], schedulerStatus: {}, executionBusy: false, orderingSaving: false,
    onRunTask: taskPath => events.push(['run-task', taskPath]),
    onEditTask: (...argumentsList) => events.push(['edit-task', ...argumentsList]),
    onSaveTaskGraph: payload => events.push(['save-task-graph', payload]),
  });
  const root = createHostNode('root');
  let instance;
  const application = renderer.createApp({ render: () => Vue.h(component, { ...properties, ref: value => { instance = value; } }) });
  application.config.errorHandler = error => renderErrors.push(error);
  application.mount(root);
  const flattenNodes = node => [node, ...node.children.flatMap(flattenNodes)];
  const nodesWithClass = className => flattenNodes(root).filter(node => String(node.props.class || '').split(' ').includes(className));
  const assertSharedTaskSearch = () => {
    const searchContainers = nodesWithClass('task-panel-search');
    assert.equal(searchContainers.length, 1, 'All views must reuse the same search control');
    assert.ok(searchContainers[0].parent === nodesWithClass('task-view-bar')[0], 'Search belongs in the shared view bar');
    const searchInputs = flattenNodes(searchContainers[0]).filter(node => node.type === 'input');
    assert.equal(searchInputs.length, 1);
    assert.equal(searchInputs[0].props.disabled, undefined, 'Browsing remains available while executing');
    return searchInputs[0];
  };
  const sharedSearchInput = assertSharedTaskSearch();
  assert.equal(nodesWithClass('task-hierarchy-category').length, 3);
  assert.equal(nodesWithClass('task-order-row').length, 0);
  instance.expandAllTaskCategories();
  await Vue.nextTick();
  const mailNode = flattenNodes(root).find(node => node.props['data-hierarchy-task-path'] === 'daily/village/mail');
  const mailRun = flattenNodes(mailNode).find(node => node.props.class === 'task-hierarchy-run');
  mailRun.props.onClick({ stopPropagation() {} });
  assert.deepEqual(events.pop(), ['run-task', 'daily/village/mail']);
  const mailEdit = flattenNodes(mailNode).find(node => node.type === 'button' && node.props.title === 'daily/village/mail');
  mailEdit.props.onClick({ stopPropagation() {} });
  assert.equal(events.at(-1)[0], 'edit-task');
  assert.equal(events.pop()[3], 'daily/village/mail');
  properties.executionBusy = true;
  await Vue.nextTick();
  assert.equal(mailRun.props.disabled, true);
  assert.equal(mailEdit.props.disabled, true);
  assert.ok(nodesWithClass('task-hierarchy-category').every(node => !node.props.disabled));
  instance.setTaskViewMode('ordering');
  await Vue.nextTick();
  assert.equal(assertSharedTaskSearch(), sharedSearchInput);
  assert.ok(nodesWithClass('task-order-row').length > 0);
  assert.equal(nodesWithClass('task-hierarchy-category').length, 0);
  instance.selectTaskForRange(instance.taskRowByPath('daily/village/training'), { reveal: false });
  instance.setTaskViewMode('graph');
  await Vue.nextTick();
  assert.deepEqual(graphRevealedPaths, ['daily/village/training'], 'View changes reveal the selection after graph mount');
  assert.equal(assertSharedTaskSearch(), sharedSearchInput);
  assert.equal(nodesWithClass('task-execution-sidebar').length, 0);
  assert.equal(nodesWithClass('task-workbench-graph-mode').length, 1);
  assert.equal(nodesWithClass('graph-test-stub').length, 1);
  assert.equal(graphProps.rows[0].path, 'custom/nested/deeper/probe');
  assert.equal(graphProps.executionBusy, true);
  assert.equal(graphProps.orderingProjection, properties.orderingProjection);
  assert.equal(graphProps.locationCosts, instance.locationCosts);
  assert.equal(graphProps.locations, instance.locations);
  properties.executionBusy = false;
  await Vue.nextTick();
  const graphPayload = { changes: [{ task_id: 'probe', after_tasks: ['mail'] }] };
  graphEmit('save-graph', graphPayload);
  assert.deepEqual(events.pop(), ['save-task-graph', graphPayload]);
  graphEmit('edit-task', graphProps.rows[0]);
  assert.equal(events.pop()[3], 'custom/nested/deeper/probe');
  properties.currentTasks = { queue: {
    after: { id: 'after', on: true, ensure_in: ['home'], after_tasks: ['before'] },
    before: { id: 'before', on: true, ensure_in: ['home'] },
  } };
  properties.orderingProjection = { effective_order: ['queue/after', 'queue/before'], overlay: {} };
  instance.selectedEnabledTaskPath = '';
  await instance.setTaskViewMode('ordering');
  await Vue.nextTick();
  assert.deepEqual(nodesWithClass('task-order-row').map(node => node.props['data-ordering-task-path']),
    ['queue/before', 'queue/after'], 'Rendered ordering rows must follow dependencies after a task reload');
  const enabledLabels = nodesWithClass('task-enabled-row').map(node =>
    flattenNodes(node).find(child => child.type === 'span' && child.props.title?.startsWith('queue / '))?.text);
  assert.deepEqual(enabledLabels, ['queue / before', 'queue / after'], 'The sidebar renders the same complete queue');
  application.unmount();
  assert.deepEqual(renderErrors, [], 'Vue must not swallow directive or render failures');
});
