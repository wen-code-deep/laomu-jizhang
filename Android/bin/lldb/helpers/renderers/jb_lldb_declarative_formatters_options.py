g_max_string_length = 250

g_max_num_children = 10000

g_max_recursion_level = 50
g_recursion_level = -1

g_enable_formatting = True
g_global_hex = False
g_global_hex_show_both = False


def set_max_string_length(val: int):
    global g_max_string_length
    g_max_string_length = val


def get_max_string_length() -> int:
    global g_max_string_length
    return g_max_string_length


def enable_disable_formatting(val: bool):
    global g_enable_formatting
    g_enable_formatting = val


def is_enabled_formatting():
    global g_enable_formatting
    return g_enable_formatting


def set_recursion_level(level: int) -> int:
    global g_recursion_level
    prev = g_recursion_level
    g_recursion_level = level
    return prev


def get_recursion_level() -> int:
    global g_recursion_level
    return g_recursion_level


def set_global_hex(val: bool):
    global g_global_hex
    g_global_hex = val


def set_global_hex_show_both(val: bool):
    global g_global_hex_show_both
    g_global_hex_show_both = val


def is_global_hex():
    global g_global_hex
    return g_global_hex


def is_global_hex_show_both():
    global g_global_hex_show_both
    return g_global_hex_show_both
