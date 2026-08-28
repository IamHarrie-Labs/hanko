"""Decision Records: verdicts that cite their evidence and pre-register their own falsification."""

from .convergence import ConvergenceReport, Echo, assess_convergence
from .engine import ENGINE_VERSION, DecisionInputs, decide
from .ledger import (
    DecisionLedger,
    DuplicateDecision,
    ReplayMismatch,
    assert_reproduces,
    replay_decision,
)
from .policy import Policy
from .quality import EvidenceQuality, Gap, GapKind, assess_quality
from .reading import Interpreter, KeywordInterpreter, Reading, Stance, read_all
from .record import (
    DecisionRecord,
    Falsifier,
    MarketFacts,
    Outcome,
    RuleFiring,
    Verdict,
)

__all__ = [
    "ConvergenceReport",
    "DecisionInputs",
    "DecisionLedger",
    "DecisionRecord",
    "DuplicateDecision",
    "ENGINE_VERSION",
    "Echo",
    "EvidenceQuality",
    "Falsifier",
    "Gap",
    "GapKind",
    "Interpreter",
    "KeywordInterpreter",
    "MarketFacts",
    "Outcome",
    "Policy",
    "Reading",
    "ReplayMismatch",
    "RuleFiring",
    "Stance",
    "Verdict",
    "assert_reproduces",
    "assess_convergence",
    "assess_quality",
    "decide",
    "read_all",
    "replay_decision",
]
