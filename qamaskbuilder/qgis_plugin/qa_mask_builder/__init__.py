def classFactory(iface):
    from .plugin import QAMaskBuilderPlugin
    return QAMaskBuilderPlugin(iface)
