from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TaskPersistenceRaceContractTests(unittest.TestCase):
    def test_task_and_ordering_writes_share_one_frontend_commit_queue(self):
        frontend = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")

        persist_tasks_start = frontend.index("async function persistTasks")
        persist_tasks_end = frontend.index("async function saveTaskFromDialog", persist_tasks_start)
        persist_tasks = frontend[persist_tasks_start:persist_tasks_end]

        save_ordering_start = frontend.index("async function saveTaskOrdering")
        save_ordering_end = frontend.index("function orderedTaskPathsForSoftOrder", save_ordering_start)
        save_ordering = frontend[save_ordering_start:save_ordering_end]

        self.assertIn("function queueTaskPersistenceOperation", frontend)
        self.assertIn("queueTaskPersistenceOperation", persist_tasks)
        self.assertIn("queueTaskPersistenceOperation", save_ordering)

    def test_ordering_response_cannot_replace_unsaved_task_draft(self):
        frontend = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")
        backend = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")

        save_ordering_start = frontend.index("async function saveTaskOrdering")
        save_ordering_end = frontend.index("function orderedTaskPathsForSoftOrder", save_ordering_start)
        save_ordering = frontend[save_ordering_start:save_ordering_end]

        self.assertIn("function applyTaskOrderingPayload", frontend)
        self.assertIn("applyTaskOrderingPayload(data)", save_ordering)
        self.assertNotIn("applyPublicConfigPayload(data)", save_ordering)

        route_start = backend.index('@app.post("/api/task-ordering")')
        route_end = backend.index('@app.post("/api/task-ordering/layout")', route_start)
        route = backend[route_start:route_end]

        self.assertIn("_make_task_ordering_response_unlocked()", route)
        self.assertNotIn("_make_public_config_unlocked()", route)

    def test_runtime_poll_compares_with_current_version_after_response(self):
        frontend = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")

        snapshot_start = frontend.index("async function fetchRuntimeSnapshot")
        snapshot_end = frontend.index("function scheduleRuntimeRefreshAfterStop", snapshot_start)
        snapshot = frontend[snapshot_start:snapshot_end]

        self.assertNotIn("const publicVersion", snapshot)
        self.assertIn("await waitForTaskPersistenceOperations()", snapshot)
        self.assertIn("const currentConfigVersion = Number(configData.config_version || 0)", snapshot)
        self.assertNotIn("nextVersion !== currentConfigVersion", snapshot)
        self.assertIn("nextVersion > currentConfigVersion", snapshot)


if __name__ == "__main__":
    unittest.main()
