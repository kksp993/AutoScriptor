"""Restricted .as grammar and natural Python generation; no eval or device imports."""
from __future__ import annotations

import ast
import builtins
import json
import keyword
import math
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

from .adapter import COMMANDS, OPTIONS


@dataclass
class TargetSpec:
    kind: str
    value: str | tuple[int, ...]
    box: tuple[int, ...] | None = None
    color: str | None = None
    margin: tuple[int, ...] = ()


@dataclass
class Command:
    name: str
    line: int
    arguments: tuple = ()
    options: dict = field(default_factory=dict)
    targets: list[TargetSpec] = field(default_factory=list)
    grouping: str = ''
    until: list[TargetSpec] = field(default_factory=list)
    until_grouping: str = ''
    until_gone: bool = False
    frame: str = ''
    save_as: str = ''
    via: str = ''


@dataclass
class ScriptPlan:
    source: str
    commands: tuple[Command, ...]

    @property
    def requires_unsafe(self):
        return any(COMMANDS[command.name].unsafe for command in self.commands)


def tokenize(line: str) -> list[str]:
    """Quotes protect spaces/comments; Windows backslashes stay literal."""
    if '\x00' in line or '$(' in line or '`' in line:
        raise ValueError('Shell substitution and NUL characters are not supported')
    tokens, buffer = [], []
    quote, started = '', False
    position = 0
    while position < len(line):
        character = line[position]
        if quote:
            if character == '\\' and position + 1 < len(line) and line[position + 1] in (quote, '\\'):
                buffer.append(line[position + 1])
                position += 2
                continue
            if character == quote:
                quote = ''
            else:
                buffer.append(character)
        elif character in ('"', "'"):
            quote, started = character, True
        elif character == '#' and not started:
            break
        elif character.isspace():
            if started:
                tokens.append(''.join(buffer))
                buffer, started = [], False
        elif character in ';|&<>$':
            raise ValueError('Shell operators/variables are not supported; use one command per line')
        else:
            buffer.append(character)
            started = True
        position += 1
    if quote:
        raise ValueError('Unclosed quote')
    if started:
        tokens.append(''.join(buffer))
    return tokens


def _convert(value: str, kind: str):
    if kind in ('str', 'optional-str', 'remainder'):
        return value
    if kind in ('mode', 'processor'):
        choices = ('text', 'img', 'both') if kind == 'mode' else ('strip', 'pretext', 'posttext', 'prenum', 'postnum')
        if value not in choices:
            raise ValueError(f'Expected one of {choices}, got {value!r}')
        return value
    if kind == 'json':
        result = json.loads(value, parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(f'Invalid JSON constant: {constant}')))
        if not isinstance(result, list):
            raise ValueError('Replay events must be a JSON list')
        return result
    result = float(value) if 'float' in kind else int(value)
    if not math.isfinite(result):
        raise ValueError('Numbers must be finite')
    if kind != 'int' and result < 0:
        raise ValueError('Expected a nonnegative value')
    if (kind.startswith('positive') or kind == 'finger') and result <= 0:
        raise ValueError('Expected a positive value')
    if kind == 'finger' and result > 10:
        raise ValueError('Finger ID must be within 1..10')
    return result


def _take(tokens, position, count, kind):
    if position + count > len(tokens):
        raise ValueError(f'Expected {count} value(s)')
    return tuple(_convert(value, kind) for value in tokens[position:position + count])


def _validate_box(box):
    if box[0] < 0 or box[1] < 0 or (len(box) == 4 and (box[2] <= 0 or box[3] <= 0)):
        raise ValueError('Coordinates must be nonnegative and rectangle dimensions positive')


def _validate_artifact(name):
    for path_type in (PurePosixPath, PureWindowsPath):
        path = path_type(name)
        if path.is_absolute() or path.drive or '..' in path.parts or not path.name:
            raise ValueError('Artifact name must be relative to the run directory without ..')
    if ':' in name:
        raise ValueError('Artifact name cannot contain a drive or alternate stream')


def parse_command(tokens: list[str], *, line: int = 1) -> Command:
    """Parse argv without round-tripping through shell quoting."""
    tokens = list(tokens)
    if tokens and tokens[0] == 'ascli':
        tokens.pop(0)
    if not tokens:
        raise ValueError('Empty command')
    if tokens[0] in ('app', 'adb', 'device', 'record') and len(tokens) > 1:
        tokens[:2] = ['-'.join(tokens[:2])]
    name = tokens.pop(0)
    if name not in COMMANDS:
        raise ValueError(f'Unknown command: {name}')
    spec = COMMANDS[name]
    command = Command(name=name, line=line)
    positional, targets = [], command.targets
    position, in_until, needs_target = 0, False, False
    while position < len(tokens):
        token = tokens[position]
        position += 1
        if token == '--':
            positional.extend(tokens[position:])
            break
        if token in ('-B', '-T', '-I'):
            if token == '-B':
                numbers = []
                while position < len(tokens) and re.fullmatch(r'-?\d+', tokens[position]):
                    numbers.append(int(tokens[position]))
                    position += 1
                if len(numbers) not in (2, 4):
                    raise ValueError('-B requires x y or x y width height')
                _validate_box(numbers)
                value = tuple(numbers)
            else:
                value = _take(tokens, position, 1, 'str')[0]
                position += 1
                if not value or value.startswith('--'):
                    raise ValueError(f'{token} requires a nonempty target')
            targets.append(TargetSpec(token[1:], value))
            needs_target = False
        elif token in ('--any', '--all'):
            attribute = 'until_grouping' if in_until else 'grouping'
            if getattr(command, attribute):
                raise ValueError('Duplicate grouping')
            setattr(command, attribute, token[2:])
        elif token in ('--until', '--until-gone'):
            if name not in ('click', 'seq-click') or in_until:
                raise ValueError('--until is supported once on click/seq-click only')
            command.until_gone = token == '--until-gone'
            targets, in_until, needs_target = command.until, True, True
        elif token in ('--next', '--to'):
            if in_until or spec.targets not in ('sequence', 'pair') or not targets or needs_target:
                raise ValueError('--next/--to requires a preceding sequence/swipe target')
            needs_target = True
        elif token in ('--box', '--color', '--margin') and spec.targets != 'none':
            if not targets:
                raise ValueError(f'{token} must follow a target')
            target = targets[-1]
            if token == '--box':
                if target.kind == 'B' or target.box is not None:
                    raise ValueError('--box belongs to a text/image target and can occur only once')
                target.box = _take(tokens, position, 4, 'int')
                _validate_box(target.box)
                position += 4
            elif token == '--color':
                target.color = _take(tokens, position, 1, 'str')[0]
                position += 1
            else:
                if target.box is None:
                    raise ValueError('--margin requires an explicit --box')
                target.margin = _take(tokens, position, 1, 'nonnegative-int')
                position += 1
        elif token in ('--save-as', '--frame', '--via'):
            value = _take(tokens, position, 1, 'str')[0]
            attribute = token[2:].replace('-', '_')
            if getattr(command, attribute):
                raise ValueError(f'Duplicate {token}')
            setattr(command, attribute, value)
            position += 1
        elif token in spec.options:
            parameter, kind, count = OPTIONS[token]
            if parameter in command.options:
                raise ValueError(f'Duplicate {token}')
            values = _take(tokens, position, count, kind) if count else ()
            command.options[parameter] = (kind == 'true') if count == 0 else values[0] if count == 1 else values
            position += count
        elif token.startswith('-') and not re.fullmatch(r'-?\d+(\.\d+)?', token):
            raise ValueError(f'Unknown option {token}; raw ADB arguments follow --')
        else:
            positional.append(token)
    if needs_target:
        raise ValueError('Missing target after transition option')
    if spec.arguments == ('remainder',):
        if not positional:
            raise ValueError('Expected an Android command after --')
        command.arguments = tuple(positional)
    else:
        required = sum(kind != 'optional-str' for kind in spec.arguments)
        if not required <= len(positional) <= len(spec.arguments):
            raise ValueError(f'{name} expects {required}..{len(spec.arguments)} positional arguments')
        command.arguments = tuple(_convert(value, kind) for value, kind in zip(positional, spec.arguments))
    target_count = len(command.targets)
    if spec.targets == 'none' and target_count or spec.targets not in ('none', 'optional') and not target_count:
        raise ValueError(f'{name}: invalid target count {target_count}')
    if spec.targets == 'pair' and target_count != 2:
        raise ValueError('Swipe requires exactly two targets')
    if spec.targets == 'optional' and target_count > 1:
        raise ValueError('This command accepts at most one target')
    if target_count > 1 and spec.targets not in ('sequence', 'pair') and not command.grouping:
        raise ValueError('Multiple targets require --any or --all')
    if command.grouping and (spec.targets not in ('many', 'one') or not target_count):
        raise ValueError('Grouping is not supported here')
    if command.grouping == 'all' and spec.targets == 'one':
        raise ValueError('This input API does not guarantee AND semantics; use --any or explicit waits')
    if len(command.until) > 1 and not command.until_grouping:
        raise ValueError('Multiple until targets require --any or --all')
    if command.until_grouping and not command.until:
        raise ValueError('Empty until group')
    if command.frame and not spec.frame_parameter:
        raise ValueError('--frame is supported only for fixed-frame recognition')
    if command.via and command.via not in ('mumu', 'nemu'):
        raise ValueError('--via must be mumu or nemu')
    if command.via and (spec.module != 'AutoScriptor' or not spec.device):
        raise ValueError('--via applies only to native device/recognition API commands')
    if name in ('extract-info', 'ocr') and any(target.kind != 'B' or len(target.value) != 4 for target in command.targets):
        raise ValueError('Extraction/OCR requires rectangular -B regions')
    if 'box' in command.options:
        _validate_box(command.options['box'])
    if name in ('screenshot', 'adb-pull') and command.arguments:
        _validate_artifact(command.arguments[-1])
    if name == 'screenshot' and command.arguments and PurePosixPath(command.arguments[0]).suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('Screenshot output must be PNG or JPEG')
    if name == 'replay':
        _validate_replay(command.arguments[0])
    if name == 'multi-finger-down':
        contacts = command.arguments[0]
        fingers = set()
        for contact in contacts:
            if not isinstance(contact, list) or len(contact) != 3 or not all(isinstance(value, int) for value in contact):
                raise ValueError('Contacts must be [finger, x, y] integer triples')
            if not 1 <= contact[0] <= 10 or contact[0] in fingers or min(contact[1:]) < 0:
                raise ValueError('Contacts require distinct fingers 1..10 and nonnegative coordinates')
            fingers.add(contact[0])
    if name == 'coloris' and 'color' not in command.options:
        raise ValueError('coloris requires --equals COLOR')
    if name in ('wait-appear', 'wait-disappear'):
        if command.grouping == 'all':
            raise ValueError('Use separate required waits for AND transitions; native list waits do not guarantee completion')
        if any(target.kind == 'B' and not target.color for target in command.targets):
            raise ValueError('A plain coordinate is not observable page evidence')
    if any(target.kind == 'B' and not target.color for target in command.until):
        raise ValueError('An until condition requires text, image or color evidence')
    if name in ('click-all',) and len(command.targets) != 1:
        raise ValueError('click-all requires one target, whose matches are clicked in row order')
    return command


def _validate_replay(events):
    previous_time = 0
    for event in events:
        if not isinstance(event, list) or len(event) != 5:
            raise ValueError('Replay accepts [t_ms, down|move|up, finger, nx, ny] events only')
        timestamp, operation, finger, horizontal, vertical = event
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < previous_time:
            raise ValueError('Replay timestamps must be finite, nonnegative and ordered')
        if operation not in ('down', 'move', 'up') or not isinstance(finger, int) or not 1 <= finger <= 10:
            raise ValueError('Invalid replay operation/finger')
        if not all(isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1 for value in (horizontal, vertical)):
            raise ValueError('Replay coordinates must be normalized to 0..1')
        previous_time = timestamp


def parse_script(source: str) -> ScriptPlan:
    if not isinstance(source, str) or len(source) > 65536:
        raise ValueError('Script must be text of at most 65536 characters')
    commands, variables = [], {}
    reserved = set(dir(builtins)) | {spec.function for spec in COMMANDS.values()} | {'B', 'I', 'T', 'Box', 'ui_T', 'ui_F', 'ctrl_mumu', 'ctrl_nemu', 'pretext', 'posttext', 'prenum', 'postnum'}
    for line_number, line in enumerate(source.lstrip('\ufeff').splitlines(), 1):
        try:
            tokens = tokenize(line)
            if not tokens:
                continue
            command = parse_command(tokens, line=line_number)
            if command.frame and variables.get(command.frame) != 'screenshot':
                raise ValueError('--frame must reference a preceding named screenshot')
            if command.save_as:
                name = command.save_as
                if not name.isidentifier() or keyword.iskeyword(name) or name.startswith('_') or name in reserved or name in variables:
                    raise ValueError('--save-as requires a new, nonreserved Python variable name')
                variables[name] = command.name
            commands.append(command)
            if len(commands) > 512:
                raise ValueError('At most 512 commands are allowed per flow')
        except (ValueError, TypeError) as error:
            raise ValueError(f'line {line_number}: {error}') from error
    if not commands:
        raise ValueError('Script contains no commands')
    return ScriptPlan(source, tuple(commands))


def _render_target(target, imports):
    imports.setdefault('AutoScriptor', set()).add(target.kind)
    arguments = [repr(value) for value in target.value] if target.kind == 'B' else [repr(target.value)]
    if target.box is not None:
        imports['AutoScriptor'].add('Box')
        region = 'Box(' + ', '.join(map(str, target.box)) + ')'
        if target.margin:
            region += f'.margin({target.margin[0]})'
        arguments.append(f'box={region}')
    if target.color is not None:
        arguments.append(f'color={target.color!r}')
    return f'{target.kind}({", ".join(arguments)})'


def _render_targets(targets, grouping, imports):
    expressions = [_render_target(target, imports) for target in targets]
    if grouping == 'any':
        return '(' + ', '.join(expressions) + ',)'
    if grouping == 'all':
        return '[' + ', '.join(expressions) + ']'
    return expressions[0]


def render_command(command, imports):
    spec = COMMANDS[command.name]
    imports.setdefault(spec.module, set()).add(spec.function)
    arguments = [repr(value) for value in command.arguments]
    if command.targets:
        if spec.targets in ('sequence', 'pair'):
            expressions = [_render_target(target, imports) for target in command.targets]
            arguments.extend(expressions if spec.targets == 'pair' else ['[' + ', '.join(expressions) + ']'])
        else:
            arguments.append(_render_targets(command.targets, command.grouping, imports))
    for name, value in command.options.items():
        expression = repr(value)
        if name == 'post_process':
            expression = 'str.strip' if value == 'strip' else value
            if value != 'strip':
                imports.setdefault('AutoScriptor', set()).add(value)
        arguments.append(f'{name}={expression}')
    if command.frame:
        arguments.append(f'{spec.frame_parameter}={command.frame}')
    if command.until:
        predicate = 'ui_F' if command.until_gone else 'ui_T'
        imports.setdefault('AutoScriptor', set()).add(predicate)
        arguments.append(f'until=lambda: {predicate}({_render_targets(command.until, command.until_grouping, imports)})')
    function = spec.function
    if command.via:
        wrapper = f'ctrl_{command.via}'
        imports.setdefault('AutoScriptor', set()).add(wrapper)
        function = f'{wrapper}({function})'
    assignment = f'{command.save_as} = ' if command.save_as else ''
    return f'{assignment}{function}({", ".join(arguments)})'


def transform_with_map(source: str) -> tuple[str, dict[int, int]]:
    plan = parse_script(source)
    imports = {}
    statements = [render_command(command, imports) for command in plan.commands]
    headers = [f'from {module} import {", ".join(sorted(names))}' for module, names in sorted(imports.items())]
    generated = '\n'.join([*headers, '', *statements, ''])
    ast.parse(generated)
    mapping = {index + len(headers) + 2: command.line for index, command in enumerate(plan.commands)}
    return generated, mapping


def transform_script(source: str) -> str:
    """Return importable Python: inline targets and one complete call per line."""
    return transform_with_map(source)[0]
