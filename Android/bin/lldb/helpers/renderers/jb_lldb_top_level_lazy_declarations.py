from __future__ import annotations

import lldb
from jb_declarative_formatters.type_viz_generated_method import GeneratedMethodDefinition
from jb_debugger_logging import LOG_MESSAGE_SEPARATOR
from renderers.jb_lldb_logging_manager import RENDER_LOG


class LLDBTopLevelLazyDeclarations:
    _LOG = RENDER_LOG.getChild("lazy declarations")

    @classmethod
    def declare_lazy_declaration(cls, debugger: lldb.SBDebugger, lazy_declaration: GeneratedMethodDefinition):
        if getattr(debugger, "AddTopLevelLazyDeclaration", None) is None:
            return

        decl_context = ""
        if lazy_declaration.declaration_context is not None:
            decl_context = lazy_declaration.declaration_context.get_full_name_with_wildcards()

        cls._LOG.debug("Adding declaration for '%s::%s':\n%s\n%s",
                       decl_context, lazy_declaration.declaration_name, lazy_declaration.definition_template, LOG_MESSAGE_SEPARATOR)

        error: lldb.SBError = debugger.AddTopLevelLazyDeclaration(decl_context, lazy_declaration.declaration_name,
                                                                  lazy_declaration.definition_template, lldb.eLanguageTypeC_plus_plus_14)
        if not error.Success():
            cls._LOG.error("Cannot add declaration for method '%s::%s': %s",
                           decl_context, lazy_declaration.declaration_name, error.description)

    @classmethod
    def remove_all_top_level_lazy_declarations(cls, debugger: lldb.SBDebugger):
        if getattr(debugger, "RemoveAllTopLevelLazyDeclarations", None) is None:
            return

        cls._LOG.debug("Removing all declarations")
        debugger.RemoveAllTopLevelLazyDeclarations()
