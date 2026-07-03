from __future__ import annotations

import copy
import re
from typing import List, Tuple, NamedTuple

from jb_declarative_formatters.parsers.type_name_parser import parse_type_name_template
from jb_declarative_formatters.type_name_template import TypeNameTemplate


class TypeVizTypeTraits:
    class TypeSpec(NamedTuple):
        type_name: str
        type_args: list[str]

    class StringTraits(NamedTuple):
        char_type: str
        strncmp: str
        strlen: str

    CHAR_CASE_SENSITIVE = StringTraits("char", "strncmp", "strlen")
    CHAR_CASE_INSENSITIVE = StringTraits("char", "::_strnicmp", "strlen")
    WCHAR_CASE_SENSITIVE = StringTraits("wchar_t", "wcsncmp", "wcslen")
    WCHAR_CASE_INSENSITIVE = StringTraits("wchar_t", "::_wcsnicmp", "wcslen")

    _SUPPORTED_STRING_TYPES = {
        CHAR_CASE_SENSITIVE: [TypeSpec("std::basic_string<>", ["char"]), TypeSpec("std::basic_string_view<>", ["char"])],
        WCHAR_CASE_SENSITIVE: [TypeSpec("std::basic_string<>", ["wchar_t"]), TypeSpec("std::basic_string_view<>", ["wchar_t"])],
        CHAR_CASE_INSENSITIVE: [TypeSpec("TStringView<>", ["ANSICHAR"]), TypeSpec("TStringView<>", ["char"]), TypeSpec("FName", [])],
        WCHAR_CASE_INSENSITIVE: [TypeSpec("TStringView<>", ["WIDECHAR"]), TypeSpec("TStringView<>", ["wchar_t"]), TypeSpec("FString", [])]
    }

    _STRING_TYPES_SPECIALIZATIONS = [
        (TypeSpec("std::basic_string<>", ["*"]),
         [parse_type_name_template("std::basic_string<char, *>"), parse_type_name_template("std::basic_string<wchar_t, *>")]),
        (TypeSpec("std::basic_string_view<>", ["*"]),
         [parse_type_name_template("std::basic_string_view<char, *>"), parse_type_name_template("std::basic_string_view<wchar_t, *>")]),
        (TypeSpec("TStringView<>", ["*"]),
         [parse_type_name_template("TStringView<char>"), parse_type_name_template("TStringView<wchar_t>")]),
    ]

    @staticmethod
    def _match_type_spec(type_spec: TypeVizTypeTraits.TypeSpec, type_name_template: TypeNameTemplate) -> bool:
        if type_spec.type_name != type_name_template.name or len(type_spec.type_args) > len(type_name_template.args):
            return False
        for (i, arg) in enumerate(type_spec.type_args):
            if type_name_template.args[i].name != arg:
                return False
        return True

    @classmethod
    def get_string_type_traits(cls, type_name_template: TypeNameTemplate) -> List[Tuple[TypeNameTemplate, StringTraits]]:
        for (type_spec, specializations) in cls._STRING_TYPES_SPECIALIZATIONS:
            if cls._match_type_spec(type_spec, type_name_template):
                spec_types = []
                for spec in specializations:
                    if len(spec.args) < len(type_name_template.args):
                        type_name_template_copy = copy.deepcopy(type_name_template)
                        for (i, arg) in enumerate(spec.args):
                            if not arg.is_wildcard:
                                type_name_template_copy.args[i] = arg
                        spec_types += cls.get_string_type_traits(type_name_template_copy)
                    else:
                        spec_types += cls.get_string_type_traits(spec)
                return spec_types

        matched_traits = []
        for type_trait, type_specializations in cls._SUPPORTED_STRING_TYPES.items():
            for type_spec in type_specializations:
                if cls._match_type_spec(type_spec, type_name_template):
                    matched_traits.append((type_name_template, type_trait))
        return matched_traits

    _REQUIRED_SUBSCRIPT_OPERATOR_TYPES = ["std::basic_string", "TArray", "TBitArray", "TMulticastDelegate"]

    @classmethod
    def is_subscript_operator_required(cls, type_name: str) -> bool:
        for required_type in cls._REQUIRED_SUBSCRIPT_OPERATOR_TYPES:
            if type_name.startswith(required_type):
                return True
        return False
