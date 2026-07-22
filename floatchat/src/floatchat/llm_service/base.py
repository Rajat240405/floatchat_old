"""Abstract interface for LLM services."""

from abc import ABC, abstractmethod


class AbstractLLMService(ABC):
    """Generate text responses from a language model.

    Implementations are responsible for prompt formatting, API communication,
    and error handling. The backend never knows which provider is used.
    """

    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Send *prompt* to the LLM and return the generated text.

        Args:
            prompt: The user message or instruction.
            system: Optional system prompt to set model behavior.

        Returns:
            The generated text response (stripped of leading/trailing whitespace).

        Raises:
            floatchat.exceptions.FloatChatError: If the LLM request fails.
        """
        ...
