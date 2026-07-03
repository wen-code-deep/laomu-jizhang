import shlex
import string
from typing import Optional

import lldb
from lldb import SBFrame
from jb_lldb_commands_utils import make_absolute_name, register_lldb_commands
from stepping.jb_lldb_instructions_reader import InstructionsReader


def __lldb_init_module(debugger, internal_dict):
    global mono_module_name
    mono_module_name = None

    commands_list = {
        make_absolute_name(__name__, '_cmd_get_frame_description'): 'jb_get_frame_description',
        make_absolute_name(__name__, '_cmd_get_thread_state'): 'jb_get_thread_state',
        make_absolute_name(__name__, '_cmd_stop_here_may_break_mixed_debug'): 'jb_stop_here_may_break_mixed_debug',
        make_absolute_name(__name__, '_cmd_set_breakpoint_on_native_method_address'): 'jb_set_breakpoint_on_native_method_address',
        make_absolute_name(__name__, '_cmd_find_next_break_location'): 'jb_find_next_break_location',
        make_absolute_name(__name__, '_cmd_get_mono_module_name'): 'jb_get_mono_module_name',
    }
    register_lldb_commands(debugger, commands_list)


def get_target(debugger):
    return debugger.GetTargetAtIndex(0)

def get_thread_by_tid(target, tid) :
    return target.GetProcess().GetThreadByID(tid)

def get_mono_module(target) -> str:
    global mono_module_name
    if mono_module_name is not None:
        return mono_module_name

    mono_dll_standalone = "mono-2.0-sgen.dll"
    mono_dll_unity  = "mono-2.0-bdwgc.dll"
    for module in target.modules:
        module_name = module.file.fullpath
        if mono_dll_standalone in module_name:
            mono_module_name = mono_dll_standalone
            return mono_module_name
        if mono_dll_unity in module_name:
            mono_module_name = mono_dll_unity
            return mono_module_name


    raise RuntimeError("Couldn't find a mono module loaded")


def evaluate_expression_on_top_frame(thread : lldb.SBThread, expression):
    expression_module_prepended = "{{,,{0}}}{1}".format(get_mono_module(thread.process.target), expression)
    options = lldb.SBExpressionOptions()
    options.SetTryAllThreads(False)
    options.SetStopOthers(True)
    options.SetTimeoutInMicroSeconds(1000000)
    options.SetOneThreadTimeoutInMicroSeconds(1000000)
    options.SetIgnoreBreakpoints(True)
    return thread.frames[0].EvaluateExpression(expression_module_prepended, options)

def eval_mono_get_method_from_ip(thread : lldb.SBThread, pc_address):
    return evaluate_expression_on_top_frame(thread, "mono_get_method_from_ip((void*){0})".format(pc_address)) # we could use mono_pmip but when trying to do it we get reference to 'mono_pmip' is ambiguous error

# Managed debugger only gets a domain identifier in ids[ID_DOMAIN]->pdata (see debugger-agent.c), not a real mono domain id
def get_mono_domain_id_by_debugger_domain_id_expression(debugger_domain_id : int):
    # This code works since mono 2009
    return "((Id*)(ids[ID_DOMAIN]->pdata)[{0}])->domain->domain_id".format(debugger_domain_id - 1) # see decode_ptr_id method in debugger-agent.c for details

def set_tls_domain(eval_thread, debugger_domain_id):
    get_mono_domain_id_expr = get_mono_domain_id_by_debugger_domain_id_expression(debugger_domain_id)
    expression = "mono_tls_set_domain(mono_domain_get_by_id({0}))".format(get_mono_domain_id_expr)
    evaluate_expression_on_top_frame(eval_thread, expression)

def reset_tls_domain(eval_thread):
    evaluate_expression_on_top_frame(eval_thread,  "mono_tls_set_domain(NULL)")

def _cmd_get_frame_description(debugger, command, exe_ctx, result, internal_dict):
    cmd = shlex.split(command)
    eval_tid = int(cmd[0])
    eval_thread = get_thread_by_tid(get_target(debugger), eval_tid)
    set_reset = cmd[1]

    if set_reset == "reset_domain_and_exit":
        reset_tls_domain(eval_thread)
        return
    elif set_reset == "set_domain":
        debugger_domain_id = int(cmd[2])
        set_tls_domain(eval_thread, debugger_domain_id)
        pc_address = cmd[3]
    else:
        pc_address = cmd[2]

    method_description = eval_mono_get_method_from_ip(eval_thread, pc_address)
    summary: str = method_description.GetSummary()
    result.AppendMessage(summary)

def is_stopped_by_managed_debugger_mono_thread(thread: lldb.SBThread) -> bool:
    return unwind_frames(thread, ["suspend_current"])

def unwind_frames(thread: lldb.SBThread, framesWeLookFor : list) -> bool:
    thread_name = thread.name
    if thread_name is not None and ".dll" in thread_name and "mono" not in thread_name:
        return False

    # it can't be mono managed thread, since only start thread methods + debugger method at the top of the stack take more than 10 frames
    if thread.GetNumFrames() < 10:
        return False

    top_10_frames = thread.frames[:10]
    for frame in top_10_frames :
        module_name = frame.module.file.basename
        # shortcut for unity
        if module_name is not None and "Unity" in module_name:
            return False

        name = frame.GetFunctionName()
        if name is not None:
            if any(nameWeLookFor in name for nameWeLookFor in framesWeLookFor):
                return True


    return False

def is_suspend_current_frame(frame: lldb.SBFrame):
    name = frame.GetFunctionName()
    return name is not None and "suspend_current" in name

def is_stopped_in_ntdll(thread: lldb.SBThread):
    description = lldb.SBStream()
    top_frame = thread.GetFrameAtIndex(0)
    if top_frame is None:
        return False

    module = top_frame.GetModule()
    if module is None:
        return False

    module.GetDescription(description)
    text = description.GetData()
    # TODO: a more precise check could be here
    return "ntdll.dll" in text

def _cmd_get_thread_state(debugger, command, exe_ctx, result, internal_dict):
    thread_id_string = shlex.split(command)[0]
    target = get_target(debugger)

    thread = get_thread_by_tid(target, int(thread_id_string))
    result.AppendMessage("{0},{1}".format(is_stopped_by_managed_debugger_mono_thread(thread), is_stopped_in_ntdll(thread)))

def _cmd_stop_here_may_break_mixed_debug(debugger, command, exe_ctx, result, internal_dict):
    target = get_target(debugger)
    thread_id_string = shlex.split(command)[0]
    thread = get_thread_by_tid(target, int(thread_id_string))

    stop_may_break_mixed_mode = unwind_frames(thread, ["single_step_from_context", "breakpoint_from_context"])
    result.AppendMessage(str(stop_may_break_mixed_mode))

def _cmd_set_breakpoint_on_native_method_address(debugger, command, exe_ctx, result, internal_dict):
    target = get_target(debugger)
    cmd = shlex.split(command)
    guid = cmd[0]

    method_token = int(cmd[1])
    eval_thread_id = int(cmd[2])
    stepping_thread_id = int(cmd[3])
    eval_thread = get_thread_by_tid(target, eval_thread_id)

    get_mono_method_ptr_expression = "mono_get_method_checked(mono_image_loaded_by_guid(\"{0}\"), {1}, NULL, NULL, new MonoError())".format(guid, method_token)
    mono_method_ptr = evaluate_expression_on_top_frame(eval_thread, get_mono_method_ptr_expression).GetValue()
    mono_lookup_internal_call = "((MonoMethodPInvoke*){0})->addr".format(mono_method_ptr) # available since 2005, commit 26e81a7032726559908cdb9c95186931b25a36f0

    code_addr = evaluate_expression_on_top_frame(eval_thread, mono_lookup_internal_call).GetValue()

    code_address_decimal = int(code_addr[2:], 16)
    # In Unity MonoMethodPInvoke that has not been called has addr == 0, the addr will be correctly initialized once the method is called first time
    if code_address_decimal == 0:
        code_addr = evaluate_expression_on_top_frame(eval_thread, "mono_lookup_pinvoke_call_internal((MonoMethod*){0}, new MonoError())".format(mono_method_ptr)).GetValue() #available at least since 2019, commit bf3afd6cad3974706287d0943c3a5d0e823c1e5f
        code_address_decimal = int(code_addr[2:], 16)

    result.AppendMessage(str(code_addr))

    breakpoint = target.BreakpointCreateByAddress(code_address_decimal)

    if not breakpoint.IsValid():
        raise Exception("Breakpoint is not valid")
    breakpoint.SetThreadID(stepping_thread_id)

    br_id = breakpoint.GetID()
    result.AppendMessage(str(br_id))

def _cmd_find_next_break_location(debugger, command, exe_ctx, result, internal_dict):
    target = get_target(debugger)
    cmd = shlex.split(command)

    thread_native_id = int(cmd[0])
    frame_index = int(cmd[1])

    thread = get_thread_by_tid(target, thread_native_id)
    frame: SBFrame = thread.GetFrameAtIndex(frame_index)

    reader = InstructionsReader(target)
    pc = frame.GetPCAddress()

    def find_nearest_instruction(mnemonic: string, operands: string = None) -> Optional[lldb.SBInstruction]:
        for ins in reader.read_instructions(pc):
            if ins.GetMnemonic(target).startswith(mnemonic) and (operands is None or ins.GetOperands(target).startswith(operands)):
                return ins

        return None

    # We expect to have such a sequence of instructions (operands except 0x0 and r11 may be different)
    # mov    r11d, 0x0
    # test   r11, r11
    # je     0x24429f731a9
    # mov    r11, qword ptr [rbp - 0x8]
    # call   qword ptr [r11]
    mov_1 = find_nearest_instruction("mov", "r11d, 0x0")
    test = find_nearest_instruction("test", "r11, r11")
    je = find_nearest_instruction("je")
    mov_2 = find_nearest_instruction("mov", "r11, ")
    call = find_nearest_instruction("call", "qword ptr [r11]")

    if mov_1 is None or test is None or je is None or mov_2 is None or call is None:
        result.AppendMessage("NOT_FOUND")
        return

    # check that no other calls are emitted before our instructions
    first_call_instruction = find_nearest_instruction("call")
    if first_call_instruction is not None and first_call_instruction.GetAddress().GetLoadAddress(target) < mov_1.GetAddress().GetLoadAddress(target):
        result.AppendMessage("NOT_FOUND")
        return

    if mov_1.GetAddress().GetLoadAddress(target) + mov_1.GetByteSize() != test.GetAddress().GetLoadAddress(target) or \
      test.GetAddress().GetLoadAddress(target) + test.GetByteSize() != je.GetAddress().GetLoadAddress(target) or \
      je.GetAddress().GetLoadAddress(target) + je.GetByteSize() != mov_2.GetAddress().GetLoadAddress(target) or \
      mov_2.GetAddress().GetLoadAddress(target) + mov_2.GetByteSize() != call.GetAddress().GetLoadAddress(target):
        result.AppendMessage("NOT_FOUND")
        return

    result.AppendMessage(
        "{0} {1} {2}".format(
            hex(mov_1.GetAddress().GetLoadAddress(target)),
            hex(test.GetAddress().GetLoadAddress(target)),
            hex(call.GetAddress().GetLoadAddress(target))))

def _cmd_get_mono_module_name(debugger, command, exe_ctx, result, internal_dict):
    target = get_target(debugger)
    module_name = get_mono_module(target)
    result.AppendMessage(module_name)
