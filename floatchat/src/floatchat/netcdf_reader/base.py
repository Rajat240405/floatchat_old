"""Abstract interface for NetCDF readers."""

from abc import ABC, abstractmethod

import pandas as pd

from floatchat.repository_service import NetCDFDataset


class AbstractNetCDFReader(ABC):
    """Extract requested variables from an in-memory Argo NetCDF profile.

    Implementations must inspect the dataset dynamically and never assume
    that a given variable exists.
    """

    @abstractmethod
    def read(
        self,
        ncd: NetCDFDataset,
        variables: list[str],
    ) -> pd.DataFrame:
        """Extract *variables* plus pressure/depth into a tidy DataFrame.

        Args:
            ncd: In-memory NetCDF dataset wrapper.
            variables: List of requested Argo variable names (e.g. ``DOXY``).

        Returns:
            A :class:`pandas.DataFrame` with one row per (profile, level).

        Raises:
            floatchat.exceptions.NetCDFReadError: On missing mandatory
                variables or read failures.
        """
        ...
