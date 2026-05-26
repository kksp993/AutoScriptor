"""Core planner for the Bagin badge exchange task.

Rune order:
    0 -> 八戒之符
    1 -> 敖玥之符
    2 -> 嫦娥之符

The real UI layer only needs to fill in ``peek``, ``exchange`` and ``merge``.
``solve`` returns the trajectory that was actually executed.

The planner scores a trajectory as:
    merge_value * merge_count - 2 * peek_count - exchange_count

``merge_value`` defaults to 10 because the live task is usually better served
by favoring extra badges; pass ``merge_value=5`` to use the strict contest
score.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from itertools import product
from typing import Any, Callable, Mapping, Sequence


RUNE_NAMES = ("八戒之符", "敖玥之符", "嫦娥之符")
RUNE_ID = {name: idx for idx, name in enumerate(RUNE_NAMES)}
NUM_RUNE_TYPES = len(RUNE_NAMES)
DEFAULT_MERGE_QUOTA = 3
MAX_REQUESTERS = 3


Op = dict[str, Any]
Executor = Callable[[Op], Sequence[int] | None]


@dataclass
class UserState:
    name: str
    counts: list[int] | None = None
    logged: bool = False
    peeks: int = 0
    merges: int = 0
    merge_remaining: int = DEFAULT_MERGE_QUOTA
    requested_runes: set[int] = field(default_factory=set)
    requesters: set[str] = field(default_factory=set)

    def can_merge(self) -> bool:
        return (
            self.merge_remaining > 0
            and self.counts is not None
            and all(value > 0 for value in self.counts)
        )


@dataclass(frozen=True)
class SearchAction:
    kind: str
    user: int | None = None
    from_user: int | None = None
    to_user: int | None = None
    give_id: int | None = None
    take_id: int | None = None


@dataclass(frozen=True)
class SearchState:
    counts: tuple[tuple[int, int, int], ...]
    current: int
    requested_rune_masks: tuple[int, ...]
    requester_masks: tuple[int, ...]
    merge_remaining: tuple[int, ...]


@dataclass(frozen=True)
class SearchResult:
    score: int
    merges: int
    cost: int
    ops: int
    actions: tuple[SearchAction, ...] = ()

    def rank(self) -> tuple[int, int, int, int]:
        return (self.score, self.merges, -self.cost, -self.ops)


class SearchLimitExceeded(RuntimeError):
    pass


class BoundedExchangeSearch:
    """Deadline-limited exact search on the currently visible state.

    Future merge rewards are unknown, so a merge is simulated as consuming one
    set.  The outer planner executes at most until the next Peek/merge result
    and then searches again with the newly observed counts.
    """

    def __init__(
        self,
        names: Sequence[str],
        initial: SearchState,
        *,
        max_nodes: int = 80_000,
        max_seconds: float = 0.8,
        merge_value: int = 10,
    ) -> None:
        self.names = list(names)
        self.initial = initial
        self.max_nodes = max_nodes
        self.merge_value = merge_value
        self.deadline = time.perf_counter() + max_seconds
        self.memo: dict[SearchState, SearchResult] = {}
        self.bound_memo: dict[SearchState, int] = {}
        self.visiting: set[SearchState] = set()
        self.nodes = 0

    def run(self) -> SearchResult:
        return self._best(self.initial)

    def _check_budget(self) -> None:
        if self.nodes >= self.max_nodes or time.perf_counter() >= self.deadline:
            raise SearchLimitExceeded("search budget exceeded")

    def _best(self, state: SearchState) -> SearchResult:
        if state in self.memo:
            return self.memo[state]
        if state in self.visiting:
            return SearchResult(-10**9, -10**9, 10**9, 10**9)
        self._check_budget()
        self.nodes += 1

        if self._upper_bound_merges(state) <= 0:
            result = SearchResult(0, 0, 0, 0)
            self.memo[state] = result
            return result

        self.visiting.add(state)
        best = SearchResult(0, 0, 0, 0)
        for action in self._candidate_actions(state):
            self._check_budget()
            next_state, gained, cost, step_score = self._apply(state, action)
            if step_score + self._upper_bound_score(next_state) < best.score:
                continue
            child = self._best(next_state)
            if child.score < 0 and child.merges < 0:
                continue
            candidate = SearchResult(
                score=step_score + child.score,
                merges=gained + child.merges,
                cost=cost + child.cost,
                ops=1 + child.ops,
                actions=(action,) + child.actions,
            )
            if candidate.rank() > best.rank():
                best = candidate
        self.visiting.remove(state)
        self.memo[state] = best
        return best

    @staticmethod
    def _upper_bound_merges(state: SearchState) -> int:
        totals = [0] * NUM_RUNE_TYPES
        user_capacity = 0
        for triple in state.counts:
            for rune_id in range(NUM_RUNE_TYPES):
                totals[rune_id] += triple[rune_id]
        for triple, remaining in zip(state.counts, state.merge_remaining):
            user_capacity += min(remaining, sum(triple) // NUM_RUNE_TYPES)
        return min(min(totals), user_capacity)

    def _upper_bound_score(self, state: SearchState) -> int:
        cached = self.bound_memo.get(state)
        if cached is not None:
            return cached
        score = self._h_star_upper_bound_score(state)
        self.bound_memo[state] = score
        return score

    def _h_star_upper_bound_score(self, state: SearchState) -> int:
        """Admissible optimistic bound for remaining net score.

        H* keeps all mathematically necessary resource limits:
        per-user total rune count, remaining merge quota, and global rune totals.
        It subtracts a conservative exchange lower bound computed from the
        minimum possible per-user rune deficits for each merge count.  Peek and
        cache reset costs are ignored here, so the value remains an upper bound
        and is safe for pruning.
        """

        merge_cap = self._upper_bound_merges(state)
        if merge_cap <= 0:
            return 0

        infinity = 10**9
        dp = [infinity] * (merge_cap + 1)
        dp[0] = 0

        for counts, remaining in zip(state.counts, state.merge_remaining):
            user_cap = min(remaining, sum(counts) // NUM_RUNE_TYPES, merge_cap)
            next_dp = [infinity] * (merge_cap + 1)
            deficits = [
                sum(max(0, merges - counts[rune_id]) for rune_id in range(NUM_RUNE_TYPES))
                for merges in range(user_cap + 1)
            ]
            for have, current_deficit in enumerate(dp):
                if current_deficit >= infinity:
                    continue
                for merges in range(user_cap + 1):
                    total_merges = have + merges
                    if total_merges > merge_cap:
                        break
                    candidate = current_deficit + deficits[merges]
                    if candidate < next_dp[total_merges]:
                        next_dp[total_merges] = candidate
            dp = next_dp

        best = 0
        for merges, deficit in enumerate(dp):
            if deficit >= infinity:
                continue
            exchange_lower_bound = (deficit + 1) // 2
            best = max(best, self.merge_value * merges - exchange_lower_bound)
        return best

    def _candidate_actions(self, state: SearchState) -> list[SearchAction]:
        actions: list[SearchAction] = []
        current = state.current
        if self._can_merge_user(state, current):
            actions.append(SearchAction("merge", user=current))

        actions.extend(self._exchange_actions(state))
        actions.extend(self._peek_actions(state))
        return actions

    @staticmethod
    def _can_merge_user(state: SearchState, user: int) -> bool:
        return state.merge_remaining[user] > 0 and all(value > 0 for value in state.counts[user])

    def _exchange_actions(self, state: SearchState) -> list[SearchAction]:
        actor = state.current
        actor_counts = state.counts[actor]
        actions: list[SearchAction] = []

        partners = [idx for idx in range(len(self.names)) if idx != actor]
        partners.sort(key=lambda idx: (state.requester_masks[idx].bit_count(), sum(state.counts[idx])))

        for partner in partners:
            self._check_budget()
            partner_counts = state.counts[partner]
            already_requested = bool(state.requester_masks[partner] & (1 << actor))
            if not already_requested and state.requester_masks[partner].bit_count() >= MAX_REQUESTERS:
                continue

            for give_id, take_id in product(range(NUM_RUNE_TYPES), repeat=2):
                self._check_budget()
                if give_id == take_id:
                    continue
                if actor_counts[give_id] <= 0 or partner_counts[take_id] <= 0:
                    continue
                if state.requested_rune_masks[partner] & (1 << take_id):
                    continue

                actions.append(
                    SearchAction(
                        "exchange",
                        from_user=actor,
                        to_user=partner,
                        give_id=give_id,
                        take_id=take_id,
                    )
                )

        actions.sort(key=lambda action: self._action_order_key(state, action), reverse=True)
        return actions

    def _action_order_key(self, state: SearchState, action: SearchAction) -> tuple[int, int, int]:
        next_state, gained, cost, score = self._apply(state, action)
        return (score + self._upper_bound_score(next_state), gained, -cost)

    def _peek_actions(self, state: SearchState) -> list[SearchAction]:
        actions: list[SearchAction] = []
        for user, counts in enumerate(state.counts):
            self._check_budget()
            if user == state.current and self._user_cache_empty(state, user):
                continue
            if state.merge_remaining[user] <= 0 and self._user_cache_empty(state, user):
                continue
            if not any(counts) and self._user_cache_empty(state, user):
                continue
            actions.append(SearchAction("Peek", user=user))

        actions.sort(
            key=lambda action: (
                action.user != state.current,
                -int(self._can_merge_user(state, action.user or 0)),
                -sum(state.counts[action.user or 0]),
            )
        )
        return actions

    @staticmethod
    def _user_cache_empty(state: SearchState, user: int) -> bool:
        return (
            state.requested_rune_masks[user] == 0
            and state.requester_masks[user] == 0
        )

    @staticmethod
    def _replace_tuple(values: tuple[Any, ...], index: int, value: Any) -> tuple[Any, ...]:
        items = list(values)
        items[index] = value
        return tuple(items)

    def _apply(self, state: SearchState, action: SearchAction) -> tuple[SearchState, int, int, int]:
        if action.kind == "Peek":
            user = action.user
            assert user is not None
            return (
                SearchState(
                    counts=state.counts,
                    current=user,
                    requested_rune_masks=self._replace_tuple(state.requested_rune_masks, user, 0),
                    requester_masks=self._replace_tuple(state.requester_masks, user, 0),
                    merge_remaining=state.merge_remaining,
                ),
                0,
                2,
                -2,
            )

        if action.kind == "merge":
            user = action.user
            assert user is not None
            counts = [list(triple) for triple in state.counts]
            for rune_id in range(NUM_RUNE_TYPES):
                counts[user][rune_id] -= 1
            return (
                SearchState(
                    counts=tuple(tuple(triple) for triple in counts),  # type: ignore[arg-type]
                    current=user,
                    requested_rune_masks=self._replace_tuple(state.requested_rune_masks, user, 0),
                    requester_masks=self._replace_tuple(state.requester_masks, user, 0),
                    merge_remaining=self._replace_tuple(
                        state.merge_remaining,
                        user,
                        max(0, state.merge_remaining[user] - 1),
                    ),
                ),
                1,
                0,
                self.merge_value,
            )

        if action.kind == "exchange":
            actor = action.from_user
            partner = action.to_user
            give_id = action.give_id
            take_id = action.take_id
            assert actor is not None and partner is not None
            assert give_id is not None and take_id is not None

            counts = [list(triple) for triple in state.counts]
            counts[actor][give_id] -= 1
            counts[partner][give_id] += 1
            counts[partner][take_id] -= 1
            counts[actor][take_id] += 1

            return (
                SearchState(
                    counts=tuple(tuple(triple) for triple in counts),  # type: ignore[arg-type]
                    current=actor,
                    requested_rune_masks=self._replace_tuple(
                        state.requested_rune_masks,
                        partner,
                        state.requested_rune_masks[partner] | (1 << take_id),
                    ),
                    requester_masks=self._replace_tuple(
                        state.requester_masks,
                        partner,
                        state.requester_masks[partner] | (1 << actor),
                    ),
                    merge_remaining=state.merge_remaining,
                ),
                0,
                1,
                -1,
            )

        raise RuntimeError(f"unknown action: {action!r}")


class MergeMacroSearch(BoundedExchangeSearch):
    """Search over exchange prefixes that end in a merge.

    This keeps the objective exact for every produced segment: a branch is only
    accepted if its exchanges and peeks culminate in a merge whose net score is
    positive against the recursive continuation.
    """

    def run(self) -> SearchResult:
        return self._best_macro(self.initial)

    def run_frontier(self) -> SearchResult:
        """Pick the best next merge segment using H* without deep recursion."""

        best = SearchResult(0, 0, 0, 0)
        best_rank = (0, 0, 0, 0)
        for actions, next_state, segment_score, segment_cost in self._macro_options(self.initial):
            self._check_budget()
            optimistic_score = segment_score + self._upper_bound_score(next_state)
            rank = (optimistic_score, segment_score, -segment_cost, -len(actions))
            if rank > best_rank:
                best_rank = rank
                best = SearchResult(
                    score=optimistic_score,
                    merges=1,
                    cost=segment_cost,
                    ops=len(actions),
                    actions=tuple(actions),
                )
        return best

    def _best_macro(self, state: SearchState) -> SearchResult:
        if state in self.memo:
            return self.memo[state]
        self._check_budget()
        self.nodes += 1

        if self._upper_bound_merges(state) <= 0:
            result = SearchResult(0, 0, 0, 0)
            self.memo[state] = result
            return result

        best = SearchResult(0, 0, 0, 0)
        for actions, next_state, segment_score, segment_cost in self._macro_options(state):
            self._check_budget()
            if segment_score + self._upper_bound_score(next_state) < best.score:
                continue
            child = self._best_macro(next_state)
            candidate = SearchResult(
                score=segment_score + child.score,
                merges=1 + child.merges,
                cost=segment_cost + child.cost,
                ops=len(actions) + child.ops,
                actions=tuple(actions) + child.actions,
            )
            if candidate.rank() > best.rank():
                best = candidate

        self.memo[state] = best
        return best

    def _macro_options(
        self,
        state: SearchState,
    ) -> list[tuple[list[SearchAction], SearchState, int, int]]:
        options: list[tuple[list[SearchAction], SearchState, int, int]] = []
        targets = list(range(len(self.names)))
        targets.sort(
            key=lambda idx: (
                idx != state.current,
                -int(self._can_merge_user(state, idx)),
                -state.merge_remaining[idx],
                sum(1 for value in state.counts[idx] if value <= 0),
            )
        )

        for target in targets:
            self._check_budget()
            if state.merge_remaining[target] <= 0:
                continue
            start_actions: list[SearchAction] = []
            cursor = state
            segment_score = 0
            segment_cost = 0
            if cursor.current != target:
                action = SearchAction("Peek", user=target)
                cursor, _, cost, score = self._apply(cursor, action)
                start_actions.append(action)
                segment_score += score
                segment_cost += cost

            self._complete_target(
                target,
                cursor,
                start_actions,
                segment_score,
                segment_cost,
                options,
                seen=set(),
            )

        options.sort(key=lambda item: (item[2], -item[3], -len(item[0])), reverse=True)
        return options

    def _complete_target(
        self,
        target: int,
        state: SearchState,
        actions: list[SearchAction],
        score: int,
        cost: int,
        options: list[tuple[list[SearchAction], SearchState, int, int]],
        seen: set[SearchState],
    ) -> None:
        self._check_budget()
        if state in seen:
            return
        seen.add(state)

        if self._can_merge_user(state, target):
            action = SearchAction("merge", user=target)
            next_state, _, step_cost, step_score = self._apply(state, action)
            options.append((actions + [action], next_state, score + step_score, cost + step_cost))
            return

        missing = [rune_id for rune_id, value in enumerate(state.counts[target]) if value <= 0]
        if not missing:
            return
        # This is an H* truncation, not a local balance rule: once even the
        # optimistic future score cannot pay back the prefix, the branch cannot
        # be globally optimal.  Zero-net branches are kept because the final
        # rank still prefers more badges when net score ties.
        if score + self._upper_bound_score(state) < 0 and score < 0:
            return
        if sum(state.counts[target]) < 3:
            return

        for give_id, take_id in self._needed_target_exchanges(state, target):
            for partner in range(len(self.names)):
                if partner == target:
                    continue
                if state.counts[partner][take_id] <= 0:
                    continue
                self._try_exchange_for_target(
                    target,
                    partner,
                    give_id,
                    take_id,
                    state,
                    actions,
                    score,
                    cost,
                    options,
                    seen,
                )

    @staticmethod
    def _needed_target_exchanges(state: SearchState, target: int) -> list[tuple[int, int]]:
        """Minimal direct swaps that can still leave target with one of each.

        A swap never changes a user's total rune count.  For one target to
        perform the next merge, the only useful pre-merge swaps are therefore
        swaps that fill a currently missing rune while giving away a rune that
        remains positive afterward.  This enumerates those swaps instead of
        wandering through locally "balanced" states.
        """

        counts = state.counts[target]
        missing = [rune_id for rune_id, value in enumerate(counts) if value <= 0]
        if not missing or len(missing) == NUM_RUNE_TYPES or sum(counts) < NUM_RUNE_TYPES:
            return []
        if len(missing) == 1:
            take_id = missing[0]
            return [
                (give_id, take_id)
                for give_id in range(NUM_RUNE_TYPES)
                if give_id != take_id and counts[give_id] >= 2
            ]

        present = next(rune_id for rune_id in range(NUM_RUNE_TYPES) if rune_id not in missing)
        if counts[present] < NUM_RUNE_TYPES:
            return []
        return [(present, missing[0]), (present, missing[1])]

    def _try_exchange_for_target(
        self,
        target: int,
        partner: int,
        give_id: int,
        take_id: int,
        state: SearchState,
        actions: list[SearchAction],
        score: int,
        cost: int,
        options: list[tuple[list[SearchAction], SearchState, int, int]],
        seen: set[SearchState],
    ) -> None:
        blocked = (
            bool(state.requested_rune_masks[partner] & (1 << take_id))
            or (
                not bool(state.requester_masks[partner] & (1 << target))
                and state.requester_masks[partner].bit_count() >= MAX_REQUESTERS
            )
        )

        variants: list[tuple[list[SearchAction], SearchState, int, int]] = []
        if not blocked:
            variants.append(([], state, 0, 0))
        else:
            reset_actions: list[SearchAction] = []
            cursor = state
            reset_score = 0
            reset_cost = 0
            for user in (partner, target):
                action = SearchAction("Peek", user=user)
                cursor, _, step_cost, step_score = self._apply(cursor, action)
                reset_actions.append(action)
                reset_score += step_score
                reset_cost += step_cost
            variants.append((reset_actions, cursor, reset_score, reset_cost))

        for prefix, cursor, prefix_score, prefix_cost in variants:
            if cursor.current != target:
                continue
            if cursor.counts[target][give_id] <= 0 or cursor.counts[partner][take_id] <= 0:
                continue
            if cursor.requested_rune_masks[partner] & (1 << take_id):
                continue
            if (
                not bool(cursor.requester_masks[partner] & (1 << target))
                and cursor.requester_masks[partner].bit_count() >= MAX_REQUESTERS
            ):
                continue

            action = SearchAction(
                "exchange",
                from_user=target,
                to_user=partner,
                give_id=give_id,
                take_id=take_id,
            )
            next_state, _, step_cost, step_score = self._apply(cursor, action)
            self._complete_target(
                target,
                next_state,
                actions + prefix + [action],
                score + prefix_score + step_score,
                cost + prefix_cost + step_cost,
                options,
                seen=set(seen),
            )


class BaginPlanner:
    def __init__(
        self,
        users: Sequence[str],
        execute: Executor,
        *,
        merge_remaining: Sequence[int] | Mapping[str, int] | None = None,
        id_style: str = "name",
        max_steps: int = 10_000,
        exact_state_limit: int = 80_000,
        max_step_seconds: float = 0.8,
        merge_value: int = 10,
    ) -> None:
        self.users = self._unique_users(users)
        self.execute = execute
        self.id_style = id_style
        self.max_steps = max_steps
        self.exact_state_limit = exact_state_limit
        self.max_step_seconds = max_step_seconds
        self.merge_value = int(merge_value)
        remaining = self._normalize_merge_remaining(merge_remaining)

        self.states = {
            name: UserState(name=name, merge_remaining=remaining[idx])
            for idx, name in enumerate(self.users)
        }
        self.current: str | None = None
        self.trajectory: list[Op] = []
        self.pending_actions: list[SearchAction] = []
        self.seen_runtime_states: set[tuple[Any, ...]] = set()
        self.total_merges = 0

    @staticmethod
    def _unique_users(users: Sequence[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in users:
            name = str(raw).strip()
            if name and name not in seen:
                result.append(name)
                seen.add(name)
        if not result:
            raise ValueError("users must contain at least one non-empty role name")
        return result

    def _normalize_merge_remaining(
        self,
        merge_remaining: Sequence[int] | Mapping[str, int] | None,
    ) -> list[int]:
        if merge_remaining is None:
            return [DEFAULT_MERGE_QUOTA] * len(self.users)
        if isinstance(merge_remaining, Mapping):
            return [max(0, int(merge_remaining.get(name, DEFAULT_MERGE_QUOTA))) for name in self.users]
        values = [max(0, int(value)) for value in merge_remaining]
        if len(values) != len(self.users):
            raise ValueError("merge_remaining must have the same length as users")
        return values

    def run(self) -> list[Op]:
        for user in self.users:
            self._peek(user)

        while len(self.trajectory) < self.max_steps:
            snapshot = self._runtime_snapshot()
            if snapshot in self.seen_runtime_states:
                break
            self.seen_runtime_states.add(snapshot)
            action = self._next_action()
            if action is None:
                break
            predicted = self._predicted_snapshot(action)
            if predicted is not None and predicted in self.seen_runtime_states:
                self.pending_actions.clear()
                break
            if not self._execute_search_action(action):
                break
        return self.trajectory

    def _next_action(self) -> SearchAction | None:
        if self.pending_actions:
            return self.pending_actions.pop(0)
        return self._best_action()

    def _best_action(self) -> SearchAction | None:
        try:
            result = MergeMacroSearch(
                self.users,
                self._search_state(),
                max_nodes=self.exact_state_limit,
                max_seconds=self.max_step_seconds,
                merge_value=self.merge_value,
            ).run()
        except (SearchLimitExceeded, RecursionError):
            self.pending_actions.clear()
            action = self._frontier_action()
            if action is not None:
                return action
            return self._fallback_action()

        if result.merges <= 0 or not result.actions:
            self.pending_actions.clear()
            return None
        self.pending_actions = list(result.actions[1:])
        return result.actions[0]

    def _frontier_action(self) -> SearchAction | None:
        try:
            result = MergeMacroSearch(
                self.users,
                self._search_state(),
                max_nodes=max(1_000, self.exact_state_limit // 20),
                max_seconds=min(0.08, max(0.01, self.max_step_seconds / 4)),
                merge_value=self.merge_value,
            ).run_frontier()
        except (SearchLimitExceeded, RecursionError):
            return None
        if result.merges <= 0 or not result.actions:
            return None
        self.pending_actions = list(result.actions[1:])
        return result.actions[0]

    def _fallback_action(self) -> SearchAction | None:
        index = {name: idx for idx, name in enumerate(self.users)}
        if self.current is not None and self.states[self.current].can_merge():
            return SearchAction("merge", user=index[self.current])

        if self.current is not None:
            action = self._quick_exchange_action(index[self.current])
            if action is not None:
                return action

        candidates = [
            (state.can_merge(), sum(state.counts or ([0] * NUM_RUNE_TYPES)), state.merge_remaining, name)
            for name, state in self.states.items()
            if state.counts is not None and state.merge_remaining > 0
            and not (name == self.current and self._user_cache_empty_actual(state))
        ]
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return SearchAction("Peek", user=index[candidates[0][3]])

    def _quick_exchange_action(self, actor_idx: int) -> SearchAction | None:
        actor_name = self.users[actor_idx]
        actor = self.states[actor_name]
        if actor.counts is None:
            return None
        index = {name: idx for idx, name in enumerate(self.users)}
        best: tuple[int, int, str, int, int] | None = None
        for take_id in sorted(range(NUM_RUNE_TYPES), key=lambda rid: actor.counts[rid]):
            for give_id in sorted(range(NUM_RUNE_TYPES), key=lambda rid: -actor.counts[rid]):
                if give_id == take_id or actor.counts[give_id] <= 0:
                    continue
                for partner_name, partner in self.states.items():
                    if partner_name == actor_name or partner.counts is None:
                        continue
                    if partner.counts[take_id] <= 0:
                        continue
                    if take_id in partner.requested_runes:
                        continue
                    if actor_name not in partner.requesters and len(partner.requesters) >= MAX_REQUESTERS:
                        continue
                    after_actor = actor.counts[:]
                    after_partner = partner.counts[:]
                    after_actor[give_id] -= 1
                    after_actor[take_id] += 1
                    after_partner[take_id] -= 1
                    after_partner[give_id] += 1
                    actor_ready = int(actor.merge_remaining > 0 and all(v > 0 for v in after_actor))
                    partner_ready = int(partner.merge_remaining > 0 and all(v > 0 for v in after_partner))
                    immediate = actor_ready + partner_ready
                    if immediate <= 0:
                        continue
                    candidate = (immediate, actor_ready, partner_name, give_id, take_id)
                    if best is None or candidate > best:
                        best = candidate
        if best is None:
            return None
        _, _, partner_name, give_id, take_id = best
        return SearchAction(
            "exchange",
            from_user=actor_idx,
            to_user=index[partner_name],
            give_id=give_id,
            take_id=take_id,
        )

    def _search_state(self) -> SearchState:
        if self.current is None:
            raise RuntimeError("planning requires at least one Peek")
        index = {name: idx for idx, name in enumerate(self.users)}
        counts: list[tuple[int, int, int]] = []
        requested_rune_masks: list[int] = []
        requester_masks: list[int] = []
        remaining: list[int] = []

        for name in self.users:
            state = self.states[name]
            if state.counts is None:
                raise RuntimeError(f"{name!r} must be Peeked before planning")
            counts.append((state.counts[0], state.counts[1], state.counts[2]))
            requested_rune_masks.append(self._ids_to_mask(state.requested_runes))
            requester_mask = 0
            for requester in state.requesters:
                if requester in index:
                    requester_mask |= 1 << index[requester]
            requester_masks.append(requester_mask)
            remaining.append(state.merge_remaining)

        return SearchState(
            counts=tuple(counts),
            current=index[self.current],
            requested_rune_masks=tuple(requested_rune_masks),
            requester_masks=tuple(requester_masks),
            merge_remaining=tuple(remaining),
        )

    def _runtime_snapshot(self) -> tuple[Any, ...]:
        counts = tuple(
            tuple(self.states[name].counts or ([-1] * NUM_RUNE_TYPES))
            for name in self.users
        )
        requested = tuple(
            tuple(sorted(self.states[name].requested_runes))
            for name in self.users
        )
        requesters = tuple(
            tuple(sorted(self.states[name].requesters))
            for name in self.users
        )
        remaining = tuple(self.states[name].merge_remaining for name in self.users)
        return (self.total_merges, self.current, counts, requested, requesters, remaining)

    def _predicted_snapshot(self, action: SearchAction) -> tuple[Any, ...] | None:
        if action.kind == "merge":
            return None

        counts = {name: list(self.states[name].counts or ([-1] * NUM_RUNE_TYPES)) for name in self.users}
        requested = {name: set(self.states[name].requested_runes) for name in self.users}
        requesters = {name: set(self.states[name].requesters) for name in self.users}
        current = self.current

        if action.kind == "Peek":
            assert action.user is not None
            user = self.users[action.user]
            current = user
            requested[user].clear()
            requesters[user].clear()
        elif action.kind == "exchange":
            assert action.from_user is not None and action.to_user is not None
            assert action.give_id is not None and action.take_id is not None
            from_user = self.users[action.from_user]
            to_user = self.users[action.to_user]
            counts[from_user][action.give_id] -= 1
            counts[to_user][action.give_id] += 1
            counts[to_user][action.take_id] -= 1
            counts[from_user][action.take_id] += 1
            requested[to_user].add(action.take_id)
            requesters[to_user].add(from_user)
            current = from_user
        else:
            return None

        counts_tuple = tuple(tuple(counts[name]) for name in self.users)
        requested_tuple = tuple(tuple(sorted(requested[name])) for name in self.users)
        requesters_tuple = tuple(tuple(sorted(requesters[name])) for name in self.users)
        remaining = tuple(self.states[name].merge_remaining for name in self.users)
        return (self.total_merges, current, counts_tuple, requested_tuple, requesters_tuple, remaining)

    @staticmethod
    def _ids_to_mask(ids: set[int]) -> int:
        mask = 0
        for rune_id in ids:
            mask |= 1 << rune_id
        return mask

    @staticmethod
    def _user_cache_empty_actual(state: UserState) -> bool:
        return not state.requested_runes and not state.requesters

    def _execute_search_action(self, action: SearchAction) -> bool:
        before = len(self.trajectory)
        if action.kind == "Peek":
            assert action.user is not None
            self._peek(self.users[action.user])
            self.pending_actions.clear()
        elif action.kind == "merge":
            assert action.user is not None
            self._merge(self.users[action.user])
            self.pending_actions.clear()
        elif action.kind == "exchange":
            assert action.from_user is not None and action.to_user is not None
            assert action.give_id is not None and action.take_id is not None
            self._exchange(
                self.users[action.from_user],
                self.users[action.to_user],
                action.give_id,
                action.take_id,
            )
        else:
            raise RuntimeError(f"unknown action: {action!r}")
        return len(self.trajectory) > before

    def _record(self, op: Op) -> Sequence[int] | None:
        if len(self.trajectory) >= self.max_steps:
            raise RuntimeError(f"trajectory exceeded max_steps={self.max_steps}")
        self.trajectory.append(op)
        return self.execute(op)

    def _parse_counts(self, result: Sequence[int] | None, user: str) -> list[int]:
        if result is None:
            state = self.states[user]
            if state.counts is None:
                raise RuntimeError(f"{user!r} did not return counts")
            return state.counts
        counts = [int(value) for value in result[:NUM_RUNE_TYPES]]
        if len(counts) != NUM_RUNE_TYPES:
            raise RuntimeError(f"expected three counts for {user!r}, got {result!r}")
        return counts

    def _peek(self, user: str) -> list[int]:
        result = self._record({"op": "Peek", "user": user})
        counts = self._parse_counts(result, user)
        state = self.states[user]
        state.counts = counts
        state.logged = True
        state.peeks += 1
        self._reset_user_cache(state)
        self.current = user
        return counts

    def _merge(self, user: str) -> list[int]:
        if self.current != user:
            self._peek(user)
        state = self.states[user]
        if not state.can_merge():
            return state.counts or [0, 0, 0]

        result = self._record({"op": "merge", "user": user})
        counts = self._parse_counts(result, user)
        state.counts = counts
        state.merges += 1
        state.merge_remaining = max(0, state.merge_remaining - 1)
        self.total_merges += 1
        self._reset_user_cache(state)
        self.current = user
        return counts

    @staticmethod
    def _reset_user_cache(state: UserState) -> None:
        state.requested_runes.clear()
        state.requesters.clear()

    def _exchange(self, from_user: str, to_user: str, give_id: int, take_id: int) -> bool:
        if from_user == to_user or give_id == take_id:
            return False
        actor = self.states[from_user]
        partner = self.states[to_user]
        if self.current != from_user:
            self._peek(from_user)
        if not partner.logged:
            self._peek(to_user)
            self._peek(from_user)

        if actor.counts is None or partner.counts is None:
            return False
        if actor.counts[give_id] <= 0 or partner.counts[take_id] <= 0:
            return False
        if take_id in partner.requested_runes:
            return False
        if from_user not in partner.requesters and len(partner.requesters) >= MAX_REQUESTERS:
            return False

        op = {
            "op": "exchange",
            "from": from_user,
            "to": to_user,
            "give_id": self._rune_value(give_id),
            "take_id": self._rune_value(take_id),
        }
        self._record(op)
        actor.counts[give_id] -= 1
        partner.counts[give_id] += 1
        partner.counts[take_id] -= 1
        actor.counts[take_id] += 1
        partner.requested_runes.add(take_id)
        partner.requesters.add(from_user)
        return True

    def _rune_value(self, rune_id: int) -> str | int:
        if self.id_style == "int":
            return rune_id
        if self.id_style == "str_int":
            return str(rune_id)
        return RUNE_NAMES[rune_id]


class StaticBaginEnv:
    """Deterministic mock executor for tests."""

    def __init__(
        self,
        counts: Mapping[str, Sequence[int]],
        merge_rewards: Mapping[str, Sequence[int]] | None = None,
        merge_remaining: Sequence[int] | Mapping[str, int] | None = None,
    ) -> None:
        self.counts = {user: [int(value) for value in values[:NUM_RUNE_TYPES]] for user, values in counts.items()}
        self.merge_rewards = {
            user: [int(rune_id) for rune_id in rewards]
            for user, rewards in (merge_rewards or {}).items()
        }
        self.merge_remaining = self._normalize_remaining(merge_remaining)
        self.current: str | None = None
        self.logged: set[str] = set()
        self.requested_runes = {user: set() for user in self.counts}
        self.requesters = {user: set() for user in self.counts}
        self.merge_count = {user: 0 for user in self.counts}
        self.reward_used = {user: 0 for user in self.counts}

    def _normalize_remaining(
        self,
        merge_remaining: Sequence[int] | Mapping[str, int] | None,
    ) -> dict[str, int]:
        users = list(self.counts)
        if merge_remaining is None:
            return {user: DEFAULT_MERGE_QUOTA for user in users}
        if isinstance(merge_remaining, Mapping):
            return {user: {user: max(0, int(merge_remaining.get(user, DEFAULT_MERGE_QUOTA))) for user in users}}
        values = [max(0, int(value)) for value in merge_remaining]
        if len(values) != len(users):
            raise ValueError("merge_remaining must have the same length as users")
        return dict(zip(users, values))

    def __call__(self, op: Op) -> Sequence[int] | None:
        kind = op.get("op")
        if kind == "Peek":
            user = str(op["user"])
            self._ensure_user(user)
            self.current = user
            self.logged.add(user)
            self._reset_user_cache(user)
            return self.counts[user][:]

        if kind == "merge":
            user = str(op["user"])
            self._ensure_user(user)
            if self.current != user:
                raise RuntimeError("merge user must be current login")
            if self.merge_remaining[user] <= 0:
                raise RuntimeError("merge quota exhausted")
            if any(value <= 0 for value in self.counts[user]):
                raise RuntimeError("merge requires one rune of each type")
            for rune_id in range(NUM_RUNE_TYPES):
                self.counts[user][rune_id] -= 1
            reward_index = self.reward_used[user]
            self.merge_remaining[user] -= 1
            self.reward_used[user] += 1
            rewards = self.merge_rewards.get(user, [])
            if reward_index < len(rewards):
                self.counts[user][rewards[reward_index]] += 3
            self.merge_count[user] += 1
            self._reset_user_cache(user)
            return self.counts[user][:]

        if kind == "exchange":
            from_user = str(op["from"])
            to_user = str(op["to"])
            give_id = self._parse_rune(op["give_id"])
            take_id = self._parse_rune(op["take_id"])
            self._ensure_user(from_user)
            self._ensure_user(to_user)
            if self.current != from_user:
                raise RuntimeError("exchange from user must be current login")
            if to_user not in self.logged:
                raise RuntimeError("exchange target must have been logged")
            if self.counts[from_user][give_id] <= 0 or self.counts[to_user][take_id] <= 0:
                raise RuntimeError("cannot exchange without positive runes")
            if take_id in self.requested_runes[to_user]:
                raise RuntimeError("this rune was already requested from target since last Peek")
            if from_user not in self.requesters[to_user] and len(self.requesters[to_user]) >= MAX_REQUESTERS:
                raise RuntimeError("target has already been requested by three users")

            self.counts[from_user][give_id] -= 1
            self.counts[to_user][give_id] += 1
            self.counts[to_user][take_id] -= 1
            self.counts[from_user][take_id] += 1
            self.requested_runes[to_user].add(take_id)
            self.requesters[to_user].add(from_user)
            return None

        raise RuntimeError(f"unknown op: {op!r}")

    def _ensure_user(self, user: str) -> None:
        if user not in self.counts:
            self.counts[user] = [0, 0, 0]
            self.merge_remaining[user] = DEFAULT_MERGE_QUOTA
            self.requested_runes[user] = set()
            self.requesters[user] = set()
            self.merge_count[user] = 0
            self.reward_used[user] = 0

    def _reset_user_cache(self, user: str) -> None:
        self.requested_runes[user].clear()
        self.requesters[user].clear()

    @staticmethod
    def _parse_rune(value: Any) -> int:
        if isinstance(value, int):
            return value
        text = str(value)
        if text in RUNE_ID:
            return RUNE_ID[text]
        return int(text)


def peek(user: str) -> Sequence[int]:
    """Real Peek interface: login/switch to user and return [0, 1, 2] counts."""

    from test_merge import peek as peek_impl
    return peek_impl(user)


def exchange(from_user: str, to_user: str, give_id: str | int, take_id: str | int) -> None:
    """Real exchange interface.

    ``from_user`` is the current login. It gives ``give_id`` to ``to_user`` and
    asks ``to_user`` for ``take_id``.
    """

    from test_merge import exchange as exchange_impl
    return exchange_impl(from_user, to_user, give_id, take_id)


def merge(user: str) -> Sequence[int]:
    """Real merge interface. Return the free post-merge Peek result."""

    from test_merge import merge as merge_impl
    return merge_impl(user)


def interface_execute(op: Op) -> Sequence[int] | None:
    kind = op.get("op")
    if kind == "Peek":
        return peek(str(op["user"]))
    if kind == "merge":
        return merge(str(op["user"]))
    if kind == "exchange":
        exchange(str(op["from"]), str(op["to"]), op["give_id"], op["take_id"])
        return None
    raise RuntimeError(f"unknown op: {op!r}")


def solve(
    users: Sequence[str],
    execute: Executor | None = None,
    *,
    initial_counts: Mapping[str, Sequence[int]] | None = None,
    merge_rewards: Mapping[str, Sequence[int]] | None = None,
    merge_remaining: Sequence[int] | Mapping[str, int] | None = None,
    id_style: str = "name",
    max_steps: int = 10_000,
    exact_state_limit: int = 80_000,
    max_step_seconds: float = 0.8,
    merge_value: int = 10,
) -> list[Op]:
    """Run the dynamic planner.

    ``merge_remaining`` is a list aligned with ``users`` or a mapping keyed by
    user name. Default is 3 for every user. ``merge_value`` is the score gained
    by one merge.  The default is 10 to prefer more badges; pass 5 if you want
    the strict net score from the original statement.
    """

    if execute is None:
        if initial_counts is None:
            execute = interface_execute
        else:
            execute = StaticBaginEnv(initial_counts, merge_rewards, merge_remaining)

    return BaginPlanner(
        users,
        execute,
        merge_remaining=merge_remaining,
        id_style=id_style,
        max_steps=max_steps,
        exact_state_limit=exact_state_limit,
        max_step_seconds=max_step_seconds,
        merge_value=merge_value,
    ).run()


build_trajectory = solve
plan = solve
run = solve


__all__ = [
    "RUNE_NAMES",
    "RUNE_ID",
    "BaginPlanner",
    "StaticBaginEnv",
    "peek",
    "exchange",
    "merge",
    "interface_execute",
    "solve",
    "build_trajectory",
    "plan",
    "run",
]
