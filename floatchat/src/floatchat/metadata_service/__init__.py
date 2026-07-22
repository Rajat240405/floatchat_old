"""Metadata Service: loads and searches the Argo BGC bio-profile index."""

from floatchat.metadata_service.base import AbstractMetadataService
from floatchat.metadata_service.gdac import GDACMetadataService

__all__ = ["AbstractMetadataService", "GDACMetadataService"]
