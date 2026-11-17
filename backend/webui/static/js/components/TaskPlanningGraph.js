const TaskPlanningGraph = {
  name: 'TaskPlanningGraph',
  props: {
    rows: { type: Array, required: true },
    orderingProjection: { type: Object, default: null },
    executionBusy: { type: Boolean, default: false },
    saving: { type: Boolean, default: false },
    locationCosts: { type: Object, default: () => ({}) },
    locations: { type: Array, default: () => [] },
    loadingLocations: { type: Boolean, default: false },
    locationError: { type: String, default: '' },
  },
  emits: ['edit-task', 'save-graph', 'refresh-locations'],
  data() {
    return {
      showDisabled: false, zoom: 1, hoveredGroup: '', pinnedGroup: '',
      selectedId: '', draftPredecessors: [], draftLocations: [], inheritPredecessors: false,
      inheritLocations: false, dirty: false, savePending: false, saveError: '',
      addVisible: false, addTaskId: '',
    };
  },
  computed: {
    graph() {
      return window.TaskPlanningLayout.build(this.rows, {
        costs: this.locationCosts, showDisabled: this.showDisabled,
      });
    },
    boardStyle() {
      const { cardWidth, cardHeight } = window.TaskPlanningLayout.geometry;
      return {
        width: `${this.graph.width}px`, height: `${this.graph.height}px`, transform: `scale(${this.zoom})`,
        '--planning-card-width': `${cardWidth}px`, '--planning-card-height': `${cardHeight}px`,
      };
    },
    selectedRow() {
      return this.rows.find((row) => this.identifier(row) === this.selectedId) || null;
    },
    disabledRows() { return this.rows.filter((row) => !row.item.on); },
    locked() { return this.executionBusy || this.saving || this.savePending; },
    dependencyOptions() { return this.rows.filter((row) => this.identifier(row) !== this.selectedId); },
    dependencyValidation() {
      if (!this.selectedRow) return '';
      return window.TaskPlanningLayout.dependencyError(this.rows, this.selectedId, this.draftPredecessors);
    },
    selectedDependents() {
      return this.rows.filter((row) => this.values(row, 'after_tasks').includes(this.selectedId));
    },
  },
  watch: {
    rows() {
      if (!this.selectedRow) {
        this.selectedId = '';
        this.dirty = false;
      } else if (!this.dirty && !this.savePending) this.readDraft();
    },
    locationCosts() { this.$nextTick(() => this.fitGraph()); },
  },
  mounted() { this.fitGraph(); },
  methods: {
    identifier(row) { return window.TaskPlanningLayout.taskId(row); },
    values(row, field) { return window.TaskPlanningLayout.specification(row, field); },
    entryLabel(row) {
      return window.TaskPlanningLayout.entryLocations(row).join(' / ') || '未配置地点';
    },
    loadLocations() { this.$emit('refresh-locations'); },
    fitGraph() {
      const width = this.$refs.viewport?.clientWidth || 800;
      this.zoom = Math.max(0.25, Math.min(1, (width - 36) / this.graph.width));
      if (this.$refs.viewport) this.$refs.viewport.scrollTo({ left: 0, top: 0 });
    },
    changeZoom(amount) { this.zoom = Math.max(0.25, Math.min(1.5, this.zoom + amount)); },
    position(node) { return { left: `${node.left}px`, top: `${node.top}px` }; },
    edgePath(edge) {
      const { cardWidth, cardHeight } = window.TaskPlanningLayout.geometry;
      let currentHorizontal = edge.source.left + cardWidth;
      let currentVertical = edge.source.top + cardHeight / 2;
      let path = `M ${currentHorizontal} ${currentVertical}`;
      const connect = (endHorizontal, endVertical) => {
        const bendHorizontal = (currentHorizontal + endHorizontal) / 2;
        path += ` C ${bendHorizontal} ${currentVertical}, ${bendHorizontal} ${endVertical}, ${endHorizontal} ${endVertical}`;
        currentHorizontal = endHorizontal;
        currentVertical = endVertical;
      };
      for (const waypoint of edge.waypoints) {
        connect(waypoint.left - 16, waypoint.top);
        currentHorizontal = waypoint.left + cardWidth + 16;
        path += ` H ${currentHorizontal}`;
      }
      connect(edge.target.left - 6, edge.target.top + cardHeight / 2);
      return path;
    },
    edgeSelected(edge) {
      return edge.predecessor === this.selectedId
        || edge.target.id === this.selectedId;
    },
    groupExpanded(group) { return this.hoveredGroup === group.id || this.pinnedGroup === group.id; },
    toggleGroup(group) { this.pinnedGroup = this.pinnedGroup === group.id ? '' : group.id; },
    statusTheme(row) {
      const theme = window.TaskStatusTheme;
      if (row.item.on && row.item.planning_status?.error) return theme.STATUS_THEME.error;
      if (row.item.on && row.item.planning_status?.blocked_by?.length) return theme.STATUS_THEME.pending;
      return theme.getTaskTheme(row.item);
    },
    status(row) {
      if (!row.item.on) return '未启用';
      if (row.item.planning_status?.error) return '配置异常';
      if (row.item.planning_status?.blocked_by?.length) return '等待前序';
      return this.statusTheme(row).label;
    },
    async selectRow(row) {
      if (this.savePending) return false;
      if (this.identifier(row) === this.selectedId) return true;
      if (this.dirty) {
        try {
          await ElementPlus.ElMessageBox.confirm('当前关系尚未保存，放弃修改并切换任务？', '未保存的修改', {
            confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning',
          });
        } catch { return false; }
      }
      this.selectedId = this.identifier(row);
      this.readDraft();
      return true;
    },
    async revealTask(taskPath) {
      const row = this.rows.find(candidate => candidate.path === taskPath);
      if (!row || !await this.selectRow(row)) return false;
      if (!row.item.on) this.showDisabled = true;
      const group = this.graph.groups.find(candidate => candidate.rows.some(member => this.identifier(member) === this.selectedId));
      this.pinnedGroup = group?.id || '';
      this.hoveredGroup = '';
      await this.$nextTick(() => {});
      const candidates = this.$refs.viewport?.querySelectorAll('[data-graph-task-id]') || [];
      const card = Array.from(candidates).find(candidate => candidate.dataset.graphTaskId === this.selectedId);
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
        card.focus({ preventScroll: true });
      }
      return true;
    },
    readDraft() {
      if (!this.selectedRow) return;
      this.draftPredecessors = this.values(this.selectedRow, 'after_tasks');
      this.draftLocations = this.values(this.selectedRow, 'preferred_locations');
      this.inheritPredecessors = !Object.prototype.hasOwnProperty.call(this.selectedRow.item, 'after_tasks');
      this.inheritLocations = !Object.prototype.hasOwnProperty.call(this.selectedRow.item, 'preferred_locations');
      this.dirty = false;
      this.saveError = '';
    },
    changePredecessors() { this.inheritPredecessors = false; this.dirty = true; },
    changeLocations() { this.inheritLocations = false; this.dirty = true; },
    restoreDefaults(field) {
      if (this.locked || !this.selectedRow) return;
      const defaults = [...(this.selectedRow.item.planning_defaults?.[field] || [])];
      if (field === 'after_tasks') {
        this.draftPredecessors = defaults;
        this.inheritPredecessors = true;
      } else {
        this.draftLocations = defaults;
        this.inheritLocations = true;
      }
      this.dirty = true;
    },
    submitChange(row, changes, inheritFields = []) {
      if (this.locked) return;
      this.saveError = '';
      this.savePending = true;
      this.$emit('save-graph', {
        path: row.path, id: this.identifier(row), changes, inheritFields,
        onComplete: (success, message) => {
          this.savePending = false;
          if (!success) {
            this.saveError = message || '保存失败，修改未应用，请重试';
            return;
          }
          this.dirty = false;
          this.addVisible = false;
          this.addTaskId = '';
          this.hoveredGroup = '';
          this.$nextTick(() => { this.readDraft(); });
        },
      });
    },
    applyDraft() {
      if (!this.selectedRow || this.dependencyValidation || !this.dirty) return;
      const changes = {};
      const inheritFields = [];
      if (this.inheritPredecessors) inheritFields.push('after_tasks');
      else changes.after_tasks = [...this.draftPredecessors];
      if (this.inheritLocations) inheritFields.push('preferred_locations');
      else changes.preferred_locations = [...this.draftLocations];
      this.submitChange(this.selectedRow, changes, inheritFields);
    },
    addTask() {
      if (this.dirty) return;
      const row = this.disabledRows.find((candidate) => this.identifier(candidate) === this.addTaskId);
      if (row) this.submitChange(row, { on: true });
    },
    async removeSelectedTask() {
      if (this.locked || this.dirty || !this.selectedRow?.item.on) return;
      const row = this.selectedRow;
      const dependentCount = this.selectedDependents.filter((dependent) => dependent.item.on).length;
      try {
        await ElementPlus.ElMessageBox.confirm(
          `停用“${row.key}”，保留脚本、参数和依赖关系。${dependentCount ? `有 ${dependentCount} 个已启用后继；按现有规则，停用的前序不再阻塞它们，图中仍保留灰色参考节点。` : ''}`,
          '移出执行图', { confirmButtonText: '停用任务', cancelButtonText: '取消', type: 'warning' },
        );
      } catch { return; }
      this.submitChange(row, { on: false });
    },
  },
  template: `
<section class="task-planning-graph" aria-label="任务计算图">
  <header class="planning-toolbar">
    <h2>任务计算图 <span>{{ graph.taskCount }} 个任务 · {{ graph.groups.length }} 组</span></h2>
    <div class="planning-actions">
      <button type="button" class="planning-primary" :disabled="locked || dirty || !disabledRows.length" @click="addVisible = !addVisible">＋ 加入任务</button>
      <button type="button" :disabled="loadingLocations" @click="loadLocations">{{ loadingLocations ? '读取中…' : '刷新图' }}</button>
    </div>
  </header>
  <div class="planning-controls">
    <label><input v-model="showDisabled" type="checkbox">显示未启用</label>
    <div class="planning-zoom">
      <button type="button" @click="changeZoom(-0.1)" aria-label="缩小">−</button>
      <span>{{ Math.round(zoom * 100) }}%</span>
      <button type="button" @click="changeZoom(0.1)" aria-label="放大">＋</button>
      <button type="button" @click="fitGraph">适应宽度</button>
    </div>
  </div>
  <div v-if="locationError" class="planning-alert" role="alert">地图加载失败：{{ locationError }}<button @click="loadLocations">重试</button></div>
  <div v-if="saveError" class="planning-alert" role="alert">{{ saveError }}</div>
  <div v-if="addVisible" class="planning-add">
    <span>选择要加入的任务</span>
    <el-select v-model="addTaskId" filterable placeholder="搜索未启用任务" :disabled="locked" aria-label="加入的任务">
      <el-option v-for="row in disabledRows" :key="identifier(row)" :value="identifier(row)" :label="row.path" />
    </el-select>
    <button type="button" class="planning-primary" :disabled="locked || dirty || !addTaskId" @click="addTask">加入</button>
    <button type="button" :disabled="savePending" @click="addVisible = false">取消</button>
  </div>
  <div class="planning-body">
    <div ref="viewport" class="planning-viewport" tabindex="0" aria-label="可滚动的依赖树">
      <div v-if="graph.errors.length" class="planning-invalid" role="alert">
        <strong>任务配置异常（点击查看）</strong>
        <button v-for="entry in graph.errors" :key="identifier(entry.row)" :data-graph-task-id="identifier(entry.row)" @click="selectRow(entry.row)">{{ entry.row.key }}：{{ entry.message }}</button>
      </div>
      <div class="planning-scale-space" :style="{ width: graph.width * zoom + 'px', height: graph.height * zoom + 'px' }">
        <div class="planning-board" :style="boardStyle">
          <svg class="planning-edges" :width="graph.width" :height="graph.height" aria-label="真实依赖连接">
            <defs><marker id="planning-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" /></marker></defs>
            <path v-for="edge in graph.edges" :key="edge.key" :d="edgePath(edge)"
              :class="['planning-edge', { 'is-secondary': !edge.primary, 'is-selected': edgeSelected(edge) }]"
              marker-end="url(#planning-arrow)"><title>{{ edge.label }}</title></path>
          </svg>
          <div v-for="group in graph.groups" :key="group.id" class="planning-deck"
            :class="{ 'is-expanded': groupExpanded(group), 'has-peers': group.rows.length > 1 }" :style="position(group)"
            @mouseenter="hoveredGroup = group.id" @mouseleave="hoveredGroup = ''"
            @focusin="hoveredGroup = group.id" @focusout="!$event.currentTarget.contains($event.relatedTarget) && (hoveredGroup = '')">
            <div v-if="group.rows.length > 1" class="planning-deck-back planning-deck-back-second"></div>
            <div v-if="group.rows.length > 2" class="planning-deck-back planning-deck-back-third"></div>
            <button v-if="group.rows.length > 1" type="button" class="planning-deck-count" :aria-expanded="groupExpanded(group)"
              :aria-label="group.rows.length + ' 个任务，展开或收起'" @click="toggleGroup(group)">
              {{ group.rows.length }} <i :class="pinnedGroup === group.id ? 'fa fa-thumb-tack' : 'fa fa-clone'"></i>
            </button>
            <div class="planning-deck-cards">
              <button v-for="(row, rowIndex) in group.rows" :key="identifier(row)" type="button" class="planning-task-card"
                :class="{ 'is-selected': selectedId === identifier(row), 'is-disabled': !row.item.on }"
                :tabindex="rowIndex === 0 || groupExpanded(group) ? 0 : -1"
                :aria-hidden="rowIndex > 0 && !groupExpanded(group)" :data-graph-task-id="identifier(row)"
                :title="row.path" @click="selectRow(row)">
                <span class="planning-card-heading"><strong>{{ row.key }}</strong><span class="planning-status-dot" role="img"
                  :style="{ backgroundColor: statusTheme(row).nodeStroke }" :title="status(row)" :aria-label="status(row)"></span></span>
                <span class="planning-card-location"><i class="fa fa-map-marker"></i> {{ entryLabel(row) }}</span>
              </button>
            </div>
          </div>
          <div v-if="!graph.taskCount" class="planning-empty">尚未启用任务。点击“加入任务”，从已注册的任务开始构建。</div>
        </div>
      </div>
    </div>
    <aside class="planning-inspector">
      <template v-if="selectedRow">
        <div class="planning-inspector-title"><span>任务关系</span><span>{{ status(selectedRow) }}</span></div>
        <h3>{{ selectedRow.key }}</h3><p class="planning-inspector-path">{{ selectedRow.path }}</p>
        <div v-if="selectedRow.item.planning_status?.blocked_by?.length" class="planning-note">当前等待：{{ selectedRow.item.planning_status.blocked_by.join('、') }}</div>
        <p class="planning-card-location"><i class="fa fa-map-marker"></i> {{ entryLabel(selectedRow) }}</p>
        <label>前序任务</label>
        <el-select v-model="draftPredecessors" multiple filterable :disabled="locked" placeholder="选择任务" aria-label="编辑前序任务" @change="changePredecessors">
          <el-option v-for="row in dependencyOptions" :key="identifier(row)" :value="identifier(row)" :label="row.path + (row.item.on ? '' : '（未启用）')" />
        </el-select>
        <button type="button" class="planning-text-button" :disabled="locked" @click="restoreDefaults('after_tasks')">恢复默认</button>
        <label>推荐地点</label>
        <el-select v-model="draftLocations" multiple filterable :disabled="locked || !!locationError || loadingLocations" placeholder="不限制地点" aria-label="编辑推荐地点" @change="changeLocations">
          <el-option v-for="location in locations" :key="location" :value="location" :label="location" />
        </el-select>
        <button type="button" class="planning-text-button" :disabled="locked" @click="restoreDefaults('preferred_locations')">恢复默认</button>
        <div v-if="dependencyValidation" role="alert" class="planning-alert">{{ dependencyValidation }}</div>
        <button type="button" class="planning-primary planning-apply" :disabled="locked || !dirty || !!dependencyValidation" @click="applyDraft">{{ savePending ? '保存中…' : '保存' }}</button>
        <button v-if="dirty" type="button" :disabled="savePending" @click="readDraft">放弃修改</button>
        <div class="planning-inspector-secondary">
          <button type="button" :disabled="locked || dirty" @click="$emit('edit-task', selectedRow)">参数与完整配置</button>
          <button v-if="selectedRow.item.on" type="button" class="planning-danger" :disabled="locked || dirty" @click="removeSelectedTask">移出执行图（停用）</button>
        </div>
        <div v-if="selectedDependents.length" class="planning-dependents"><label>后继任务</label>
          <button v-for="row in selectedDependents" :key="identifier(row)" @click="selectRow(row)">{{ row.key }} <i class="fa fa-angle-right"></i></button>
        </div>
      </template>
      <div v-else class="planning-inspector-empty"><i class="fa fa-sitemap"></i><h3>选择任务以编辑</h3></div>
    </aside>
  </div>
</section>`,
};
