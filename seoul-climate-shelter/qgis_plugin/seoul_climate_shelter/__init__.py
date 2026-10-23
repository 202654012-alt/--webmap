# -*- coding: utf-8 -*-
def classFactory(iface):
    from .plugin import SeoulClimateShelterPlugin
    return SeoulClimateShelterPlugin(iface)
