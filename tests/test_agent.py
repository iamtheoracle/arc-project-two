from core.agent import ArcAgent


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append((messages, tools))
        return {"message": next(self.responses)}


class FakePlugins:
    tools = [{"name": "calculate", "description": "calculate", "parameters": {"type": "object", "properties": {}}}]
    def get_tools_schema(self):
        return [{"type": "function", "function": {"name": "calculate", "description": "calculate",
                                                   "parameters": {"type": "object", "properties": {}}}}]
    def execute(self, name, arguments):
        return "2"


def test_unapproved_tool_is_never_executed():
    call = {"id": "call-1", "function": {"name": "calculate", "arguments": {"expression": "1+1"}}}
    llm = FakeLLM([{"role": "assistant", "content": "", "tool_calls": [call]},
                   {"role": "assistant", "content": "I need permission before using that tool."}])
    agent = ArcAgent.__new__(ArcAgent)
    agent.llm = llm
    agent.plugins = FakePlugins()
    agent.messages = [{"role": "system", "content": "system"}]
    agent.approved_tools = set()
    agent.tool_audit = None
    result = agent.chat("calculate 1+1")
    assert result == "I need permission before using that tool."
    assert agent.messages[-2]["content"].startswith("Permission denied")
