# 依赖、顺序与计算图

## 自动选择

Stable-ID after_tasks=AND; due/exhausted predecessors block. Disabled/postponed/rescheduled release successors, except unfinished continuation_pending; no success epochs. Recollect after tasks; retries yield to first attempts, successors count independently. Blocked chains wait. Manual runs ignore constraints.

preferred_locations inherits ensure_in; [] clears preference, not source. nearest_ready default: (minimum directed steps, ready-with-predecessors first, saved-list index, ID). Unknown/unreachable/no preference=infinity, still executable. Unit edges include nested exits/entries; multi-location minimum≠seconds/global optimum. list_ready uses saved list. Save rejects unknown/self/cyclic references; reload blocks affected chains only.

ANYWHERE=任意位置, no default preference/map node/route. Anywhere-only grouping preserves dependencies.

## 持久化与视图

Hierarchy/order/graph share all-field fuzzy search, protected drafts/saves and blur cancellation; read-only browsing. Order/enabled lists share full queue: columns left-to-right, groups top-to-bottom, expanded decks, errors last. Include blocked/future; disabled references never run. Range-run/highlight follow queue, not live predictions.

Global data/config.json task_ordering: schema_version=1, selection_policy, nested ID items; user_order=flattened legacy seed. IDs→paths, fallback registration/path. Dissolve single-child groups; display noncontiguous groups unwrapped. Edits preserve originals, never persist queues. Ignore hard_edges/layout/group_order; layout API no-op, no coordinates/old DAG panels.

## 图主干与归堆

Dependency endpoints form backbone; longest depth gives columns. Mind-map alignment, unique shared successors, faded secondary edges, cross-level gap routing. Hide transitive display edges only; preserve AND, diagnose errors.

Attach independents across levels to enabled backbone by directed **source ensure_in** distance, then depth/list. Backbone first, attachments distance/list sorted; no inherited constraints/priority/anchors. Without reachable backbone, require whole-deck common zero-cost origin; no multi-entry bridging, unknown distances or threshold/toggle.

Default enabled/predecessor closure, disabled gray. Join enables; removal disables/warns successor release. Accessible name/status/location, hover/focus/pin expansion, internal scrolling. Preferences only affect scheduling. Save reflows or retains failed drafts. FIFO freezes snapshots/rejects role changes; busy blocks edits. Parent shares mount/refresh static locations, visible/retryable failures; no device polling/route promise.
