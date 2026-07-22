"""Repository Service: fetches NetCDF profiles from the GDAC via HTTP."""

from floatchat.repository_service.base import AbstractRepositoryService
from floatchat.repository_service.dataset_wrapper import NetCDFDataset
from floatchat.repository_service.gdac_http import GDACRepositoryService

__all__ = [
    "AbstractRepositoryService",
    "GDACRepositoryService",
    "NetCDFDataset",
]
