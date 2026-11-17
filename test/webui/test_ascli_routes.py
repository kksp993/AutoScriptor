"""CLI platform binding: permission/gate failures never start device work."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from AutoScriptor.cli import AutomationService
from backend.webui.api_response import api_error
from backend.webui.routes.ascli import create_router
from test.framework.test_ascli import FlowAdapter


class AscliRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.gate = threading.Lock()
        self.adapter = FlowAdapter()
        self.service = AutomationService(acquire_execution=lambda: self.gate.acquire(False), release_execution=self.gate.release, request_cancel=lambda: None, reset_cancel=lambda: None, logs_root=Path(self.directory.name), adapter_factory=lambda: self.adapter)
        self.addCleanup(self.service.shutdown)
        self.unlock = Mock(return_value=None)
        self.router = create_router(self.service, require_unlock=self.unlock, identity=lambda: 'test-character')

    def invoke(self, path, method='GET', payload=None, **parameters):
        route = next(route for route in self.router.routes if route.path == '/api/ascli' + path and method in route.methods)
        if payload is not None:
            request = Mock(body=AsyncMock(return_value=json.dumps(payload).encode('utf-8')))
            parameters['request'] = request
        return asyncio.run(route.endpoint(**parameters))

    def test_credential_lock_blocks_even_a_valid_flow(self):
        self.unlock.return_value = api_error(403, 'locked', code='credential_locked')
        response = self.invoke('/runs', 'POST', {'source': 'click -B 1 2'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.adapter.calls, [])
        self.assertFalse(self.gate.locked())

    def test_compile_and_status_are_device_free(self):
        response = self.invoke('/transform', 'POST', {'source': 'click -B 1 2\nwait-appear -T Ready'})
        self.assertTrue(response['ok'])
        self.assertIn('wait_for_appear', response['code'])
        self.assertFalse(self.invoke('/status')['busy'])
        self.assertEqual(self.adapter.prepared, 0)
        self.unlock.assert_not_called()

    def test_invalid_and_busy_submissions_do_not_execute(self):
        response = self.invoke('/runs', 'POST', {'source': 'click -B 1 2\nunknown-command'})
        self.assertEqual(response.status_code, 400)
        self.gate.acquire()
        try:
            response = self.invoke('/runs', 'POST', {'source': 'click -B 1 2'})
            self.assertEqual(response.status_code, 409)
        finally:
            self.gate.release()
        self.assertEqual(self.adapter.prepared, 0)

    def test_full_submission_result_log_and_artifact_endpoints(self):
        response = self.invoke('/runs', 'POST', {'source': 'click -B 1 2\nwait-appear -T Ready', 'request_id': 'b' * 32})
        self.service.wait(response['run_id'], timeout=3)
        final = self.invoke('/runs/{run_id}', run_id=response['run_id'])
        self.assertEqual(final['state'], 'succeeded')
        self.assertTrue(final['verified'])
        logs = self.invoke('/runs/{run_id}/logs', run_id=response['run_id'])
        self.assertIn('wait-appear', logs['text'])
        artifacts = self.invoke('/runs/{run_id}/artifacts', run_id=response['run_id'])
        self.assertIn('flow.py', {item['name'] for item in artifacts['files']})
        escape = self.invoke('/runs/{run_id}/file', run_id=response['run_id'], name='../private.json')
        self.assertEqual(escape.status_code, 400)

    def test_unknown_fields_and_nonexistent_runs_are_explicit_errors(self):
        response = self.invoke('/runs', 'POST', {'source': 'sleep 0', 'force_login': True})
        self.assertEqual(response.status_code, 400)
        response = self.invoke('/runs/{run_id}', run_id='c' * 32)
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
