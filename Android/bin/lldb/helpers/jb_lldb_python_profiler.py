from __future__ import annotations

import cProfile
import shlex
import inspect

import lldb

from jb_lldb_commands_utils import make_absolute_name, register_lldb_commands


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict):
    commands_list = {
        make_absolute_name(__name__, '_cmd_python_profiler'): 'jb_python_profiler',
    }
    register_lldb_commands(debugger, commands_list)


class PythonProfiler:
    _profiler: cProfile.Profile | None = None

    @classmethod
    def start(cls):
        if cls._profiler:
            raise RuntimeError('Profiler already running')
        cls._profiler = cProfile.Profile()
        cls._profiler.enable()

    @classmethod
    def stop(cls):
        if not cls._profiler:
            raise RuntimeError('Profiler not running')
        cls._profiler.disable()
        cls._profiler = None

    @classmethod
    def dump(cls, out_file: str):
        if not cls._profiler:
            raise RuntimeError('Profiler not running')
        cls._profiler.disable()
        cls._profiler.dump_stats(out_file)
        cls._profiler.enable()


PYTHON_PROFILER_ACTIONS = {
    action: method for (action, method) in inspect.getmembers(PythonProfiler, predicate=inspect.ismethod)
}


def _cmd_python_profiler(debugger: lldb.SBDebugger, command: str, exe_ctx: lldb.SBExecutionContext, result: lldb.SBCommandReturnObject,
                         internal_dict):
    help_message = f'Usage: jb_python_profiler <{"|".join(PYTHON_PROFILER_ACTIONS.keys())}> <params>'
    cmd = shlex.split(command)
    if len(cmd) < 1:
        result.SetError(f'Action expected.\n{help_message}')
        return

    action = PYTHON_PROFILER_ACTIONS.get(cmd[0])
    if action is None:
        result.SetError(f'Unknown action "{cmd[0]}".\n{help_message}')
        return

    arguments = cmd[1:]
    signature = inspect.signature(action)

    if len(arguments) != len(signature.parameters):
        result.SetError(f'Not enough arguments, expected {len(signature.parameters)} passed {len(arguments)}.\n{help_message}')
        return

    try:
        action(*arguments)
    except Exception as e:
        result.SetError(str(e))
