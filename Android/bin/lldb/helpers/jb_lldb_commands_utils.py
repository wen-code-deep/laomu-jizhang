import lldb


def make_absolute_name(root: str, name: str) -> str:
    return '.'.join([root, name])


def register_lldb_commands(debugger: lldb.SBDebugger, cmd_map: dict[str, str]):
    for func, cmd in cmd_map.items():
        debugger.HandleCommand('command script add -f {func} {cmd}'.format(func=func, cmd=cmd))
