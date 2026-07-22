"""LLM Service: abstraction layer for language model integrations."""

from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.llm_service.knowledge_base import KnowledgeBase, get_knowledge_base
from floatchat.llm_service.ollama import OllamaLLMService

__all__ = ["AbstractLLMService", "OllamaLLMService", "QueryClassifier", "KnowledgeBase", "get_knowledge_base"]
