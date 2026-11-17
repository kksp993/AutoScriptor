"""Persistent flow execution and a lightweight HTTP client/console entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .adapter import COMMANDS, ExecutionAdapter, capabilities, encode_result
from .transform import parse_command, parse_script, transform_script, transform_with_map


TERMINAL_STATES = frozenset({'succeeded', 'failed', 'cancelled', 'timed_out', 'interrupted'})


class ExecutionBusyError(RuntimeError):
    """Another participant owns the platform execution gate."""


class FlowCancelled(Exception):
    pass


def _write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _run_id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('Run/request ID must be 32 lowercase hexadecimal characters')
    return value


class AutomationService:
    """Instantiate once in a host; inject that host's gate and cancellation hooks.

    A new adapter owns evidence per run, never a second device session. No work
    is launched by construction, status polling or source transformation.
    """
    def __init__(self, *, acquire_execution, release_execution, request_cancel, reset_cancel, adapter_factory=ExecutionAdapter, logs_root=None):
        self.acquire_execution = acquire_execution
        self.release_execution = release_execution
        self.request_cancel = request_cancel
        self.reset_cancel = reset_cancel
        self.adapter_factory = adapter_factory
        self._logs_root = Path(logs_root) if logs_root is not None else None
        self._lock = threading.RLock()
        self._active = None
        self._thread = None
        self._cancel = threading.Event()
        self._timed_out = False
        self._closing = False

    @property
    def root(self):
        if self._logs_root is None:
            from AutoScriptor.utils.paths import get_logs_root
            self._logs_root = get_logs_root()
        return self._logs_root / 'ascli'

    def status(self):
        with self._lock:
            return {'running': self._active is not None, 'busy': self._active is not None, 'stopping': self._active is not None and self._cancel.is_set(), 'run_id': self._active}

    def get_run(self, run_id):
        directory = self.root / _run_id(run_id)
        with self._lock:
            result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
            if result['state'] not in TERMINAL_STATES and run_id != self._active:
                result.update(state='interrupted', error='Backend stopped before this run finalized; it will not be replayed')
            return result

    def _publish(self, directory, result):
        # Readers and replace() share the lock, including on Windows.
        with self._lock:
            _write_json(directory / 'result.json', result)

    def submit(self, source, *, timeout=300, request_id=None, allow_unsafe=False, identity=''):
        plan = parse_script(source)
        timeout = float(timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError('Flow timeout must be within (0, 3600] seconds')
        if not isinstance(allow_unsafe, bool):
            raise ValueError('allow_unsafe must be a boolean')
        if plan.requires_unsafe and not allow_unsafe:
            raise ValueError('Raw ADB shell/push requires explicit --allow-unsafe authorization')
        run_id = _run_id(request_id) if request_id is not None else uuid.uuid4().hex
        fingerprint = hashlib.sha256(json.dumps([source, timeout, allow_unsafe, identity], ensure_ascii=False).encode('utf-8')).hexdigest()
        directory = self.root / run_id
        with self._lock:
            if (directory / 'result.json').is_file():
                previous = self.get_run(run_id)
                if previous['fingerprint'] != fingerprint:
                    raise ValueError('Request ID already belongs to a different flow, options or identity')
                return previous
            if self._closing:
                raise ExecutionBusyError('Automation service is shutting down')
            if self._active is not None or not self.acquire_execution():
                raise ExecutionBusyError('Runtime is occupied; the flow was not queued or executed')
            try:
                self.reset_cancel()
                self._cancel.clear()
                self._timed_out = False
                directory.mkdir(parents=True, exist_ok=False)
                generated, line_map = transform_with_map(source)
                (directory / 'flow.as').write_text(source, encoding='utf-8')
                (directory / 'flow.py').write_text(generated, encoding='utf-8')
                _write_json(directory / 'source_map.json', line_map)
                result = {'run_id': run_id, 'fingerprint': fingerprint, 'state': 'accepted', 'directory': str(directory), 'steps': [], 'timeout': timeout, 'created_at': time.time(), 'verified': False}
                _write_json(directory / 'result.json', result)
                self._active = run_id
                self._thread = threading.Thread(target=self._execute, args=(plan, directory, result), name=f'ascli-{run_id[:8]}', daemon=True)
                self._thread.start()
            except BaseException:
                self._active = None
                self.release_execution()
                raise
            return dict(result)

    def _expire(self, run_id):
        with self._lock:
            if self._active == run_id:
                self._timed_out = True
                self._cancel.set()
                self.request_cancel()

    def _check_cancel(self):
        from AutoScriptor.utils.cancel import check_cancel_raise
        if self._cancel.is_set():
            raise FlowCancelled('Flow timeout requested cancellation' if self._timed_out else 'Flow cancelled')
        check_cancel_raise()

    def _execute(self, plan, directory, result):
        adapter, error = None, None
        timer = threading.Timer(result['timeout'], self._expire, args=(result['run_id'],))
        timer.daemon = True
        state, values = 'succeeded', {}
        current_step = None
        started = time.monotonic()
        try:
            timer.start()
            result.update(state='running', started_at=time.time())
            self._publish(directory, result)
            self._check_cancel()
            adapter = self.adapter_factory()
            adapter.prepare(plan, directory, result['timeout'])
            with (directory / 'steps.jsonl').open('a', encoding='utf-8') as journal:
                for command in plan.commands:
                    self._check_cancel()
                    result['failed_line'] = command.line
                    current_step = {'line': command.line, 'command': command.name, 'started': time.monotonic() - started, 'state': 'running'}
                    journal.write(json.dumps(current_step, ensure_ascii=False) + '\n')
                    journal.flush()
                    value = adapter.execute(command, values)
                    self._check_cancel()
                    if command.save_as:
                        values[command.save_as] = value
                    current_step.update(state='completed', elapsed=time.monotonic() - started - current_step['started'], result=encode_result(value))
                    journal.write(json.dumps(current_step, ensure_ascii=False) + '\n')
                    journal.flush()
                    result['steps'].append(current_step)
                    current_step = None
                    self._publish(directory, result)
            result.pop('failed_line', None)
            # Function completion is not business completion without an explicit terminal observation.
            final_command = plan.commands[-1]
            has_observation = final_command.name in ('wait-appear', 'wait-disappear') or bool(final_command.until)
            result['verified'] = has_observation and bool(value)
        except BaseException as exception:
            from AutoScriptor.utils.cancel import TaskCancelled
            error = exception
            if self._timed_out:
                state = 'timed_out'
            elif self._cancel.is_set() or isinstance(exception, (FlowCancelled, TaskCancelled, KeyboardInterrupt)):
                state = 'cancelled'
            else:
                state = 'failed'
            result.update(error=str(exception), traceback=traceback.format_exc())
            try:
                if current_step is not None:
                    current_step.update(state=state, error=str(exception), elapsed=time.monotonic() - started - current_step['started'])
                    result['steps'].append(current_step)
                    with (directory / 'steps.jsonl').open('a', encoding='utf-8') as journal:
                        journal.write(json.dumps(current_step, ensure_ascii=False) + '\n')
                (directory / 'error.log').write_text(result['traceback'], encoding='utf-8')
            except OSError as write_error:
                result['evidence_error'] = str(write_error)
        finally:
            timer.cancel()
            if timer.ident is not None:
                timer.join()
            if self._timed_out and state == 'succeeded':
                state = 'timed_out'
                error = TimeoutError('Flow deadline elapsed before finalization')
                result['error'] = str(error)
            if adapter is not None:
                try:
                    evidence = adapter.finish(error)
                    result.update(evidence=evidence)
                    if evidence.get('warnings') and state == 'succeeded':
                        state = 'failed'
                        result['error'] = 'Flow completed but evidence/cleanup is incomplete'
                except Exception as cleanup_error:
                    result['evidence_error'] = str(cleanup_error)
                    if state == 'succeeded':
                        state = 'failed'
            # Keep the occupancy until all device work and evidence finalization are finished.
            with self._lock:
                try:
                    # stop() shares this lock: every accepted cancellation must reach the saved terminal state.
                    if self._cancel.is_set():
                        state = 'timed_out' if self._timed_out else 'cancelled'
                        result.update(verified=False, error='Flow timeout requested cancellation' if self._timed_out else 'Flow cancelled')
                    result.update(state=state, finished_at=time.time(), elapsed=time.monotonic() - started)
                    _write_json(directory / 'result.json', result)
                finally:
                    try:
                        self.reset_cancel()
                    finally:
                        self.release_execution()
                        self._active = None

    def stop(self, run_id):
        _run_id(run_id)
        with self._lock:
            if self._active == run_id:
                self._cancel.set()
                self.request_cancel()
                return {'run_id': run_id, 'state': 'stopping'}
            return self.get_run(run_id)

    def wait(self, run_id, *, timeout=None):
        with self._lock:
            worker = self._thread if self._active == run_id else None
        if worker is not None:
            worker.join(timeout)
            if worker.is_alive():
                raise TimeoutError(f'Run {run_id} is still executing; occupancy has not been released')
        return self.get_run(run_id)

    def artifacts(self, run_id):
        result = self.get_run(run_id)
        directory = self.root / run_id
        files = [{'name': path.relative_to(directory).as_posix(), 'bytes': path.stat().st_size} for path in sorted(directory.rglob('*')) if path.is_file() and not path.is_symlink()]
        return {'run_id': run_id, 'state': result['state'], 'directory': str(directory), 'files': files}

    def artifact_path(self, run_id, name):
        self.get_run(run_id)
        directory = (self.root / run_id).resolve()
        path = (directory / name).resolve()
        if directory not in path.parents:
            raise ValueError('Artifact path escapes this run')
        if not path.is_file():
            raise FileNotFoundError('Artifact does not exist inside this run')
        return path

    def shutdown(self, timeout=10):
        with self._lock:
            self._closing = True
            active = self._active
            if active:
                self.stop(active)
        if active:
            self.wait(active, timeout=timeout)


class AscliClient:
    """Standard-library client; no OCR or configuration initialization."""
    def __init__(self, url=None, *, token=None, credential_token=None, request_timeout=30):
        self.url = (url or os.environ.get('AUTOSCRIPTOR_URL') or f'http://127.0.0.1:{os.environ.get("AUTOSCRIPTOR_PORT", "5000")}').rstrip('/')
        if not self.url.startswith(('http://', 'https://')):
            raise ValueError('Backend URL must use http:// or https://')
        self.token = token or os.environ.get('AUTOSCRIPTOR_AUTH_TOKEN')
        self.credential_token = credential_token or os.environ.get('AUTOSCRIPTOR_CREDENTIAL_TOKEN')
        self.request_timeout = request_timeout

    def request(self, route, payload=None):
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['X-Auth-Token'] = self.token
        if self.credential_token:
            headers['X-Credential-Unlock'] = self.credential_token
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(f'{self.url}/api/{route.lstrip("/")}', data=body, headers=headers)
        try:
            with urlopen(request, timeout=self.request_timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            detail = error.read().decode('utf-8', errors='replace')
            raise RuntimeError(f'HTTP {error.code}: {detail}') from error
        except URLError as error:
            raise RuntimeError(f'Backend unavailable at {self.url}: {error.reason}; no local-device fallback') from error
        if isinstance(result, dict) and result.get('ok') is False:
            raise RuntimeError(result.get('error') or result.get('message') or str(result))
        return result

    def submit(self, source, *, timeout=300, request_id=None, allow_unsafe=False):
        parse_script(source)
        return self.request('ascli/runs', {'source': source, 'timeout': timeout, 'request_id': request_id or uuid.uuid4().hex, 'allow_unsafe': allow_unsafe})

    def get_run(self, run_id):
        return self.request(f'ascli/runs/{_run_id(run_id)}')

    def stop(self, run_id):
        return self.request(f'ascli/runs/{_run_id(run_id)}/stop', {})

    def wait(self, run_id, *, timeout=None, interval=0.25):
        started = time.monotonic()
        while True:
            result = self.get_run(run_id)
            if result['state'] in TERMINAL_STATES:
                return result
            if timeout is not None and time.monotonic() - started >= timeout:
                raise TimeoutError(f'Run {run_id} may still be active; query status or stop explicitly')
            time.sleep(interval)

    def run(self, source, **options):
        accepted = self.submit(source, **options)
        return self.wait(accepted['run_id'])


def _quote_token(token):
    return '"' + token.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _print_result(result, json_output=False):
    if json_output or not isinstance(result, dict) or not result.get('run_id') or 'state' not in result or 'files' in result or 'text' in result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"{result['run_id']}  {result.get('state', 'unknown')}")
    if result.get('directory'):
        print(f"Artifacts: {result['directory']}")
    if result.get('error'):
        print(result['error'])
    if result.get('state') == 'succeeded' and not result.get('verified'):
        print('Commands completed; no terminal observation was declared. This is not flow acceptance.')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ascli', description='Run complete .as flows through the existing AutoScriptor backend.')
    parser.add_argument('--url', help='Backend URL (or AUTOSCRIPTOR_URL)')
    parser.add_argument('--json', action='store_true', help='Machine-readable output')
    parser.add_argument('command', nargs='?', default='help')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    try:
        return _main(options)
    except (ValueError, RuntimeError, OSError, TimeoutError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False) if options.json else str(error), file=sys.stderr)
        return 1


def _main(options):
    command, arguments = options.command, options.arguments
    if command in ('help', 'capabilities'):
        catalogue = capabilities()
        if arguments:
            name = '-'.join(arguments)
            if name not in catalogue:
                raise ValueError(f'Unknown command: {name}')
            catalogue = {name: catalogue[name]}
        _print_result({'commands': catalogue, 'management': ['check FILE', 'transform FILE -o FILE.py', 'run FILE [--timeout 300] [--detach]', 'status [RUN_ID]', 'stop RUN_ID', 'logs RUN_ID', 'artifacts RUN_ID', 'task list|status|stop', 'task show|run TASK_PATH', 'task debug TASK_PATH on|off|inherit'], 'syntax': 'One command/line; -B x y [w h], -T text, -I key, --until/--until-gone, --any/--all, --next, --save-as, --frame, --via mumu|nemu'}, options.json)
        return 0
    if command in ('check', 'transform', 'run'):
        operation = argparse.ArgumentParser(prog=f'ascli {command}')
        operation.add_argument('file')
        if command == 'transform':
            operation.add_argument('-o', '--output')
        if command == 'run':
            operation.add_argument('--timeout', type=float, default=300)
            operation.add_argument('--request-id')
            operation.add_argument('--detach', action='store_true')
            operation.add_argument('--allow-unsafe', action='store_true')
        settings = operation.parse_args(arguments)
        source = sys.stdin.read() if settings.file == '-' else Path(settings.file).read_text(encoding='utf-8-sig')
        plan = parse_script(source)
        if command == 'check':
            _print_result({'ok': True, 'commands': len(plan.commands), 'requires_unsafe': plan.requires_unsafe, 'device_actions_executed': False}, options.json)
            return 0
        if command == 'transform':
            generated = transform_script(source)
            if settings.output:
                Path(settings.output).write_text(generated, encoding='utf-8')
            else:
                print(generated, end='')
            return 0
        return _submit_and_wait(AscliClient(options.url), source, settings, options.json)
    client = AscliClient(options.url)
    if command == 'status':
        result = client.get_run(arguments[0]) if arguments else client.request('ascli/status')
    elif command in ('stop', 'logs', 'artifacts'):
        if len(arguments) != 1:
            raise ValueError(f'{command} requires one RUN_ID')
        run_id = _run_id(arguments[0])
        result = client.stop(run_id) if command == 'stop' else client.request(f'ascli/runs/{run_id}/{command}')
    elif command == 'task':
        result = _task_command(client, arguments)
    else:
        # Validate original argv first, then serialize the restricted grammar, not a shell command.
        parse_command([command, *arguments])
        source = ' '.join(_quote_token(token) for token in [command, *arguments])
        settings = argparse.Namespace(timeout=300, request_id=None, allow_unsafe=False, detach=False)
        return _submit_and_wait(client, source, settings, options.json)
    _print_result(result, options.json)
    return 0


def _submit_and_wait(client, source, settings, json_output):
    request_id = settings.request_id or uuid.uuid4().hex
    print(f'Request ID: {request_id}', file=sys.stderr)
    result = client.submit(source, timeout=settings.timeout, request_id=request_id, allow_unsafe=settings.allow_unsafe)
    if not settings.detach:
        try:
            result = client.wait(result['run_id'])
        except KeyboardInterrupt:
            client.stop(result['run_id'])
            print(f'Stop requested for {result["run_id"]}; waiting for occupancy release', file=sys.stderr)
            try:
                result = client.wait(result['run_id'], timeout=15)
            except (TimeoutError, KeyboardInterrupt):
                print(f'Run {result["run_id"]} may still be stopping. Use ascli status.', file=sys.stderr)
                return 130
    _print_result(result, json_output)
    return 0 if result['state'] in ('accepted', 'running', 'succeeded') else 130 if result['state'] == 'cancelled' else 1


def _task_command(client, arguments):
    if arguments == ['list']:
        return client.request('refresh')['tasks']
    if arguments == ['status']:
        return client.request('run/status')
    if arguments == ['stop']:
        return client.request('stop', {})
    if len(arguments) == 2 and arguments[0] == 'show':
        configuration = client.request('refresh')
        return {'path': arguments[1], 'task': _get_task_node(configuration, arguments[1])}
    if len(arguments) == 3 and arguments[0] == 'debug':
        setting = arguments[2]
        if setting not in ('on', 'off', 'inherit'):
            raise ValueError('Debug setting must be on, off or inherit')
        if client.request('run/status')['runtime']['busy']:
            raise ExecutionBusyError('Cannot change task debug while runtime is occupied')
        configuration = client.request('refresh')
        task_node = _get_task_node(configuration, arguments[1])
        previous = task_node.get('debug', 'inherit')
        if setting == 'inherit':
            task_node.pop('debug', None)
        else:
            task_node['debug'] = setting == 'on'
        saved = client.request('tasks', {'tasks': configuration['tasks']})
        return {'path': arguments[1], 'previous_debug': previous, 'task': _get_task_node(saved, arguments[1])}
    if len(arguments) == 2 and arguments[0] == 'run':
        result = client.request('run', {'tasks': [arguments[1]], 'activate_scheduler': False, 'execution_source': 'task_list'})
        return {'accepted': result, 'note': 'Registered task submitted via the existing executor; inspect task status/evidence, not this acknowledgement.'}
    raise ValueError('Use task list | show TASK_PATH | debug TASK_PATH on|off|inherit | run TASK_PATH | status | stop')


def _get_task_node(configuration, task_path):
    task_node = configuration['tasks']
    for component in task_path.split('/'):
        if not component or not isinstance(task_node, dict) or component not in task_node:
            raise ValueError(f'Unknown registered task path: {task_path}')
        task_node = task_node[component]
    if not isinstance(task_node, dict) or 'on' not in task_node:
        raise ValueError(f'Expected a registered task, not a group: {task_path}')
    return task_node
