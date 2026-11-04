/* A display projection, not a second scheduler. Only declared predecessors create edges. */
window.TaskPlanningLayout = (() => {
  const geometry = Object.freeze({
    cardWidth: 168, cardHeight: 76, columnGap: 96,
    rowGap: 40, padding: 36,
  });

  function specification(row, field) {
    const value = row.item[field] ?? row.item.planning_effective?.[field]
      ?? row.item.planning_defaults?.[field] ?? [];
    return Array.isArray(value) ? [...new Set(value)] : [];
  }

  function taskId(row) {
    return String(row.item.id || row.path);
  }

  function entryLocations(row) {
    const locations = row.item.ensure_in;
    return Array.isArray(locations)
      ? [...new Set(locations.filter((location) => typeof location === 'string' && location.trim()))] : [];
  }

  function distanceBetween(origins, targets, costs) {
    const distances = origins.flatMap(origin => targets.map(target => costs[origin]?.[target]))
      .filter(distance => typeof distance === 'number' && Number.isFinite(distance) && distance >= 0);
    return distances.length ? Math.min(...distances) : Infinity;
  }

  function build(rows, { costs = {}, showDisabled = false } = {}) {
    const rowById = new Map(rows.map((row) => [taskId(row), row]));
    const predecessors = new Map(rows.map((row) => [taskId(row), specification(row, 'after_tasks')]));
    const visibleIds = new Set();
    function includeAncestors(identifier) {
      if (visibleIds.has(identifier) || !rowById.has(identifier)) return;
      visibleIds.add(identifier);
      for (const predecessor of predecessors.get(identifier)) includeAncestors(predecessor);
    }
    rows.filter((row) => showDisabled || row.item.on).forEach((row) => includeAncestors(taskId(row)));

    const errors = new Map();
    const levels = new Map();
    const visiting = new Set();
    function depth(identifier) {
      if (levels.has(identifier)) return levels.get(identifier);
      if (visiting.has(identifier)) {
        errors.set(identifier, '前序依赖存在环，请编辑后解除');
        return 0;
      }
      visiting.add(identifier);
      const row = rowById.get(identifier);
      if (row.item.planning_status?.error) errors.set(identifier, row.item.planning_status.error);
      if (row.item.ensure_in !== null && !entryLocations(row).length) {
        errors.set(identifier, '起点未配置，请检查任务');
      }
      let level = 1;
      for (const predecessor of predecessors.get(identifier)) {
        if (!rowById.has(predecessor)) {
          errors.set(identifier, `前序任务不存在：${predecessor}`);
          continue;
        }
        level = Math.max(level, depth(predecessor) + 1);
        if (errors.has(predecessor)) errors.set(identifier, `前序配置异常：${predecessor}`);
      }
      visiting.delete(identifier);
      levels.set(identifier, level);
      return level;
    }
    for (const identifier of visibleIds) depth(identifier);

    const validRows = rows.filter(row => visibleIds.has(taskId(row)) && !errors.has(taskId(row)));
    const orderById = new Map(rows.map((row, index) => [taskId(row), index]));
    const ancestorCache = new Map();
    function ancestors(identifier) {
      if (!ancestorCache.has(identifier)) {
        const allAncestors = new Set(predecessors.get(identifier));
        for (const parent of predecessors.get(identifier)) {
          for (const ancestor of ancestors(parent)) allAncestors.add(ancestor);
        }
        ancestorCache.set(identifier, allAncestors);
      }
      return ancestorCache.get(identifier);
    }
    // Remove redundant display edges only; the stored AND constraints remain untouched.
    const directPredecessors = new Map(validRows.map(row => {
      const identifier = taskId(row);
      const parents = predecessors.get(identifier);
      return [identifier, parents.filter(parent => !parents.some(other => other !== parent && ancestors(other).has(parent)))];
    }));
    const backboneIds = new Set();
    for (const [identifier, parents] of directPredecessors) {
      if (parents.length) backboneIds.add(identifier);
      for (const parent of parents) backboneIds.add(parent);
    }

    const groups = [];
    const groupByTask = new Map();
    function createGroup(row, backbone) {
      const identifier = taskId(row);
      const group = {
        id: identifier, rows: [row], level: levels.get(identifier), backbone,
        stackOrigins: entryLocations(row), distances: {}, children: [], parentId: null,
      };
      groups.push(group);
      groupByTask.set(identifier, group);
      return group;
    }
    const backboneGroups = validRows.filter(row => backboneIds.has(taskId(row))).map(row => createGroup(row, true));
    const fallbackGroups = [];
    for (const row of validRows.filter(candidate => !backboneIds.has(taskId(candidate)))) {
      const identifier = taskId(row);
      const locations = entryLocations(row);
      // Anchor distance always comes from the trunk card, never another attached peer.
      const nearest = backboneGroups.filter(group => group.rows[0].item.on).map(group => ({
        group, distance: distanceBetween(group.stackOrigins, locations, costs),
      })).filter(candidate => Number.isFinite(candidate.distance)).sort((left, right) =>
        left.distance - right.distance || left.group.level - right.group.level
        || orderById.get(left.group.id) - orderById.get(right.group.id))[0];
      if (nearest) {
        nearest.group.rows.push(row);
        nearest.group.distances[identifier] = nearest.distance;
        groupByTask.set(identifier, nearest.group);
        continue;
      }
      // Without a reachable trunk, keep independent same-place decks instead of inventing a route.
      const matching = fallbackGroups.map(group => ({
        group, origins: group.stackOrigins.filter(origin => distanceBetween([origin], locations, costs) === 0),
      })).find(candidate => candidate.origins.length);
      if (matching) {
        matching.group.rows.push(row);
        matching.group.stackOrigins = matching.origins;
        groupByTask.set(identifier, matching.group);
      } else fallbackGroups.push(createGroup(row, false));
    }
    for (const group of backboneGroups) {
      group.rows = [group.rows[0], ...group.rows.slice(1).sort((left, right) =>
        group.distances[taskId(left)] - group.distances[taskId(right)]
        || orderById.get(taskId(left)) - orderById.get(taskId(right)))];
    }

    const roots = [];
    for (const group of groups) {
      const parents = directPredecessors.get(group.id).map(identifier => groupByTask.get(identifier));
      const primaryParent = parents.sort((left, right) => right.level - left.level
        || orderById.get(left.id) - orderById.get(right.id))[0];
      if (primaryParent) {
        group.parentId = primaryParent.id;
        primaryParent.children.push(group);
      } else roots.push(group);
    }
    function measure(group) {
      group.span = Math.max(geometry.cardHeight + geometry.rowGap,
        group.children.reduce((total, child) => total + measure(child), 0));
      return group.span;
    }
    function place(group, top) {
      group.left = geometry.padding + (group.level - 1) * (geometry.cardWidth + geometry.columnGap);
      group.top = top + (group.span - geometry.cardHeight) / 2;
      let nextTop = top;
      for (const child of group.children) {
        place(child, nextTop);
        nextTop += child.span;
      }
    }
    let nextTop = geometry.padding;
    for (const group of roots) {
      measure(group);
      place(group, nextTop);
      nextTop += group.span;
    }
    const columnCount = Math.max(1, ...groups.map(group => group.level));
    const width = columnCount * geometry.cardWidth + (columnCount - 1) * geometry.columnGap + geometry.padding * 2;
    const height = Math.max(300, nextTop + geometry.padding);
    function connectionWaypoints(source, target) {
      const waypoints = [];
      for (let level = source.level + 1; level < target.level; level++) {
        const obstacles = groups.filter(group => group.level === level).sort((left, right) => left.top - right.top);
        const fraction = (level - source.level) / (target.level - source.level);
        const desiredTop = source.top + (target.top - source.top) * fraction + geometry.cardHeight / 2;
        const gaps = [];
        let gapStart = 16;
        for (const obstacle of obstacles) {
          const gapEnd = obstacle.top - 20;
          if (gapEnd >= gapStart) gaps.push([gapStart, gapEnd]);
          gapStart = obstacle.top + geometry.cardHeight + 16;
        }
        gaps.push([gapStart, height - 16]);
        const top = gaps.map(([start, end]) => Math.max(start, Math.min(end, desiredTop)))
          .sort((left, right) => Math.abs(left - desiredTop) - Math.abs(right - desiredTop))[0];
        waypoints.push({ left: geometry.padding + (level - 1) * (geometry.cardWidth + geometry.columnGap), top });
      }
      return waypoints;
    }
    const edges = [];
    for (const group of backboneGroups) {
      const parents = directPredecessors.get(group.id);
      for (const predecessor of parents) {
        const parent = groupByTask.get(predecessor);
        if (parent) edges.push({
          source: parent, target: group, kind: 'dependency', predecessor,
          primary: group.parentId === predecessor,
          waypoints: connectionWaypoints(parent, group),
          key: `${predecessor}:${group.id}`,
          label: `${rowById.get(predecessor).key} → ${group.rows[0].key}`,
        });
      }
    }
    return {
      groups, edges, width, height,
      errors: rows.filter((row) => visibleIds.has(taskId(row)) && errors.has(taskId(row)))
        .map((row) => ({ row, message: errors.get(taskId(row)) })),
      taskCount: visibleIds.size,
    };
  }

  function dependencyError(rows, identifier, proposedPredecessors) {
    const dependencies = new Map(rows.map((row) => [taskId(row), specification(row, 'after_tasks')]));
    dependencies.set(identifier, proposedPredecessors);
    const visited = new Set();
    const visiting = new Set();
    function visit(current) {
      if (!dependencies.has(current)) return `前序任务不存在：${current}`;
      if (visiting.has(current)) return '这项修改会形成循环依赖';
      if (visited.has(current)) return '';
      visiting.add(current);
      for (const predecessor of dependencies.get(current)) {
        const error = visit(predecessor);
        if (error) return error;
      }
      visiting.delete(current);
      visited.add(current);
      return '';
    }
    return visit(identifier);
  }

  return { build, taskId, specification, entryLocations, dependencyError, geometry };
})();
