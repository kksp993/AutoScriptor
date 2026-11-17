// Offline coverage for graph semantics, real Vue templates, and the shared save queue.
const assert = require('node:assert/strict');
const filesystem = require('node:fs');
const path = require('node:path');
const virtualMachine = require('node:vm');

const root = path.resolve(__dirname, '../..');
const source = (relativePath) => filesystem.readFileSync(path.join(root, relativePath), 'utf8');
const plain = (value) => JSON.parse(JSON.stringify(value));
const messages = [];
const message = (value) => messages.push(value);
Object.assign(message, { success: message, error: message, warning: message, info: message });
const context = virtualMachine.createContext({
  window: {}, console, setTimeout, clearTimeout,
  ElementPlus: { ElMessage: message, ElMessageBox: { confirm: async () => {} } },
});
virtualMachine.runInContext(source('backend/webui/vendor/vue.global.prod.js'), context);
virtualMachine.runInContext(source('backend/webui/static/js/core/taskStatusTheme.js'), context);
virtualMachine.runInContext(source('backend/webui/static/js/core/taskPlanningLayout.js'), context);
virtualMachine.runInContext(source('backend/webui/static/js/components/TaskPlanningGraph.js'), context);
const layout = context.window.TaskPlanningLayout;
const component = virtualMachine.runInContext('TaskPlanningGraph', context);

const continuation = { on: true, _due: false, continuation_pending: true };
assert.equal(context.window.TaskStatusTheme.getTaskStatus(continuation), 'pending');
assert.equal(context.window.TaskStatusTheme.getTaskTheme(continuation).label, '等待续跑');
assert.equal(context.window.TaskStatusTheme.getTaskTheme({ ...continuation, _due: true }).label, '待执行');
assert.equal(context.window.TaskStatusTheme.getTaskStatus({ ...continuation, on: false }), 'disabled');
assert.equal(context.window.TaskStatusTheme.getTaskStatus({ ...continuation, error: 'failure' }), 'error');
assert.equal(context.window.TaskStatusTheme.getTaskStatus({ on: true, _due: false }), 'scheduled');

function row(identifier, after = [], locations = ['home'], enabled = true) {
  return { key: identifier, path: `daily/area/${identifier}`, item: {
    id: identifier, on: enabled, after_tasks: after, ensure_in: locations,
    preferred_locations: locations || [],
  } };
}
const costs = { home: { home: 0, garden: 1, far: 5 }, garden: { home: null, garden: 0 }, far: { far: 0 } };
const rows = [row('before'), row('peer', [], ['garden']), row('after', ['before']),
  row('join', ['before', 'after']), row('far', [], ['far']), row('scene', [], ['任意位置']), row('disabled', [], ['任意位置'], false)];
const original = plain(rows);
const anywhereGraph = layout.build([row('anywhere-first', [], ['任意位置']), row('anywhere-second', [], ['任意位置']), row('map-task')], { costs });
assert.equal(anywhereGraph.groups.length, 2, 'Anywhere cards group only with anywhere, never claim a route to the map');
assert.equal(anywhereGraph.errors.length, 0);
assert.equal(layout.build([row('null-entry', [], null)], { costs }).errors.length, 1, 'Legacy null entry declarations must not silently bypass validation');
const graph = layout.build(rows, { costs });
const backboneRows = [row('travel', [], ['far']), row('destination', ['travel']), row('independent')];
const backboneGraph = layout.build(backboneRows, { costs });
assert.deepEqual(plain(backboneGraph.groups.find(group => group.id === 'destination').rows.map(entry => entry.key)),
  ['destination', 'independent'], 'An independent task must stack behind a same-location backbone task even at depth two');
assert.equal(backboneGraph.groups.length, 2, 'Independent cards must not add another visible branch');
const branchRows = Array.from({ length: 11 }, (_, index) => row(`entry-${index}`));
branchRows.push(...Array.from({ length: 11 }, (_, index) => row(`child-${index}`, [`entry-${index}`])));
const branchGraph = layout.build(branchRows, { costs: {} });
for (const edge of branchGraph.edges) {
  assert.ok(edge.source.left + layout.geometry.cardWidth < edge.target.left, 'Dependency columns flow left to right');
  assert.equal(edge.source.top, edge.target.top, 'A simple chain is aligned like a mind map');
}
for (const level of [1, 2]) {
  const groupsAtLevel = branchGraph.groups.filter(group => group.level === level).sort((left, right) => left.top - right.top);
  assert.equal(new Set(groupsAtLevel.map(group => group.left)).size, 1, 'One column per topology level');
  for (let index = 1; index < groupsAtLevel.length; index++) {
    assert.ok(groupsAtLevel[index - 1].top + layout.geometry.cardHeight < groupsAtLevel[index].top,
      'Visible branch cards do not overlap');
  }
}
assert.ok(graph.edges.every(edge => edge.kind === 'dependency'), 'The graph must not connect a virtual login to every root');
assert.equal(graph.root, undefined, 'Omit the artificial login card');
assert.equal(layout.build([row('village'), row('adjacent', [], ['garden'])], { costs }).groups.length,
  2, 'Only distance zero may stack; adjacent locations must stay separate');
const villageTasks = Array.from({ length: 20 }, (_, index) => row(`village-${index}`));
assert.equal(layout.build(villageTasks, { costs }).groups.length, 1,
  'Twenty tasks with the same village origin must form one deck');
assert.equal(graph.groups.length, 4);
assert.deepEqual(plain(graph.groups[0].rows.map((entry) => entry.key)), ['before', 'peer', 'far']);
assert.deepEqual(rows, original, 'Layout must never modify task configuration');
assert.equal(graph.edges.length, 2, 'Redundant ancestor links are omitted from the display only');
assert.deepEqual(rows[3].item.after_tasks, ['before', 'after'], 'The complete saved constraints must survive display reduction');
assert.equal(graph.groups.find((group) => group.id === 'join').level, 3);
for (const edge of graph.edges.filter((entry) => entry.kind === 'dependency')) {
  assert.ok(edge.source.left < edge.target.left, 'Every strict edge must point to a deeper column');
}
assert.equal(Object.hasOwn(component.data(), 'stackSameLocation'), false, 'Stacking is automatic, not a user-facing option');
assert.equal(layout.build(rows, { costs: {} }).groups.length, 6, 'Unknown distances do not group tasks');
assert.equal(layout.build(villageTasks, { costs: {} }).groups.length, 20);
assert.equal(layout.build(rows, { costs, showDisabled: true }).taskCount, 7);
assert.equal(layout.build([row('garden', [], ['garden']), row('home')], { costs }).groups.length, 2, 'Distances must remain directed');
assert.equal(layout.build([row('first'), row('second', ['first'])], { costs }).groups.length, 2, 'Nearby predecessors never become peers');
const ancestorGraph = layout.build([row('off', [], ['home'], false), row('child', ['off'])], { costs });
assert.equal(ancestorGraph.taskCount, 2, 'Disabled prerequisites remain as context without re-enabling them');
const invalid = layout.build([row('cycle1', ['cycle2']), row('cycle2', ['cycle1']), row('missing', ['absent']), row('healthy')], { costs });
assert.equal(invalid.errors.length, 3);
assert.equal(invalid.groups.length, 1, 'Malformed chains cannot prevent unrelated tasks from rendering');
assert.match(layout.dependencyError(rows, 'before', ['join']), /循环/);
assert.match(layout.dependencyError(rows, 'before', ['missing']), /不存在/);
assert.equal(layout.dependencyError(rows, 'after', []), '');
assert.equal(layout.build([], { costs }).taskCount, 0);
const multipleLocations = layout.build([row('first', [], ['far', 'home']), row('second')], { costs });
assert.equal(multipleLocations.groups.length, 1, 'Multiple entrypoints can share a common zero-cost origin');
assert.deepEqual(plain(multipleLocations.groups[0].stackOrigins), ['home']);
const bridgedLocations = layout.build([
  row('flexible', [], ['home', 'garden']), row('village-only'), row('garden-only', [], ['garden']),
], { costs });
assert.equal(bridgedLocations.groups.length, 2, 'A flexible entrypoint must not bridge distinct locations into one deck');
const differentPredecessors = layout.build([
  row('first'), row('second'), row('first-child', ['first']), row('second-child', ['second']),
], { costs });
assert.equal(differentPredecessors.groups.length, 4, 'Every dependency endpoint stays visible even at the same location');
const multipleParents = layout.build([
  row('parent-first'), row('parent-second'), row('child', ['parent-first', 'parent-second']),
], { costs });
assert.equal(multipleParents.edges.length, 2, 'Independent AND predecessors must both remain visible');
assert.equal(multipleParents.groups.length, 3, 'A shared successor has one card, not a duplicate per branch');
const nearestRows = [row('travel', [], ['far']), row('destination', ['travel']),
  row('far-independent', [], ['far']), row('one-step', [], ['garden']), row('same-place')];
const nearestGraph = layout.build(nearestRows, { costs });
assert.deepEqual(plain(nearestGraph.groups.find(group => group.id === 'destination').rows.map(entry => entry.key)),
  ['destination', 'same-place', 'one-step'], 'Attached tasks are ordered by directed distance, then existing list order');
assert.equal(nearestGraph.groups.find(group => group.id === 'destination').distances['one-step'], 1);
assert.deepEqual(plain(nearestGraph.groups.find(group => group.id === 'travel').rows.map(entry => entry.key)),
  ['travel', 'far-independent'], 'Choose the globally nearest trunk instead of the first reachable one');
const directedGraph = layout.build([row('start', [], ['garden']), row('end', ['start'], ['garden']), row('unreachable')], { costs });
assert.equal(directedGraph.groups.length, 3, 'Reverse-only reachability cannot attach independent cards');
const skipLevelGraph = layout.build([
  row('root'), row('middle', ['root']), row('other-root'), row('leaf', ['middle', 'other-root']),
], { costs });
const longEdge = skipLevelGraph.edges.find(edge => edge.predecessor === 'other-root');
assert.equal(longEdge.waypoints.length, 1, 'A cross-level dependency uses the gap in its intermediate column');
for (const waypoint of longEdge.waypoints) {
  for (const group of skipLevelGraph.groups.filter(candidate => candidate.left === waypoint.left)) {
    assert.ok(waypoint.top < group.top || waypoint.top > group.top + layout.geometry.cardHeight,
      'Cross-level connections must not cut through a task card');
  }
}
const lateTrunk = layout.build([row('independent'), row('travel', [], ['far']), row('destination', ['travel'])], { costs });
assert.deepEqual(plain(lateTrunk.groups.find(group => group.id === 'destination').rows.map(entry => entry.key)),
  ['destination', 'independent'], 'Build the whole backbone before assigning any independent task');
assert.deepEqual(plain(lateTrunk.queueRows.map(entry => entry.key)), ['travel', 'destination', 'independent'],
  'The complete graph queue must expand every deck after its predecessors, not preserve raw input order');
const queueRows = [row('join', ['left', 'right']), row('leaf', ['join']), row('right'), row('left')];
queueRows[0].item.planning_status = { blocked_by: ['left', 'right'] };
queueRows[1].item._due = false;
const queueGraph = layout.build(queueRows, { costs });
assert.deepEqual(plain(queueGraph.queueRows.map(entry => entry.key)), ['right', 'left', 'join', 'leaf'],
  'AND dependencies, blocked successors and future tasks all belong to the full queue');
assert.deepEqual(plain(ancestorGraph.queueRows.map(entry => entry.key)), ['off', 'child']);
assert.deepEqual(plain(invalid.queueRows.map(entry => entry.key)), ['healthy', 'cycle1', 'cycle2', 'missing'],
  'Invalid tasks remain visible at the end instead of disappearing or blocking healthy branches');
assert.equal(new Set(queueGraph.queueRows.map(entry => entry.key)).size, queueRows.length);
const preferenceOverrides = [row('original'), row('overridden')];
preferenceOverrides[0].item.preferred_locations = [];
preferenceOverrides[1].item.preferred_locations = ['far'];
assert.equal(layout.build(preferenceOverrides, { costs }).groups.length, 1,
  'Optional scheduling preferences must not erase or replace the required entrypoint');
const missingEntry = row('missing-entry');
delete missingEntry.item.ensure_in;
const missingEntryGraph = layout.build([missingEntry, row('empty-entry', [], []), row('healthy')], { costs });
assert.equal(missingEntryGraph.errors.length, 2);
assert.match(missingEntryGraph.errors[0].message, /起点/);
assert.equal(missingEntryGraph.groups.length, 1, 'Missing mandatory declarations are visible errors, not unknown-location cards');

function instantiate(definition, properties) {
  const instance = { ...definition.data(), $refs: {}, $nextTick: callback => callback(), ...properties };
  for (const [name, method] of Object.entries(definition.methods)) instance[name] = method.bind(instance);
  for (const [name, getter] of Object.entries(definition.computed)) Object.defineProperty(instance, name, { get: () => getter.call(instance) });
  return instance;
}

async function testGraphEditing() {
  const emitted = [];
  const panel = instantiate(component, { rows, executionBusy: false, saving: false,
    $emit: (event, payload) => emitted.push({ event, payload }),
  });
  assert.equal(panel.entryLabel(rows[0]), 'home');
  assert.equal(panel.entryLabel(rows[5]), '任意位置');
  assert.equal(panel.boardStyle['--planning-card-width'], '168px');
  for (const [task, statusName] of [
    [row('done'), 'scheduled'], [{ item: { on: true, _due: true } }, 'pending'],
    [{ item: { on: true, error: 'failed' } }, 'error'], [row('off', [], ['home'], false), 'disabled'],
    [{ item: { on: true, planning_status: { blocked_by: ['before'] } } }, 'pending'],
  ]) {
    assert.equal(panel.statusTheme(task).nodeStroke, context.window.TaskStatusTheme.STATUS_THEME[statusName].nodeStroke,
      'Card status dots must match the existing task colors');
  }
  assert.doesNotMatch(component.template, /ensure_in|源码|叠牌只看|同起点叠牌|无注册前序|登录界面|planning-card-footer|planning-card-path/);
  assert.match(component.template, /class="planning-status-dot"[\s\S]*?:aria-label="status\(row\)"/);
  assert.match(component.template, /fa fa-map-marker/);
  const branchPanel = instantiate(component, { rows: branchRows, executionBusy: false, saving: false });
  for (const edge of branchPanel.graph.edges) {
    const route = branchPanel.edgePath(edge);
    assert.doesNotMatch(route, /NaN|undefined/);
    assert.match(route, / C /, 'Mind-map connections use smooth branches');
    assert.ok(edge.source.left + layout.geometry.cardWidth < edge.target.left);
  }
  const deck = { id: 'village', rows: villageTasks };
  panel.hoveredGroup = deck.id;
  assert.equal(panel.groupExpanded(deck), true, 'Hover expands the complete twenty-card deck');
  panel.hoveredGroup = '';
  panel.toggleGroup(deck);
  assert.equal(panel.groupExpanded(deck), true, 'Pinning keeps a large deck accessible');
  await panel.selectRow(rows[2]);
  panel.draftPredecessors = [];
  panel.changePredecessors();
  panel.applyDraft();
  assert.equal(emitted.length, 1);
  assert.deepEqual(plain(emitted[0].payload.changes.after_tasks), []);
  assert.deepEqual(rows, original, 'The editor must retain uncommitted changes outside props');
  emitted[0].payload.onComplete(false, 'rejected');
  assert.equal(panel.dirty, true);
  assert.equal(panel.saveError, 'rejected');
  panel.readDraft();
  panel.executionBusy = true;
  panel.submitChange(rows[0], { on: false });
  assert.equal(emitted.length, 1, 'Execution occupancy blocks writes');
  panel.executionBusy = false;
  panel.draftPredecessors = ['join'];
  panel.changePredecessors();
  panel.applyDraft();
  assert.equal(emitted.length, 1, 'Cycle checks run before emitting a save');
  panel.readDraft();
  panel.restoreDefaults('after_tasks');
  panel.applyDraft();
  assert.deepEqual(plain(emitted[1].payload.inheritFields), ['after_tasks']);
  emitted[1].payload.onComplete(true);
  assert.equal(panel.dirty, false);
  panel.addTaskId = 'disabled';
  panel.addTask();
  assert.deepEqual(plain(emitted[2].payload.changes), { on: true });
  emitted[2].payload.onComplete(true);
  await panel.selectRow(rows[0]);
  await panel.removeSelectedTask();
  assert.deepEqual(plain(emitted[3].payload.changes), { on: false }, 'Removing a card only disables, never deletes source');
  emitted[3].payload.onComplete(true);
  panel.loadLocations();
  assert.equal(emitted[4].event, 'refresh-locations', 'The parent owns navigation data for all views');
}

async function testSearchReveal() {
  const revealRows = [...backboneRows, row('disabled-result', [], ['home'], false), row('invalid-result', ['absent'])];
  const originalRows = plain(revealRows);
  const interactions = [];
  const emitted = [];
  const cards = revealRows.map(entry => ({
    dataset: { graphTaskId: entry.item.id },
    scrollIntoView: options => interactions.push(['scroll', entry.item.id, plain(options)]),
    focus: options => interactions.push(['focus', entry.item.id, plain(options)]),
  }));
  const panel = instantiate(component, { rows: revealRows, executionBusy: true, saving: false,
    locationCosts: costs, $emit: (...eventArguments) => emitted.push(eventArguments),
    $refs: { viewport: { querySelectorAll: () => cards } },
  });
  assert.equal(await panel.revealTask(backboneRows[2].path), true);
  assert.equal(panel.selectedId, 'independent');
  assert.equal(panel.pinnedGroup, 'destination', 'Search opens the containing backbone deck');
  assert.equal(interactions[0][1], 'independent', 'Search scrolls to the hidden card, not just its leader');
  assert.equal(panel.graph.edges.some(edge => panel.edgeSelected(edge)), false,
    'Selecting an attached independent task must not highlight a false dependency');

  panel.draftPredecessors = ['travel'];
  panel.changePredecessors();
  context.ElementPlus.ElMessageBox.confirm = async () => { throw new Error('keep draft'); };
  assert.equal(await panel.revealTask(revealRows[3].path), false);
  assert.equal(panel.showDisabled, false);
  assert.equal(panel.selectedId, 'independent');
  assert.deepEqual(plain(panel.draftPredecessors), ['travel']);
  context.ElementPlus.ElMessageBox.confirm = async () => {};
  assert.equal(await panel.revealTask(revealRows[3].path), true);
  assert.equal(panel.showDisabled, true, 'A disabled search match becomes visible without enabling it');
  assert.equal(panel.selectedId, 'disabled-result');
  assert.equal(panel.pinnedGroup, 'destination');
  panel.savePending = true;
  assert.equal(await panel.revealTask(backboneRows[0].path), false, 'Do not change selection during a save');
  panel.savePending = false;
  assert.equal(await panel.revealTask(revealRows[4].path), true, 'Invalid search matches remain inspectable');
  assert.equal(panel.pinnedGroup, '');
  assert.equal(await panel.revealTask('missing/path'), false);
  assert.deepEqual(revealRows, originalRows, 'Search is a read-only display operation');
  assert.deepEqual(emitted, []);
}

async function testSaveQueue() {
  let applicationDefinition;
  const requests = [];
  let releaseOrdering;
  let rejectTasks = false;
  const responseConfig = (tasks) => ({ config_version: 3, tasks, active_character: { server: 'test', name: 'role' } });
  context.window.WebUIApi = {
    request: async (method, route, payload) => {
      requests.push({ method, route, payload: plain(payload) });
      if (route === '/task-ordering') return new Promise(resolve => { releaseOrdering = resolve; });
      if (rejectTasks) return { ok: false, data: { message: 'cycle rejected' } };
      return { ok: true, data: responseConfig(payload.tasks) };
    },
    get: async () => ({ config_version: 0 }),
    errorMessage: (data) => data.message,
  };
  context.Vue.createApp = (definition) => {
    applicationDefinition = definition;
    return { component() {}, use() {}, mount() {} };
  };
  for (const name of ['AppSidebar', 'NewsPanel', 'OverviewPanel', 'SchedulerPanel', 'TaskPanel', 'SettingsPanel', 'EditorPanel', 'ApiDocsPanel', 'DiagnosticsPanel', 'ErrorArchivesPanel', 'NotificationsPanel', 'UpdatePanel', 'AboutPanel', 'TaskTree']) context[name] = {};
  virtualMachine.runInContext(source('backend/webui/static/js/stores/runtimeStore.js'), context);
  virtualMachine.runInContext(source('backend/webui/static/js/app.js'), context);
  const application = applicationDefinition.setup();
  application.openEditModal('first', {
    params: { diff: 15 }, params_doc: { diff: '普通难度' },
  }, 'weekly/first');
  assert.equal(application.paramLabel('diff'), '普通难度');
  application.openEditModal('second', {
    params: { diff: 6 }, params_doc: { diff: '混沌难度' },
  }, 'weekly/second');
  assert.equal(application.paramLabel('diff'), '混沌难度', 'Labels belong to each task, not the parameter key globally');
  application.openEditModal('legacy', { params: { diff: 1 } }, 'custom/legacy');
  assert.equal(application.paramLabel('diff'), 'diff', 'Old custom tasks fall back to their parameter names');
  assert.equal(application.paramLabel('constructor'), 'constructor', 'Inherited object properties are not labels');
  application.editTaskData.value.params_doc = { diff: '' };
  assert.equal(application.paramLabel('diff'), 'diff');
  application.editTaskData.value.params_doc = { diff: '重新加载的难度' };
  assert.equal(application.paramLabel('diff'), '重新加载的难度');
  application.currentAccount.value = 'test-account';
  Object.assign(application.activeCharacter, { server: 'test', name: 'role' });
  application.configData.tasks = { daily: { area: { before: { id: 'before', on: false, next_exec_time: 100, params: { keep: 7 } } } } };
  const originalTasks = application.configData.tasks;
  const orderingSave = application.saveTaskOrdering({ user_order: ['daily/area/before'] });
  let result;
  const graphSave = application.saveTaskGraph({ id: 'before', path: 'daily/area/before', changes: { on: true }, onComplete: (success) => { result = success; } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 1, 'Graph saving waits behind ordering in the same FIFO');
  assert.equal(originalTasks.daily.area.before.on, false, 'Do not optimistically corrupt the persisted projection');
  originalTasks.daily.area.before.params.keep = 99;
  releaseOrdering({ ok: true, data: { config_version: 2, projection: { overlay: { selection_policy: 'nearest_ready' } } } });
  await orderingSave;
  await graphSave;
  assert.equal(result, true);
  assert.equal(requests[1].payload.tasks.daily.area.before.params.keep, 7, 'Payload is frozen at enqueue time');
  assert.equal(requests[1].payload.tasks.daily.area.before.next_exec_time, 0);
  assert.equal(application.configData.tasks.daily.area.before.on, true);
  assert.equal(application.taskGraphSaving.value, false);
  assert.equal(typeof application.runTaskRange, 'function', 'Range-run must be exposed to the page template');

  rejectTasks = true;
  await application.saveTaskGraph({ id: 'before', path: 'daily/area/before', changes: { on: false }, onComplete: (success) => { result = success; } });
  assert.equal(result, false);
  assert.equal(application.configData.tasks.daily.area.before.on, true, 'Failed writes must not replace configuration');
  rejectTasks = false;
  const nextOrdering = application.saveTaskOrdering({ user_order: [] });
  const staleSave = application.saveTaskGraph({ id: 'before', path: 'daily/area/before', changes: { on: false }, onComplete: (success) => { result = success; } });
  await new Promise(resolve => setImmediate(resolve));
  const beforeSwitch = requests.length;
  application.activeCharacter.name = 'different-role';
  releaseOrdering({ ok: true, data: { config_version: 4, projection: { overlay: {} } } });
  await nextOrdering;
  await staleSave;
  assert.equal(requests.length, beforeSwitch, 'Queued graph writes cannot cross character boundaries');
  assert.equal(result, false);
}

async function main() {
  const compilationErrors = [];
  context.Vue.compile(component.template, {
    onError: error => compilationErrors.push(error.message),
    decodeEntities: value => value.replace(/&(?:amp|lt|gt|quot);/g, entity => ({
      '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
    })[entity]),
  });
  assert.deepEqual(compilationErrors, [], 'The actual Vue template must compile');
  await testGraphEditing();
  await testSearchReveal();
  await testSaveQueue();
  console.log('PASS: graph topology, proximity, editing, Vue compilation, save FIFO and failure isolation');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
