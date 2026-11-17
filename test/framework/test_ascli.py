"""CLI flows must preflight completely, preserve transitions and never replay a submission."""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from AutoScriptor.cli import AutomationService, ExecutionBusyError, parse_script, transform_script
from AutoScriptor.cli import adapter, core


class ScriptContractTests(unittest.TestCase):
    def test_until_and_complete_flow_generate_natural_single_line_calls(self):
        source = 'ascli click -B 332 33 22 44 --until -T "Done" --timeout 20\nascli wait-disappear -T "Loading" --timeout 10'
        generated = transform_script(source)
        self.assertIn('click(B(332, 33, 22, 44), timeout=20.0, until=lambda: ui_T(T(\'Done\')))', generated)
        self.assertIn("wait_for_disappear(T('Loading'), timeout=10.0)", generated)
        for statement in ast.parse(generated).body:
            self.assertEqual(statement.lineno, statement.end_lineno)

    def test_targets_are_inline_and_frame_references_are_checked(self):
        source = 'screenshot before.png --save-as before\nlocate -T "Ready" --box 10 20 200 50 --frame before'
        generated = transform_script(source)
        self.assertIn("before = screenshot('before.png')", generated)
        self.assertIn("locate(T('Ready', box=Box(10, 20, 200, 50)), screenshot=before)", generated)
        with self.assertRaisesRegex(ValueError, 'line 1'):
            parse_script('locate -T Ready --frame missing')

    def test_shell_syntax_unknown_options_and_invalid_numbers_fail_before_execution(self):
        for source in ('click -B 1 2; sleep 3', 'click -B 1 2 --typo 3', 'sleep nan', 'click -B 1 2 -1 5', 'wait-appear -T Ready --timeout -1', 'input "$(whoami)"'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_script(source)

    def test_quotes_comments_and_windows_paths_are_not_shell_expanded(self):
        plan = parse_script('# note\r\ninput "two words # literal"\r\nadb push "D:\\files\\report.txt" /sdcard/report.txt')
        self.assertEqual(plan.commands[0].arguments, ('two words # literal',))
        self.assertEqual(plan.commands[1].arguments[0], 'D:\\files\\report.txt')

    def test_shell_argv_roundtrip_preserves_quotes_backslashes_and_empty_text(self):
        for value in ('', 'a "quoted" value', "single ' quote", 'D:\\folder with spaces\\', '# literal', 'a; b'):
            source = ' '.join(core._quote_token(token) for token in ['input', value])
            self.assertEqual(parse_script(source).commands[0].arguments, (value,))

    def test_inline_target_grouping_and_sequence_preserve_different_semantics(self):
        self.assertIn("click((T('Yes'), T('OK'),))", transform_script('click --any -T Yes -T OK'))
        self.assertIn("locate([T('Yes'), T('OK')])", transform_script('locate --all -T Yes -T OK'))
        self.assertIn("seq_click([T('Yes'), T('OK')])", transform_script('seq-click -T Yes --next -T OK'))
        for source in ('click --all -T Yes -T OK', 'click -T Yes --until', 'wait-appear -B 1 2', 'screenshot ../../result.png', 'adb pull /sdcard/a C:\\a'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_script(source)

    def test_cli_import_and_help_do_not_import_config_ocr_or_devices(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', "import sys; import AutoScriptor.cli as cli; assert callable(cli.AutomationService); assert 'AutoScriptor.utils.app_config' not in sys.modules; assert 'cv2' not in sys.modules; assert 'AutoScriptor.core.api' not in sys.modules; cli.main(['help', 'click'])"], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('until', result.stdout)

    def test_command_catalogue_parameters_match_real_functions_without_importing_them(self):
        root = Path(__file__).resolve().parents[2]
        definitions = {}
        for module, filename in (('AutoScriptor', 'AutoScriptor/core/api.py'), ('AutoScriptor.cli.adapter', 'AutoScriptor/cli/adapter.py')):
            tree = ast.parse((root / filename).read_text(encoding='utf-8'))
            definitions[module] = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name, spec in adapter.COMMANDS.items():
            if spec.function == 'sleep':
                continue  # This public export is the cancellable_sleep alias.
            with self.subTest(command=name):
                function = definitions[spec.module][spec.function]
                parameters = {argument.arg for argument in [*function.args.args, *function.args.kwonlyargs]}
                self.assertTrue({adapter.OPTIONS[option][0] for option in spec.options} <= parameters)
                if spec.frame_parameter:
                    self.assertIn(spec.frame_parameter, parameters)

    def test_exported_wheel_contains_the_console_entrypoint(self):
        from scripts import build_wheels
        framework, _game = build_wheels.build_specs('0.0.0')
        entries = build_wheels.collect_archive_entries(framework, '0.0.0')
        self.assertIn(b'ascli = AutoScriptor.cli:main', entries['autoscriptor-0.0.0.dist-info/entry_points.txt'])
        self.assertIn('AutoScriptor/cli/core.py', entries)


class RegisteredTaskCommandTests(unittest.TestCase):
    def test_debug_override_can_be_removed_without_replacing_other_task_state(self):
        configuration = {'tasks': {'group': {'task': {'on': False, 'debug': True, 'next_exec_time': 123, 'params': {'amount': 10}}}}}
        client = Mock()
        client.request.side_effect = [{'runtime': {'busy': False}}, configuration, configuration]
        result = core._task_command(client, ['debug', 'group/task', 'inherit'])
        self.assertTrue(result['previous_debug'])
        saved = client.request.call_args.args[1]['tasks']['group']['task']
        self.assertNotIn('debug', saved)
        self.assertEqual(saved, {'on': False, 'next_exec_time': 123, 'params': {'amount': 10}})

    def test_busy_debug_change_never_reads_or_saves_configuration(self):
        client = Mock()
        client.request.return_value = {'runtime': {'busy': True}}
        with self.assertRaises(ExecutionBusyError):
            core._task_command(client, ['debug', 'group/task', 'on'])
        client.request.assert_called_once_with('run/status')

    def test_task_show_rejects_unknown_paths_and_groups(self):
        client = Mock()
        client.request.return_value = {'tasks': {'group': {'task': {'on': False}}}}
        for task_path in ('group', 'group/missing', ''):
            with self.subTest(task_path=task_path), self.assertRaises(ValueError):
                core._task_command(client, ['show', task_path])


class FlowAdapter:
    def __init__(self):
        self.calls = []
        self.ready = False
        self.prepared = 0
        self.finished = []
        self.fail_click = False
        self.block = None
        self.entered = threading.Event()

    def prepare(self, plan, directory, timeout):
        self.prepared += 1

    def execute(self, command, values):
        self.calls.append(command.name)
        self.entered.set()
        if self.block is not None:
            self.block.wait(2)
        if command.name == 'click':
            if self.fail_click:
                raise RuntimeError('transition failed')
            self.ready = True
        if command.name == 'wait-appear' and not self.ready:
            raise TimeoutError('destination not reached')
        return True

    def finish(self, error):
        self.finished.append(error)
        return {'recording': {'complete': True}, 'warnings': []}


class FlowExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.gate = threading.Lock()
        self.adapter = FlowAdapter()
        self.cancelled = threading.Event()
        self.service = AutomationService(
            acquire_execution=lambda: self.gate.acquire(blocking=False),
            release_execution=self.gate.release,
            request_cancel=self.cancelled.set,
            reset_cancel=self.cancelled.clear,
            adapter_factory=lambda: self.adapter,
            logs_root=Path(self.temporary.name),
        )
        self.addCleanup(self.service.shutdown)

    def test_whole_flow_and_duplicate_submission_share_one_run(self):
        source = 'click -B 1 2\nwait-appear -T Ready'
        result = self.service.submit(source, request_id='a' * 32)
        final = self.service.wait(result['run_id'], timeout=3)
        self.assertEqual(final['state'], 'succeeded')
        self.assertEqual(self.adapter.calls, ['click', 'wait-appear'])
        self.assertFalse(self.gate.locked())
        self.assertEqual(self.service.submit(source, request_id='a' * 32)['run_id'], result['run_id'])
        self.assertEqual(self.adapter.prepared, 1)
        self.assertTrue((Path(final['directory']) / 'flow.py').is_file())

    def test_failure_stops_later_steps_and_keeps_error_and_result(self):
        self.adapter.fail_click = True
        run = self.service.submit('click -B 1 2\nwait-appear -T Ready')
        final = self.service.wait(run['run_id'], timeout=3)
        self.assertEqual(final['state'], 'failed')
        self.assertEqual(final['failed_line'], 1)
        self.assertEqual(self.adapter.calls, ['click'])
        self.assertEqual(len(self.adapter.finished), 1)
        self.assertTrue((Path(final['directory']) / 'error.log').is_file())
        self.assertFalse(self.gate.locked())

    def test_invalid_last_line_has_no_side_effects(self):
        with self.assertRaises(ValueError):
            self.service.submit('click -B 1 2\nnot-a-command')
        self.assertEqual(self.adapter.prepared, 0)
        self.assertFalse(self.gate.locked())

    def test_cancel_does_not_release_gate_while_worker_is_still_blocked(self):
        self.adapter.block = threading.Event()
        run = self.service.submit('click -B 1 2\nwait-appear -T Ready')
        self.assertTrue(self.adapter.entered.wait(2))
        self.service.stop(run['run_id'])
        self.assertTrue(self.gate.locked())
        self.assertTrue(self.service.status()['stopping'])
        self.adapter.block.set()
        final = self.service.wait(run['run_id'], timeout=3)
        self.assertEqual(final['state'], 'cancelled')
        self.assertNotIn('wait-appear', self.adapter.calls)
        self.assertFalse(self.gate.locked())

    def test_cancellation_takes_precedence_over_a_late_adapter_failure(self):
        self.adapter.block = threading.Event()
        self.adapter.fail_click = True
        run = self.service.submit('click -B 1 2\nwait-appear -T Ready')
        try:
            self.assertTrue(self.adapter.entered.wait(2))
            self.assertEqual(self.service.stop(run['run_id'])['state'], 'stopping')
            self.assertTrue(self.gate.locked())
        finally:
            self.adapter.block.set()

        result = self.service.wait(run['run_id'], timeout=3)
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(result['steps'][-1]['state'], 'cancelled')
        self.assertFalse(result['verified'])
        self.assertNotIn('wait-appear', self.adapter.calls)
        self.assertFalse(self.gate.locked())

    def test_cancellation_during_cleanup_overrides_success_warnings_and_errors(self):
        for cleanup_outcome in ('success', 'warning', 'error'):
            with self.subTest(cleanup_outcome=cleanup_outcome):
                cleanup_started = threading.Event()
                cleanup_released = threading.Event()

                def finish(error):
                    cleanup_started.set()
                    if not cleanup_released.wait(3):
                        raise TimeoutError('Test cleanup was not released')
                    if cleanup_outcome == 'error':
                        raise RuntimeError('Cleanup failed after cancellation')
                    return {'warnings': ['video missing'] if cleanup_outcome == 'warning' else []}

                self.adapter.finish = Mock(side_effect=finish)
                run = self.service.submit('click -B 1 2\nwait-appear -T Ready')
                try:
                    self.assertTrue(cleanup_started.wait(2))
                    self.assertEqual(self.service.stop(run['run_id'])['state'], 'stopping')
                    self.assertTrue(self.gate.locked())
                    self.assertTrue(self.service.status()['stopping'])
                finally:
                    cleanup_released.set()

                result = self.service.wait(run['run_id'], timeout=3)
                self.assertEqual(result['state'], 'cancelled')
                self.assertFalse(result['verified'])
                self.assertFalse(self.gate.locked())
                self.assertFalse(self.cancelled.is_set())

    def test_busy_runtime_rejects_without_creating_a_second_controller(self):
        self.gate.acquire()
        try:
            with self.assertRaises(ExecutionBusyError):
                self.service.submit('click -B 1 2')
        finally:
            self.gate.release()
        self.assertEqual(self.adapter.prepared, 0)

    def test_run_timeout_is_distinct_from_user_cancellation_and_waits_for_exit(self):
        self.adapter.block = threading.Event()
        run = self.service.submit('click -B 1 2\nwait-appear -T Ready', timeout=0.05)
        self.assertTrue(self.cancelled.wait(2))
        self.assertTrue(self.gate.locked())
        self.adapter.block.set()
        result = self.service.wait(run['run_id'], timeout=3)
        self.assertEqual(result['state'], 'timed_out')
        self.assertFalse(self.gate.locked())

    def test_recorder_start_failure_never_executes_actions_but_finalizes_evidence(self):
        self.adapter.prepare = Mock(side_effect=RuntimeError('Recorder unavailable'))
        run = self.service.submit('click -B 1 2\nwait-appear -T Ready')
        result = self.service.wait(run['run_id'], timeout=3)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(len(self.adapter.finished), 1)
        self.assertFalse(self.gate.locked())

    def test_evidence_failure_does_not_masquerade_as_a_successful_run(self):
        self.adapter.finish = Mock(return_value={'warnings': ['video missing']})
        run = self.service.submit('click -B 1 2\nwait-appear -T Ready')
        result = self.service.wait(run['run_id'], timeout=3)
        self.assertEqual(result['state'], 'failed')
        self.assertIn('evidence', result['error'])

    def test_a_previous_run_id_cannot_be_used_for_a_different_flow(self):
        run = self.service.submit('click -B 1 2')
        self.service.wait(run['run_id'], timeout=3)
        with self.assertRaises(ValueError):
            self.service.submit('click -B 3 4', request_id=run['run_id'])

    def test_raw_adb_requires_explicit_authorization_before_acquiring_gate(self):
        with self.assertRaisesRegex(ValueError, 'allow-unsafe'):
            self.service.submit('adb shell -- getprop sys.boot_completed')
        self.assertEqual(self.adapter.prepared, 0)
        self.assertFalse(self.gate.locked())

    def test_artifact_paths_cannot_escape_run_directory(self):
        run = self.service.submit('sleep 0')
        self.service.wait(run['run_id'], timeout=3)
        with self.assertRaises(ValueError):
            self.service.artifact_path(run['run_id'], '../private.json')

    def test_command_false_does_not_verify_an_until_flow(self):
        self.adapter.execute = Mock(return_value=False)
        run = self.service.submit('click -T Optional --if-exist --until -T Ready')
        result = self.service.wait(run['run_id'], timeout=3)
        self.assertFalse(result['verified'])


if __name__ == '__main__':
    unittest.main()
