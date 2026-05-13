"""LLM provider adapters.

Each adapter implements :class:`~src.adapters.base.ModelAdapter` and returns
a :class:`~src.adapters.base.ModelResult`. Today only ``OpenAIAdapter`` is
wired to a real SDK; ``AnthropicAdapter`` and ``GoogleAdapter`` are stubs
that raise ``NotImplementedError`` until someone wires them up.
"""
