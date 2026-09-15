"""
Graph Orchestration: LangGraph workflow compilation for SentinelPR.
"""

from typing import Any, Dict, List, Optional
from langgraph.graph import END, START, StateGraph

from sentinel.agents.anti_bloat import anti_bloat_agent_node
from sentinel.agents.consolidator import consolidator_agent_node
from sentinel.agents.critic import critic_agent_node
from sentinel.agents.logic import logic_agent_node
from sentinel.agents.risk import risk_agent_node
from sentinel.agents.security import security_agent_node
from sentinel.agents.test_synthesizer import test_synthesis_node
from sentinel.agents.triage import triage_agent_node
from sentinel.state import PRReviewState


def create_sentinel_graph():
    """
    Compiles the SentinelPR StateGraph.
    Flow:
      START -> triage -> [logic, security, anti_bloat, risk] in parallel
            -> test_synthesizer (fan-in)
            -> critic
            -> consolidator
            -> END
    """
    builder = StateGraph(PRReviewState)

    # Add Nodes
    builder.add_node("triage", triage_agent_node)
    builder.add_node("logic", logic_agent_node)
    builder.add_node("security", security_agent_node)
    builder.add_node("anti_bloat", anti_bloat_agent_node)
    builder.add_node("risk", risk_agent_node)
    builder.add_node("test_synthesizer", test_synthesis_node)
    builder.add_node("critic", critic_agent_node)
    builder.add_node("consolidator", consolidator_agent_node)

    # Connect Edges
    builder.add_edge(START, "triage")

    # Parallel Fan-Out
    builder.add_edge("triage", "logic")
    builder.add_edge("triage", "security")
    builder.add_edge("triage", "anti_bloat")
    builder.add_edge("triage", "risk")

    # Fan-In to Test Synthesizer
    builder.add_edge("logic", "test_synthesizer")
    builder.add_edge("security", "test_synthesizer")
    builder.add_edge("anti_bloat", "test_synthesizer")
    builder.add_edge("risk", "test_synthesizer")

    # Pipeline Continuation
    builder.add_edge("test_synthesizer", "critic")
    builder.add_edge("critic", "consolidator")
    builder.add_edge("consolidator", END)

    return builder.compile()


def review_pr(
    diff: str,
    head_files: Dict[str, str],
    base_files: Dict[str, str] = None,
    uninspected_files: List[str] = None,
) -> Dict[str, Any]:
    """
    High-level entry point to execute SentinelPR on a pull request.
    """
    if base_files is None:
        base_files = {}
    if uninspected_files is None:
        uninspected_files = []

    initial_state: PRReviewState = {
        "diff": diff,
        "base_files": base_files,
        "head_files": head_files,
        "changed_files": [],
        "hunks": [],
        "symbols": [],
        "candidate_findings": [],
        "repro_tests": {},
        "verified_findings": [],
        "risk_assessment": None,
        "risk_indicators": [],
        "uninspected_files": uninspected_files,
        "review_outcome": None,
        "consolidated_report": None,
    }

    graph = create_sentinel_graph()
    final_state = graph.invoke(initial_state)
    return final_state
