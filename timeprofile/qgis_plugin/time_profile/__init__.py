def classFactory(iface):
    from .plugin import TimeProfilePlugin
    return TimeProfilePlugin(iface)
