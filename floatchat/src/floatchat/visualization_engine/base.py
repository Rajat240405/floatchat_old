"""Abstract interface for visualization engines."""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from floatchat.models import ParsedIntent


class AbstractVisualizationEngine(ABC):
    """Render Plotly figures from DataFrames.

    The engine selects the graph type based **only** on
    :attr:`ParsedIntent.intent` and never touches raw NetCDF or the LLM.
    """

    @abstractmethod
    def render(
        self,
        intent: ParsedIntent,
        df: pd.DataFrame,
    ) -> dict[str, Any]:
        """Produce a Plotly JSON figure dict.

        Args:
            intent: The parsed intent (used for routing and titles).
            df: Tidy DataFrame produced by the NetCDF reader.

        Returns:
            A JSON-serialisable Plotly figure dictionary.

        Raises:
            floatchat.exceptions.VisualizationError: If rendering fails.
        """
        ...
