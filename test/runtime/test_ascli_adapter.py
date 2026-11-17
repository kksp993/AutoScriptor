"""Exercise real adapters/recorder contracts in a temporary-data child process."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class AscliAdapterIsolationTests(unittest.TestCase):
    def test_runtime_adapter_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, AUTOSCRIPTOR_DATA_DIR=directory, AUTOSCRIPTOR_TESTING='1')
            result = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve())], cwd=str(Path(__file__).resolve().parents[2]), env=environment, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def run_isolated_cases():
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    import numpy as np

    import AutoScriptor.core.api as api
    from AutoScriptor.cli import AutomationService, parse_script
    from AutoScriptor.cli import adapter
    from AutoScriptor.core import runtime_context
    from AutoScriptor.logging import task_video_recorder as recording
    from AutoScriptor.logging import tracer
    from AutoScriptor.utils.paths import get_logs_root

    class AdapterCases(unittest.TestCase):
        def setUp(self):
            self.stack = ExitStack()
            self.addCleanup(self.stack.close)
            self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            self.control = SimpleNamespace(screenshot=Mock(return_value=self.frame), release_all_keys=Mock(), release_all_fingers=Mock())
            runtime = runtime_context.RuntimeContext()
            runtime.mixctrl, runtime.mumu = self.control, SimpleNamespace()
            self.stack.enter_context(patch.object(runtime_context, 'runtime_ctx', runtime))
            self.stack.enter_context(patch.object(api, 'mixctrl', self.control))
            self.stack.enter_context(patch.object(api, 'mumu', runtime.mumu))
            self.refresh = self.stack.enter_context(patch.object(runtime, '_refresh_device_session_locked', side_effect=AssertionError('A warm flow must not initialize again')))

        def test_successful_device_flows_reuse_session_and_keep_recordings(self):
            recorders = []

            def recorder_factory(*arguments, **options):
                recorder = Mock(is_recording=True)
                recorder.recording_status.return_value = {'complete': True}
                video = get_logs_root() / f'video-{len(recorders)}'
                video.mkdir()
                (video / 'segment.mp4').write_bytes(b'fixture')
                recorder.stop.return_value = video
                recorders.append(recorder)
                return recorder

            self.stack.enter_context(patch.object(recording, 'TaskVideoRecorder', side_effect=recorder_factory))
            service = AutomationService(acquire_execution=lambda: True, release_execution=lambda: None, request_cancel=lambda: None, reset_cancel=lambda: None, logs_root=get_logs_root())
            self.addCleanup(service.shutdown)
            for _attempt in range(2):
                run = service.submit('screenshot frame.png')
                result = service.wait(run['run_id'], timeout=10)
                self.assertEqual(result['state'], 'succeeded', result)
                self.assertFalse(result['verified'])
                self.assertTrue((Path(result['directory']) / 'artifacts/frame.png').is_file())
                self.assertTrue((Path(result['directory']) / 'video/segment.mp4').is_file())
            self.refresh.assert_not_called()
            for recorder in recorders:
                recorder.stop.assert_called_once_with(keep=True)
            self.assertFalse(tracer.is_run_capture_enabled())

        def test_fixed_frame_absence_uses_exact_frame_without_new_capture(self):
            command = parse_script('screenshot frame.png --save-as frame\nabsent -T Ready --frame frame').commands[1]
            with patch.object(api, 'locate', return_value=None) as locate:
                self.assertTrue(adapter.execute_command(command, {'frame': self.frame}))
                self.assertIs(locate.call_args.kwargs['screenshot'], self.frame)
            self.control.screenshot.assert_not_called()

        def test_adb_error_is_not_a_successful_return(self):
            from AutoScriptor.control.MumuAdaptor.api.adb import direct
            failed = SimpleNamespace(returncode=1, stdout='', stderr='device offline')
            with patch.object(direct, 'run_adb', return_value=failed) as execute:
                with self.assertRaisesRegex(RuntimeError, 'device offline'):
                    adapter.adb_shell('input', 'text', 'a; b')
            self.assertEqual(execute.call_args.args[0], ['shell', "input text 'a; b'"])

        def test_generated_python_and_adapter_preserve_the_same_stateful_flow(self):
            import AutoScriptor
            from AutoScriptor.cli import transform_script
            page = {'name': 'home'}
            observed = []

            def click(target, **options):
                observed.append(('click', target.get_source()))
                if target.get_source() == 'Settings' and page['name'] == 'home':
                    page['name'] = 'settings'
                elif target.get_source() == 'Close' and page['name'] == 'settings':
                    page['name'] = 'home'
                else:
                    raise RuntimeError('Invalid page transition')
                return True

            def wait_for_appear(target, **options):
                observed.append(('wait', target.get_source()))
                if page['name'] != target.get_source():
                    raise TimeoutError('Expected page was never reached')
                return True

            source = 'wait-appear -T home\nclick -T Settings\nwait-appear -T settings\nclick -T Close\nwait-appear -T home'
            with patch.object(AutoScriptor, 'click', click), patch.object(AutoScriptor, 'wait_for_appear', wait_for_appear):
                for command in parse_script(source).commands:
                    adapter.execute_command(command, {})
                expected = list(observed)
                observed.clear()
                exec(compile(transform_script(source), '<generated-flow>', 'exec'), {})
            self.assertEqual(observed, expected)
            self.assertEqual(page['name'], 'home')

        def test_full_retention_never_discards_earlier_segments(self):
            recorder = recording.TaskVideoRecorder('test', keep_segments=2, retain_all=True)
            recorder.segments = ['first.mp4', 'second.mp4', 'third.mp4']
            with patch.object(recorder, '_adb') as execute:
                recorder._trim_device_segments()
            execute.assert_not_called()
            self.assertEqual(len(recorder.segments), 3)
            recorder._segment_index = 2
            self.assertFalse(recorder._start_segment())
            self.assertIn('budget', recorder.errors[0])

        def test_missing_video_is_explicitly_incomplete(self):
            recorder = recording.TaskVideoRecorder('test', retain_all=True)
            recorder.segments = ['missing.mp4']
            with patch.object(recorder, '_pull_one', return_value=False):
                self.assertIsNone(recorder._pull_segments())
            recorder._stopped.set()
            self.assertFalse(recorder.recording_status()['complete'])
            self.assertIn('Missing', recorder.recording_status()['errors'][0])

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AdapterCases))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(run_isolated_cases())
