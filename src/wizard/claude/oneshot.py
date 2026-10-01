"""One question to Claude, outside the conversation, with no tools at all.

For the jobs that must not touch the conversation in the answer panel:
translating a selection, fixing its spelling, summarising it. Each runs as its
own short Claude Code session and is forgotten afterwards.

No tools, deliberately. The input is text copied from another application,
which may be an email, a web page or a document someone else wrote — i.e.
text that can contain instructions. A job whose only possible effect is
returning text cannot be talked into reading files or running commands, so
there is nothing to approve and nothing to go wrong.

The cost is a CLI start per job (a few seconds): these calls do not reuse the
answer panel's connection, precisely so they cannot see or alter it.
"""

from __future__ import annotations

#: Guard against a runaway answer; these are short transformations.
_MAX_TURNS = 1


async def _refuse(tool_name, tool_input, context):
    from claude_agent_sdk import PermissionResultDeny

    return PermissionResultDeny(message="Aucun outil pour cette tâche.", interrupt=True)


def options(system_prompt: str):
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        # An empty tool list: nothing to read, nothing to run.
        tools=[],
        allowed_tools=[],
        permission_mode="default",
        can_use_tool=_refuse,
        max_turns=_MAX_TURNS,
        system_prompt=system_prompt,
        env={"WIZARD_OWN_SESSION": "1"},
    )


async def ask_once(prompt: str, system_prompt: str, query=None) -> str:
    """Run one prompt and return Claude's text. Raises on failure.

    `query` is injectable so the tests can stand in for the SDK.
    """
    if query is None:
        from claude_agent_sdk import query as sdk_query

        query = sdk_query
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    parts: list[str] = []
    async for message in query(prompt=prompt, options=options(system_prompt)):
        if isinstance(message, AssistantMessage):
            parts.extend(b.text for b in message.content if isinstance(b, TextBlock))
        elif isinstance(message, ResultMessage) and message.is_error:
            raise RuntimeError((message.result or "Claude a échoué.").strip())
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError("Claude n'a rien répondu.")
    return text
