"""hanko -- an agent that files receipts.

Named for the seal a person stamps on a document to commit to it: the
mark goes on before the outcome is known, and it cannot be taken back.
That is what a Decision Record is here. The commitment is hashed, and
the hash is the decision's identity, so a threshold moved after the
fact produces a new decision rather than an edited one.

Built for the RYO-CHAN platform, whose seven read-only research tools
this agent reasons over.
"""

__version__ = "0.1.0"
