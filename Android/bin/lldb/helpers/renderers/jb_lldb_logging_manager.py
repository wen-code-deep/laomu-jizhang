from __future__ import annotations

import shlex

from jb_lldb_commands_utils import make_absolute_name, register_lldb_commands
from renderers.jb_lldb_logging_render import LLDBLoggingRender, DiagnosticsLevel

RENDER_LOG = LLDBLoggingRender.get_render_logger()


def __lldb_init_module(debugger, internal_dict):
    commands_list = {
        make_absolute_name(__name__, '_cmd_set_diagnostics_level'): 'jb_renderers_set_diagnostics_level',
    }
    register_lldb_commands(debugger, commands_list)

    # set errors-only diagnostics level by default
    LLDBLoggingRender.update_render_diagnostic_level(DiagnosticsLevel.ERRORS)


def _cmd_set_diagnostics_level(debugger, command, exe_ctx, result, internal_dict):
    cmd = shlex.split(command)
    if len(cmd) != 1:
        result.SetError('Single argument expected.\nUsage: jb_renderers_set_diagnostics_level <level>')
        return
    try:
        diagnostic_level = DiagnosticsLevel(int(cmd[0]))
        LLDBLoggingRender.update_render_diagnostic_level(diagnostic_level)
    except Exception as e:
        result.SetError('Invalid argument passed, required level as integer in range [0, 2]: {}'.format(str(e)))
        return
