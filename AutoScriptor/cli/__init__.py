"""Public, device-free CLI imports; execution is owned by the hosting backend."""
from .adapter import CommandSpec, capabilities
from .core import AscliClient, AutomationService, ExecutionBusyError, main
from .transform import Command, ScriptPlan, TargetSpec, parse_command, parse_script, transform_script, transform_with_map

__all__ = [
    'AscliClient', 'AutomationService', 'ExecutionBusyError', 'CommandSpec',
    'Command', 'ScriptPlan', 'TargetSpec', 'capabilities', 'parse_command',
    'parse_script', 'transform_script', 'transform_with_map', 'main',
]
