# -*- coding: utf-8 -*-
from qgis.core import QgsApplication

from .provider import SeoulClimateShelterProvider


class SeoulClimateShelterPlugin:
    """별도 메뉴/툴바 없이 Processing Toolbox에 도구를 등록하는 플러그인."""

    def __init__(self, iface=None):
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        # QGIS가 initProcessing()과 initGui()를 모두 부를 수 있어 중복 등록을 막는다.
        if self.provider is None:
            self.provider = SeoulClimateShelterProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
