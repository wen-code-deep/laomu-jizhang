from renderers.jb_lldb_logging_manager import RENDER_LOG


# Associate source files and storage of parsed type visualizers.
# Every type viz storage also contains list of registered summaries and synthetics.
class FormattersManager(object):
    class FormatterEntry(object):
        def __init__(self, storage, loader):
            self.storage = storage
            self.loader = loader

    def __init__(self, summary_func_name, synthetic_provider_class_name):
        self.formatter_entries = {}
        self.summary_func_name = summary_func_name
        self.synthetic_provider_class_name = synthetic_provider_class_name

    def get_all_registered_files(self):
        return self.formatter_entries.keys()

    def get_all_type_viz(self):
        return [e.storage for e in self.formatter_entries.values()]

    def register(self, filepath, loader) -> FormatterEntry:
        RENDER_LOG.info("Registering types storage for '%s'...", filepath)
        storage = loader(filepath)
        entry = self.FormatterEntry(storage, loader)
        self.formatter_entries[filepath] = entry
        return entry

    def unregister(self, filepath):
        RENDER_LOG.info("Unregistering types storage for '%s'...", filepath)
        try:
            del self.formatter_entries[filepath]
        except KeyError:
            RENDER_LOG.warning("Key '%s' wasn't found in formatters storage...", filepath)
            return

    def reload(self, filepath):
        try:
            entry = self.formatter_entries[filepath]
        except KeyError:
            RENDER_LOG.warning("Key '%s' wasn't found in formatters storage...", filepath)
            return

        entry.storage = entry.loader(filepath)
