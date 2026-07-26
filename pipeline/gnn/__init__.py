"""GNN architecture: single-conversation message graph (GraphSAGE) + LLM reasoning stage."""

from .conversation_gnn import build_message_graph, MessageGraphSAGE, ConversationGraphState
from .llm_stage import run_llm_reasoning

__all__ = ["build_message_graph", "MessageGraphSAGE", "ConversationGraphState", "run_llm_reasoning"]
