from jb_declarative_formatters.parsers.natvis import natvis_parse_file
from jb_declarative_formatters.type_viz_storage import TypeVizStorage
from renderers.jb_lldb_jetvis_proxy import JetvisProxy
from renderers.jb_lldb_logging_manager import RENDER_LOG


def natvis_loader(filepath):
    storage = TypeVizStorage()
    load_natvis_file(storage, filepath)
    storage.generate_top_level_methods(RENDER_LOG, JetvisProxy.is_enabled())
    return storage


def load_natvis_file(storage, filepath):
    RENDER_LOG.info("Parsing %s", filepath)
    for type_viz in natvis_parse_file(filepath, RENDER_LOG, JetvisProxy.is_enabled()):
        RENDER_LOG.info("Register types: %s", ', '.join(map(_type_viz_name_pp, type_viz.type_viz_names)))
        storage.add_type(type_viz)


def _type_viz_name_pp(type_viz_name):
    return "'" + str(type_viz_name) + "'"
