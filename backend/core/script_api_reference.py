"""Device-free API reference projection. Never import the runtime for inspection."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import AutoScriptor
from AutoScriptor.api_version import (
    API_PENDING_CHANGES,
    API_RELEASES,
    API_VERSION,
    API_VERSION_POLICY,
)
from backend.core.script_api_catalog import (
    CATEGORIES,
    COMMON_PARAMETERS,
    ENTRIES,
    GUIDANCE,
    QUICKSTART,
    REFERENCES,
)


def get_version_metadata() -> dict:
    return {
        "ok": True,
        "scope": "python-script-api",
        "version": API_VERSION,
        "display_version": f"v{API_VERSION}",
        "version_policy": API_VERSION_POLICY,
        "releases": [
            {**release, "changes": list(release["changes"])}
            for release in API_RELEASES
        ],
        "pending_changes": list(API_PENDING_CHANGES),
    }


def _find_function(tree: ast.Module, symbol: str) -> ast.FunctionDef:
    current_node = tree
    for name in symbol.split("."):
        current_node = next(
            (child for child in current_node.body
             if isinstance(child, (ast.FunctionDef, ast.ClassDef)) and child.name == name),
            None,
        )
        if current_node is None:
            raise ValueError(f"API reference symbol no longer exists: {symbol}")
    if not isinstance(current_node, ast.FunctionDef):
        raise ValueError(f"API reference symbol is not a function: {symbol}")
    return current_node


def _describe_signature(definition: ast.FunctionDef, entry: dict) -> dict:
    arguments = deepcopy(definition.args)
    if "." in entry["symbol"]:
        # Constructors expose their public call signature, not the class receiver.
        receiver_arguments = arguments.posonlyargs or arguments.args
        if receiver_arguments and receiver_arguments[0].arg in ("self", "cls"):
            receiver_arguments.pop(0)

    parameters = []
    parameter_help = {**COMMON_PARAMETERS, **entry["parameter_help"]}

    def append_parameter(argument, default, kind):
        description = parameter_help.get(argument.arg)
        if not description:
            raise ValueError(f"API parameter needs documentation: {entry['name']}.{argument.arg}")
        parameters.append({
            "name": argument.arg,
            "type": ast.unparse(argument.annotation) if argument.annotation else "未标注",
            "default": ast.unparse(default) if default is not None else None,
            "required": default is None and kind not in ("var_positional", "var_keyword"),
            "kind": kind,
            "description": description,
        })

    positional_arguments = [*arguments.posonlyargs, *arguments.args]
    defaults = [None] * (len(positional_arguments) - len(arguments.defaults)) + arguments.defaults
    for position, (argument, default) in enumerate(zip(positional_arguments, defaults)):
        kind = "positional_only" if position < len(arguments.posonlyargs) else "positional_or_keyword"
        append_parameter(argument, default, kind)
    if arguments.vararg:
        append_parameter(arguments.vararg, None, "var_positional")
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        append_parameter(argument, default, "keyword_only")
    if arguments.kwarg:
        append_parameter(arguments.kwarg, None, "var_keyword")

    unknown_parameters = entry["parameter_help"].keys() - {parameter["name"] for parameter in parameters}
    if unknown_parameters:
        raise ValueError(f"Stale API parameter documentation: {entry['name']}: {sorted(unknown_parameters)}")

    signature = f"{entry['name']}({ast.unparse(arguments)})"
    if definition.returns is not None:
        signature += f" -> {ast.unparse(definition.returns)}"
    return {"signature": signature, "parameters": parameters}


def build_reference() -> dict:
    package_root = Path(AutoScriptor.__file__).resolve().parent
    source_trees = {}
    entries = []
    for entry in ENTRIES:
        source_file = entry["source_file"]
        if source_file not in source_trees:
            # Only the fixed catalog supplies filenames; no request path or eval.
            source_trees[source_file] = ast.parse(
                (package_root / source_file).read_text(encoding="utf-8-sig")
            )
        definition = _find_function(source_trees[source_file], entry["symbol"])
        entries.append({
            **{key: value for key, value in entry.items()
               if key not in ("source_file", "symbol", "parameter_help")},
            **_describe_signature(definition, entry),
            "source": f"AutoScriptor/{source_file}:{definition.lineno}",
        })
    return {
        **get_version_metadata(),
        "categories": deepcopy(list(CATEGORIES)),
        "entries": entries,
        "quickstart": deepcopy(QUICKSTART),
        "guidance": deepcopy(list(GUIDANCE)),
        "references": deepcopy(list(REFERENCES)),
    }
