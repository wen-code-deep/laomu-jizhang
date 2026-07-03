from __future__ import annotations

import re
from io import StringIO
from typing import Tuple, Optional, Sequence, Callable, NamedTuple

from jb_declarative_formatters.parsers.args_parser import parse_args


class CppParser:
    _REGEX_IDENT = r"[A-Za-z_$][\w$]*"
    _REGEX_SUBSCRIPT = r"\[\d+]"

    _PATTERN_IDENT = re.compile(f"^{_REGEX_IDENT}$")
    # Expression like that: foo->bar[1][0].baz
    _PATTERN_TRIVIAL_EXPR = re.compile(fr"^{_REGEX_IDENT}(:?{_REGEX_SUBSCRIPT})*"
                                       fr"(:?(:?\.|->){_REGEX_IDENT}(:?{_REGEX_SUBSCRIPT})*)*$")
    _PATTERN_ARRAY_ACCESS = re.compile(f"^{_REGEX_SUBSCRIPT}$")
    _PATTERN_LAMBDA = re.compile(r"^.*<lambda_[0-9a-f]{32}>.*$")
    _PATTERN_TEMPLATE_REGEX = re.compile(r"\$T([1-9][0-9]*)")

    _PATTERNS_FUNC_CALL = [
        # foo(), bar()
        (re.compile(fr"(?<!\.)(?<!->)\b(?P<func_name>{_REGEX_IDENT})\s*\("), False),
        # this->foo(), this -> foo()
        (re.compile(rf"\bthis\s*->\s*(?P<func_name>{_REGEX_IDENT}\w*)\s*\("), True),
        # (*this).foo(), ( * this ) . foo()
        (re.compile(rf"\(\s*\*\s*this\s*\)\s*\.\s*(?P<func_name>{_REGEX_IDENT}\w*)\s*\("), True)
    ]

    _SPECIFIERS_CV = {"const", "volatile"}
    _SPECIFIERS_TYPE_CLASS = {"class", "struct", "union", "enum"}

    @classmethod
    def is_trivial_expression(cls, expr: str) -> bool:
        return cls._PATTERN_TRIVIAL_EXPR.match(expr) is not None

    @classmethod
    def is_array_access_expr(cls, expr: str) -> bool:
        return cls._PATTERN_ARRAY_ACCESS.match(expr) is not None

    @classmethod
    def is_identifier(cls, expr: str) -> bool:
        return cls._PATTERN_IDENT.match(expr) is not None

    @classmethod
    def is_literal_expr(cls, expr: str) -> bool:
        if not expr:
            return False
        # TODO: Support more literals
        if expr in ("true", "false"):
            return True
        if expr[0] in ('-', '+'):
            return expr[1:].isdigit()
        return expr.isdigit()

    @classmethod
    def has_lambda_in_type_expr(cls, type_expr: str) -> bool:
        return cls._PATTERN_LAMBDA.match(type_expr) is not None

    @staticmethod
    def remove_cpp_comments(code: str) -> str:
        comment_pos = []
        in_string = False
        i = 0
        code_len = len(code)
        while i < code_len:
            char = code[i]
            if not in_string and char == "/" and i + 1 < code_len:
                comment_end_seq = None
                next_char = code[i + 1]
                if next_char == "/":
                    comment_end_seq = "\n"
                elif next_char == "*":
                    comment_end_seq = "*/"
                if comment_end_seq is not None:
                    comment_end = code.find(comment_end_seq, i + 2)
                    comment_end = code_len if comment_end < 0 else comment_end + len(comment_end_seq)
                    comment_pos.append((i, comment_end))
                    i = comment_end
                    continue

            if char == '"':
                in_string = not in_string

            i += 1

        if not comment_pos:
            return code

        code_no_comments = []
        code_pos = 0
        for (comment_start, comment_end) in comment_pos:
            if code_pos < comment_start:
                code_no_comments.append(code[code_pos:comment_start].strip())
            code_pos = comment_end
        if code_pos < code_len:
            code_no_comments.append(code[code_pos:].strip())
        # #pragma must be on a separate line
        return ''.join(map(lambda c: f"\n{c}\n" if c.startswith("#pragma") else c, code_no_comments))

    @staticmethod
    def is_outer_parentheses_balanced(s: str) -> bool:
        if not s.startswith('(') or not s.endswith(')'):
            return False
        counter = 0
        in_string = False
        for i in range(1, len(s) - 1):
            char = s[i]
            if char == '"':
                in_string = not in_string
            elif not in_string:
                if char == '(':
                    counter += 1
                elif char == ')':
                    counter -= 1
                if counter < 0:
                    # There was a closing parenthesis without a matching opening one
                    return False
        return counter == 0 and not in_string

    @classmethod
    def try_remove_outer_parentheses(cls, s: str) -> str:
        s = s.strip()
        while cls.is_outer_parentheses_balanced(s):
            s = s[1:-1].strip()
        return s.strip()

    @classmethod
    def try_merge_deref_and_address_of(cls, s: str) -> str:
        if not s.startswith("(*(&(") or not s.endswith(")))"):
            return s

        if not cls.is_outer_parentheses_balanced(s):
            return s
        # (*(&(<expr>))) -> (&(<expr>))
        no_deref = s[2:-1]

        if not cls.is_outer_parentheses_balanced(no_deref):
            return s
        # (&(<expr>)) -> (<expr>)
        no_address_of = no_deref[2:-1]

        if not cls.is_outer_parentheses_balanced(no_address_of):
            return s
        return no_address_of

    @classmethod
    def cut_deref_or_address_of_from_trivial_expression(cls, expr: str) -> Tuple[Optional[str], Optional[str]]:
        expr = expr.strip()
        if expr.startswith("*") or expr.startswith("&"):
            specifier = expr[0]
            sub_expr = CppParser.try_remove_outer_parentheses(expr[1:])
            if cls.is_trivial_expression(sub_expr):
                return specifier, sub_expr
        return None, None

    @classmethod
    def simplify_cpp_expression(cls, expr: str) -> str:
        expr = cls.remove_cpp_comments(expr.strip())
        return cls.try_remove_outer_parentheses(expr)

    @classmethod
    def insert_type_class_specifier(cls, type_expr: str, type_class_specifier: str) -> str:
        if type_class_specifier not in cls._SPECIFIERS_TYPE_CLASS:
            return type_expr
        type_expr = type_expr.lstrip()
        start_index = 0
        new_type_expr = []
        for index, char in enumerate(type_expr):
            if char.isspace():
                specifier = type_expr[start_index:index]
                if not specifier:
                    start_index = index + 1
                    continue
                if specifier in cls._SPECIFIERS_TYPE_CLASS:
                    return type_expr
                if specifier in cls._SPECIFIERS_CV:
                    new_type_expr.append(specifier)
                    start_index = index + 1
                    continue
                break
        type_tail = type_expr[start_index:]
        if type_tail in cls._SPECIFIERS_TYPE_CLASS:
            return type_expr
        if type_tail in cls._SPECIFIERS_CV:
            new_type_expr.append(type_tail)
            new_type_expr.append(type_class_specifier)
        else:
            new_type_expr.append(type_class_specifier)
            new_type_expr.append(type_tail)
        return " ".join(new_type_expr)

    @classmethod
    def remove_type_class_specifier(cls, type_expr: str) -> str:
        type_expr = type_expr.lstrip()
        for type_class_specifier in cls._SPECIFIERS_TYPE_CLASS:
            if len(type_expr) > len(type_class_specifier) and \
              type_expr.startswith(type_class_specifier) and \
              type_expr[len(type_class_specifier)].isspace():
                return type_expr[len(type_class_specifier) + 1:].lstrip()
        return type_expr

    class FunctionCall(NamedTuple):
        base_name: str
        args: list[str]
        func_call_start_pos: int
        args_begin_pos: int
        func_call_end_pos: int
        with_this_receiver: bool

    @classmethod
    def search_unqualified_function_call(cls, expr: str, search_start: int) -> FunctionCall | None:
        """
        Searches for the first unqualified function call in the given expression string, starting from the specified position.

        A valid function call matches one of the following:
        - A function call without any receiver, e.g., `foo()`, `bar()`.
        - A function call explicitly using `this` as the receiver, e.g., `this->foo()`, `(*this).foo()`.

        Function calls with other receivers (e.g., `obj.foo()`, `ptr->bar()`) are ignored.

        :param expr: The expression string to search within.
        :param search_start: The position in the string to start searching from.

        :return: FunctionCall for the first matching function call, or None if no valid call is found.
        """
        all_matches = list(filter(lambda m: m[0], map(lambda p: (p[0].search(expr, search_start), p[1]), cls._PATTERNS_FUNC_CALL)))
        if not all_matches:
            return None

        # Get the leftmost call
        (function_call, with_this_receiver) = min(all_matches, key=lambda call: call[0].start())
        function_name = function_call.group('func_name')
        args_begin_pos = function_call.end()
        args, func_call_end_pos = parse_args(expr, args_begin_pos)
        return cls.FunctionCall(function_name, args, function_call.start(), args_begin_pos, func_call_end_pos, with_this_receiver)

    @classmethod
    def substitute_wildcards(cls, expr: str, repl: Callable[[int], str | None]) -> tuple[str, bool]:
        expr_len = len(expr)
        i = 0
        s = StringIO()
        all_substituted = True
        while i < expr_len:
            m = cls._PATTERN_TEMPLATE_REGEX.search(expr, i)
            if m is None:
                s.write(expr[i:])
                break

            s.write(m.string[i:m.start()])
            wildcard_idx = int(m.group(1)) - 1
            replacement = repl(wildcard_idx)
            if replacement is None:
                all_substituted = False
                replacement = m.string[m.start():m.end()]
            s.write(replacement)
            i = m.end()
            if i < expr_len and replacement and replacement[-1] == '>' and expr[i] == '>':
                # write extra space between >>
                s.write(' ')

        return s.getvalue(), all_substituted

    @classmethod
    def resolve_wildcards(cls, expr: str, wildcards: Sequence[str]) -> tuple[str, bool]:
        def replace_wildcard(index: int) -> str | None:
            try:
                nonlocal wildcards
                return wildcards[index]
            except IndexError:
                return None
        return cls.substitute_wildcards(expr, replace_wildcard)

    @staticmethod
    def try_extract_lambda_type_name(type_name: str) -> str | None:
        idx = type_name.rfind('<lambda_')
        if idx == -1:
            return None
        if type_name[-1] != '>':
            return None
        if idx == 0:
            return type_name
        extracted_name = type_name[idx + len("<lambda_"):-1]
        if not extracted_name.isalnum():
            return None
        return type_name[idx:]
