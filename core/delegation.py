import re

PATTERNS = (
    r"\b(research|investigate|analy[sz]e|debug|troubleshoot|audit|architect)\b",
    r"\b(compare|evaluate|assess|design|calculate|solve|diagnose)\b",
    r"\b(build|implement|write code|review code|plan)\b.{0,60}\b(system|api|application|architecture|strategy|solution|project)\b",
    r"\b(step[- ]by[- ]step|technical deep dive|root cause)\b",
)

def select_agent(agent_id: str, user_text: str) -> tuple[str, str | None]:
    if agent_id != "bud":
        return agent_id, None
    if any(re.search(pattern, user_text.casefold()) for pattern in PATTERNS):
        return "oracle", "Clear specialist intent detected; BUD routed the task to ORACLE."
    return "bud", None
