# -*- coding: utf-8 -*-
from qgis.core import QgsProcessingProvider

from .alg_shelter_count import ShelterCountByDistrictAlgorithm
from .alg_nearest_shelters import NearestSheltersAlgorithm


class SeoulClimateShelterProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(ShelterCountByDistrictAlgorithm())
        self.addAlgorithm(NearestSheltersAlgorithm())

    def id(self):
        return 'seoul_climate_shelter'

    def name(self):
        return '서울 기후동행쉼터'

    def longName(self):
        return self.name()
