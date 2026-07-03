from __future__ import annotations

import abc
import logging
import re
from enum import Enum
from typing import NamedTuple

from jb_debugger_logging import LOG_MESSAGE_SEPARATOR
from jb_declarative_formatters.parsers.cpp_parser import CppParser


def mangle_intrinsic_name(name: str, parameters_count: int) -> str:
    return f"__{name}___{parameters_count}__"


def create_intrinsic(intrinsic_overloads: dict[str, int],
                     mangled_name: str, base_name: str, expression: str, optional: bool,
                     parameters: list[TypeVizIntrinsicParameter], return_type: str | None,
                     dependencies: list[str],
                     intrinsic_unique_id: int):
    if intrinsic_overloads[mangled_name] == 1:
        return TypeVizIntrinsicInlined(
            mangled_name, base_name, expression,
            optional, parameters, return_type,
            dependencies, intrinsic_unique_id)
    else:
        return TypeVizIntrinsicLambdaBased(
            mangled_name, base_name, expression,
            optional, parameters, return_type,
            dependencies, intrinsic_unique_id)


class TypeVizIntrinsicParameter(object):
    def __init__(self, parameter_name: str | None, parameter_type: str):
        self.parameter_type = parameter_type
        self.parameter_name = parameter_name


class IntrinsicsScope:
    class Kind(str, Enum):
        BUILTIN = "builtin"
        GLOBAL = "global"
        TYPE = "type"

    def __init__(self, declaration_order_list: list[TypeVizIntrinsic], sorted_list: list[TypeVizIntrinsic], kind: IntrinsicsScope.Kind):
        self.declaration_order_list = declaration_order_list
        self.sorted_list = sorted_list
        self.kind = kind
        self.name_to_indexes_map: dict[str, list[int]] = {}

        for i in range(len(sorted_list)):
            name = sorted_list[i].name
            if name not in self.name_to_indexes_map:
                self.name_to_indexes_map[name] = list[int]()
            self.name_to_indexes_map[name].append(i)

    def retain_only_lazy(self) -> IntrinsicsScope:
        new_declaration_order_list = [item for item in self.declaration_order_list if item.is_lazy]
        new_sorted_list = [item for item in self.sorted_list if item.is_lazy]
        return IntrinsicsScope(new_declaration_order_list, new_sorted_list, self.kind)


class TypeVizIntrinsic(abc.ABC):
    INTRINSIC_NAME_PREFIX = "JB_INTRINSIC_MACRO_"

    def __init__(self, mangled_name: str, base_name: str, expression: str, optional: bool,
                 parameters: list[TypeVizIntrinsicParameter],
                 return_type: str | None,
                 dependencies: list[str],
                 intrinsic_unique_id: int):
        self.parameters = parameters
        self.return_type = return_type
        self.base_name: str = base_name
        self.optional = optional
        self.name: str = mangled_name
        self.expression: str = expression
        self.original_expression: str = expression
        self.is_used = False
        self.unique_dependencies = set(dependencies)
        self.is_lazy = True
        self.intrinsic_unique_id = intrinsic_unique_id

    def __hash__(self):
        return hash((self.original_expression, self.name, self.optional))

    def change_expression(self, new_expression: str):
        self.expression = new_expression

    def mark_as_used(self):
        self.is_used = True

    @abc.abstractmethod
    def get_intrinsic_call_replacement(self,
                                       expression: str, intrinsic_call: CppParser.FunctionCall,
                                       intrinsic_scope_kind: IntrinsicsScope.Kind) -> tuple[str, int, int]:
        pass

    @abc.abstractmethod
    def get_code_for_validate(self, prolog: str) -> str:
        pass

    @abc.abstractmethod
    def get_definition_code(self) -> str:
        pass


class TypeVizIntrinsicInlined(TypeVizIntrinsic):

    def __init__(self, mangled_name: str, base_name: str, expression: str, optional: bool,
                 parameters: list[TypeVizIntrinsicParameter],
                 return_type: str | None,
                 dependencies: list[str],
                 intrinsic_unique_id: int):
        super().__init__(mangled_name, base_name, expression, optional, parameters, return_type, dependencies, intrinsic_unique_id)
        self.is_lazy = False

    def get_intrinsic_call_replacement(self,
                                       expression: str, intrinsic_call: CppParser.FunctionCall,
                                       intrinsic_scope_kind: IntrinsicsScope.Kind) -> tuple[str, int, int]:
        start_pos = intrinsic_call.func_call_start_pos
        end_pos = intrinsic_call.func_call_end_pos

        init_params = []
        fixed_expression = self.expression
        for index, param in enumerate(self.parameters):
            # we should keep even unused parameters because an argument can be a function call with side effects
            param_name = param.parameter_name or f"__$jb$unused${index}"
            arg_expression = intrinsic_call.args[index]
            param_regex = re.compile(rf"\b{re.escape(param_name)}\b")
            type_must_be_deduced = "auto" in param.parameter_type
            argument_can_be_inlined = CppParser.is_literal_expr(arg_expression) or CppParser.is_identifier(arg_expression)
            if not type_must_be_deduced and argument_can_be_inlined:
                # if the argument is a trivial literal or identifier, we may inline it as is
                fixed_expression = param_regex.sub(f"(({param.parameter_type}){arg_expression})", fixed_expression)
            else:
                unique_param_name = f"{param_name}_{self.intrinsic_unique_id}"
                init_params.append(f"{param.parameter_type} {unique_param_name} = {arg_expression};")
                fixed_expression = param_regex.sub(unique_param_name, fixed_expression)

        init_params_block = ''.join(init_params)
        if init_params_block:
            text = f"({{" \
                   f"/*intrinsic {intrinsic_scope_kind}:{self.base_name}*/" \
                   f"{init_params_block}" \
                   f"({fixed_expression});" \
                   f"}})"
        else:
            # TODO: If we commonize the code, it will break [CppParser.simplify_cpp_expression]
            #  because it doesn't support statement expression simplification {(expressions in curly brackets);}
            text = f"(" \
                   f"/*intrinsic {intrinsic_scope_kind}:{self.base_name}*/" \
                   f'{fixed_expression}' \
                   f")"

        return text, start_pos, end_pos

    def get_definition_code(self) -> str:
        return ''

    def get_code_for_validate(self, prolog: str) -> str:
        return ''


class TypeVizIntrinsicLambdaBased(TypeVizIntrinsic):

    def __init__(self, mangled_name: str, base_name: str, expression: str, optional: bool,
                 parameters: list[TypeVizIntrinsicParameter],
                 return_type: str | None,
                 dependencies: list[str],
                 intrinsic_unique_id: int):
        super().__init__(mangled_name, base_name, expression, optional, parameters, return_type, dependencies, intrinsic_unique_id)

    def get_intrinsic_call_replacement(self,
                                       expression: str, intrinsic_call: CppParser.FunctionCall,
                                       intrinsic_scope_kind: IntrinsicsScope.Kind) -> tuple[str, int, int]:
        start_pos = intrinsic_call.func_call_start_pos
        end_pos = intrinsic_call.args_begin_pos
        text = f"{self.INTRINSIC_NAME_PREFIX}{self.name}("

        return text, start_pos, end_pos

    def get_code_for_validate(self, prolog: str) -> str:
        param_str = ", ".join([f"{p.parameter_type} {p.parameter_name}" for p in self.parameters])
        lambda_stmt = f"[&]({param_str})" \
                      "{" \
                      f" {prolog} " \
                      f" return {self.expression} ;" \
                      "}"
        return lambda_stmt

    def get_definition_code(self) -> str:
        param_str_without_types = ", ".join([f" {p.parameter_name}" for p in self.parameters])
        expr = self.expression
        for param in self.parameters:
            expr = expr.replace(param.parameter_name, f'(({param.parameter_type}) ({param.parameter_name}))')
        expr = expr.replace("\n", "\\\n")
        macros = f"\n" \
                 f"#define {self.INTRINSIC_NAME_PREFIX}{self.name}({param_str_without_types}) " \
                 f" ( {expr} )\n" \
                 f""
        return macros


class BuiltinIntrinsics:
    class _Signature(NamedTuple):
        base_name: str
        parameters: list[TypeVizIntrinsicParameter]

    @staticmethod
    def _create_builtin_intrinsics(signatures: list[_Signature], expression: str) -> list[TypeVizIntrinsicInlined]:
        intrinsics = []
        for signature in signatures:
            name = mangle_intrinsic_name(signature.base_name, len(signature.parameters))
            intrinsic = TypeVizIntrinsicInlined(name, signature.base_name, expression, False, signature.parameters, None, [], 0)
            intrinsics.append(intrinsic)
        return intrinsics

    _BUILTIN_INTRINSICS = [
        *_create_builtin_intrinsics(
            signatures=[
                _Signature(
                    base_name="__findnonnull",
                    parameters=[
                        TypeVizIntrinsicParameter("__$jb$param$ptr", "auto *"),
                        TypeVizIntrinsicParameter("__$jb$param$size", "auto")
                    ])],
            expression="({ "
                       "int __$jb$result = -1; "
                       "for (int i = 0; i < __$jb$param$size; ++ i) {"
                       " if (__$jb$param$ptr[i] != nullptr) { __$jb$result = i; break; }"
                       "} "
                       "__$jb$result; "
                       "})"),
        *_create_builtin_intrinsics(
            signatures=[
                _Signature(
                    base_name="strlen",
                    parameters=[TypeVizIntrinsicParameter("__$jb$param$str", "const char *")]
                ),
                _Signature(
                    base_name="wcslen",
                    parameters=[TypeVizIntrinsicParameter("__$jb$param$str", "const wchar_t *")]
                )
            ],
            expression="({ "
                       "unsigned long long __$jb$result = 0; "
                       "while(__$jb$param$str[__$jb$result]) {"
                       " ++__$jb$result;"
                       "} "
                       "__$jb$result; "
                       "})"),
        *_create_builtin_intrinsics(
            signatures=[
                _Signature(
                    base_name="strnlen",
                    parameters=[
                        TypeVizIntrinsicParameter("__$jb$param$str", "const char *"),
                        TypeVizIntrinsicParameter("__$jb$param$size", "unsigned long long")
                    ]
                ),
                _Signature(
                    base_name="wcsnlen",
                    parameters=[
                        TypeVizIntrinsicParameter("__$jb$param$str", "const wchar_t *"),
                        TypeVizIntrinsicParameter("__$jb$param$size", "unsigned long long")]
                )
            ],
            expression="({ "
                       "unsigned long long __$jb$result = 0; "
                       "while(__$jb$param$str[__$jb$result] && __$jb$result < __$jb$param$size) {"
                       " ++__$jb$result;"
                       "} "
                       "__$jb$result; "
                       "})"),
        *_create_builtin_intrinsics(
            signatures=[
                _Signature(
                    base_name="strcmp",
                    parameters=[
                        TypeVizIntrinsicParameter("__$jb$param$str1", "const char *"),
                        TypeVizIntrinsicParameter("__$jb$param$str2", "const char *"),
                    ]
                ),
                _Signature(
                    base_name="wcscmp",
                    parameters=[
                        TypeVizIntrinsicParameter("__$jb$param$str1", "const wchar_t *"),
                        TypeVizIntrinsicParameter("__$jb$param$str2", "const wchar_t *")
                    ]
                )
            ],
            expression="({ "
                       "unsigned long long __$jb$index = 0;"
                       "while(__$jb$param$str1[__$jb$index] && "
                       "      __$jb$param$str1[__$jb$index] == __$jb$param$str2[__$jb$index]) {"
                       " ++__$jb$index;"
                       "} "
                       "sizeof(__$jb$param$str1[__$jb$index]) == 1 ? "
                       "  ((int) (unsigned char) __$jb$param$str1[__$jb$index] - (int) (unsigned char) __$jb$param$str2[__$jb$index]) : "
                       "  ((int) (unsigned int) __$jb$param$str1[__$jb$index] - (int) (unsigned int) __$jb$param$str2[__$jb$index]); "
                       "})"),
        *_create_builtin_intrinsics(
            signatures=[
                _Signature(
                    base_name="strncmp",
                    parameters=[
                        TypeVizIntrinsicParameter("__$jb$param$str1", "const char *"),
                        TypeVizIntrinsicParameter("__$jb$param$str2", "const char *"),
                        TypeVizIntrinsicParameter("__$jb$param$size", "unsigned long long")
                    ]
                ),
                _Signature(
                    base_name="wcsncmp",
                    parameters=[
                        TypeVizIntrinsicParameter("__$jb$param$str1", "const wchar_t *"),
                        TypeVizIntrinsicParameter("__$jb$param$str2", "const wchar_t *"),
                        TypeVizIntrinsicParameter("__$jb$param$size", "unsigned long long")
                    ]
                )
            ],
            expression="({ "
                       "unsigned long long __$jb$index = 0;"
                       "while(__$jb$index < __$jb$param$size &&"
                       "      __$jb$param$str1[__$jb$index] &&"
                       "      __$jb$param$str1[__$jb$index] == __$jb$param$str2[__$jb$index]) {"
                       " ++__$jb$index;"
                       "} "
                       "__$jb$index >= __$jb$param$size ? 0 : ("
                       "  sizeof(__$jb$param$str1[__$jb$index]) == 1 ?"
                       "    ((int) (unsigned char) __$jb$param$str1[__$jb$index] - (int) (unsigned char) __$jb$param$str2[__$jb$index]): "
                       "    ((int) (unsigned int) __$jb$param$str1[__$jb$index] - (int) (unsigned int) __$jb$param$str2[__$jb$index])"
                       ");"
                       "})")
    ]

    _BUILTIN_SCOPE = IntrinsicsScope(_BUILTIN_INTRINSICS, _BUILTIN_INTRINSICS, IntrinsicsScope.Kind.BUILTIN)

    @classmethod
    def get_scope(cls):
        return cls._BUILTIN_SCOPE


def check_intrinsic_call_args(expr: str, intrinsic_call: CppParser.FunctionCall, logger: logging.Logger) -> bool:
    for arg_index, arg in enumerate(intrinsic_call.args):
        if not arg:
            logger.error("Error on parsing an intrinsic call in expression '%s': %s argument is missing", expr, arg_index)
            return False
    return True


def apply_intrinsics_to_expression(expression: str,
                                   user_intrinsics_scopes: list[IntrinsicsScope],
                                   logger: logging.Logger) -> str:
    intrinsics_scopes = [*user_intrinsics_scopes, BuiltinIntrinsics.get_scope()]
    new_expression = expression
    current_pos = 0
    while True:
        intrinsic_call = CppParser.search_unqualified_function_call(new_expression, current_pos)
        if not intrinsic_call:
            if new_expression != expression:
                logger.debug("Replaced intrinsic:\n'%s'\n>>>>>\n'%s'\n%s", expression, new_expression, LOG_MESSAGE_SEPARATOR)
            return new_expression
        current_pos = intrinsic_call.args_begin_pos
        if not check_intrinsic_call_args(new_expression, intrinsic_call, logger):
            continue
        if intrinsic_call.base_name.startswith(TypeVizIntrinsic.INTRINSIC_NAME_PREFIX):
            continue

        intrinsic: TypeVizIntrinsic | None = None
        current_scope: IntrinsicsScope | None = None

        intrinsic_mangled_name = mangle_intrinsic_name(intrinsic_call.base_name, len(intrinsic_call.args))
        for intrinsics_scope in intrinsics_scopes:
            if intrinsic_call.with_this_receiver and intrinsics_scope.kind != IntrinsicsScope.Kind.TYPE:
                continue
            intrinsic_index = intrinsics_scope.name_to_indexes_map.get(intrinsic_mangled_name, None)
            if intrinsic_index is None:
                continue

            intrinsic = intrinsics_scope.sorted_list[intrinsic_index[0]]
            current_scope = intrinsics_scope
            break

        if not intrinsic:
            continue

        replace_text, replace_start_pos, replace_end_pos = intrinsic.get_intrinsic_call_replacement(
            new_expression, intrinsic_call, current_scope.kind)

        new_expression = f"{new_expression[:replace_start_pos]}{replace_text}{new_expression[replace_end_pos:]}"
        current_pos = replace_start_pos

        for intrinsic_index in current_scope.name_to_indexes_map[intrinsic_mangled_name]:
            current_scope.sorted_list[intrinsic_index].mark_as_used()
