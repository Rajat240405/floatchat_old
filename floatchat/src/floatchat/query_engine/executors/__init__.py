"""Execution components for the QueryEngine (Milestone 4 decomposition).

Each module owns exactly one execution responsibility. All executors share
the uniform protocol::

    execute_<kind>(deps: ExecutionDeps, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse

``ExecutionDeps`` (see ``floatchat.query_engine.dispatch``) carries the
injected runtime collaborators; executors never construct services or read
global state beyond ``floatchat.config.settings``.
"""



