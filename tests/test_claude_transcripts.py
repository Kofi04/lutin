"""Reading Claude Code's own transcripts: tolerant, and strictly read-only."""

from __future__ import annotations

import json

from wizard.claude_transcripts import as_markdown, list_sessions, read_messages


def write_session(root, project, session, events):
    folder = root / project
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session}.jsonl"
    path.write_text(
        "\n".join(e if isinstance(e, str) else json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    return path


def user(text, **extra):
    return {"type": "user", "message": {"role": "user", "content": text}, **extra}


def assistant(blocks, **extra):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": blocks},
        **extra,
    }


def test_a_session_is_listed_with_its_ai_title(tmp_path):
    write_session(
        tmp_path,
        "C--proj",
        "s1",
        [
            user("fais un truc", cwd="C:/work/proj"),
            {"type": "ai-title", "aiTitle": "Un truc"},
        ],
    )

    sessions = list_sessions(tmp_path)
    assert [(s.title, s.project, s.session_id) for s in sessions] == [
        ("Un truc", "proj", "s1")
    ]


def test_without_a_title_the_first_prompt_is_used(tmp_path):
    write_session(tmp_path, "p", "s", [user("Pourquoi ce test échoue ?")])

    assert list_sessions(tmp_path)[0].title == "Pourquoi ce test échoue ?"


def test_the_most_recent_session_comes_first(tmp_path):
    import os

    old = write_session(tmp_path, "p", "old", [user("vieux")])
    write_session(tmp_path, "p", "new", [user("neuf")])
    os.utime(old, (1_000_000, 1_000_000))

    assert [s.session_id for s in list_sessions(tmp_path)] == ["new", "old"]


def test_messages_skip_thinking_and_tool_results(tmp_path):
    path = write_session(
        tmp_path,
        "p",
        "s",
        [
            user("Bonjour"),
            assistant(
                [
                    {"type": "thinking", "thinking": "secret reasoning"},
                    {"type": "text", "text": "Salut !"},
                    {"type": "tool_use", "name": "Bash", "input": {}},
                ]
            ),
            # The harness answering a tool call is not the person talking.
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "tool_result"}]},
            },
        ],
    )

    messages = read_messages(path)
    assert [(m.role, m.text) for m in messages] == [
        ("user", "Bonjour"),
        ("assistant", "Salut !"),
    ]
    assert messages[1].extras == ("outil : Bash",)
    assert all("secret" not in m.text for m in messages)


def test_subagent_sidechains_are_left_out(tmp_path):
    path = write_session(
        tmp_path, "p", "s", [user("à moi"), user("au sous-agent", isSidechain=True)]
    )

    assert [m.text for m in read_messages(path)] == ["à moi"]


def test_an_image_in_a_prompt_is_noted(tmp_path):
    path = write_session(
        tmp_path,
        "p",
        "s",
        [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "image"}, {"type": "text", "text": "et ça ?"}],
                },
            }
        ],
    )

    message = read_messages(path)[0]
    assert message.text == "et ça ?"
    assert "image" in message.extras


def test_garbage_lines_and_unknown_events_are_skipped(tmp_path):
    # The format is Claude Code's and changes between versions: nothing in it
    # may make the parser raise.
    path = write_session(
        tmp_path,
        "p",
        "s",
        [
            "{not json",
            "[1, 2]",
            {"type": "brand-new-event", "whatever": True},
            {"type": "user", "message": "not a dict"},
            user("survivant"),
        ],
    )

    assert [m.text for m in read_messages(path)] == ["survivant"]
    assert list_sessions(tmp_path)[0].title == "survivant"


def test_a_file_with_nothing_readable_is_not_listed(tmp_path):
    write_session(tmp_path, "p", "empty", [{"type": "cost-state"}])

    assert list_sessions(tmp_path) == []


def test_a_missing_directory_lists_nothing(tmp_path):
    assert list_sessions(tmp_path / "nope") == []


def test_reading_never_modifies_the_file(tmp_path):
    path = write_session(tmp_path, "p", "s", [user("intact"), assistant("ok")])
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    list_sessions(tmp_path)
    read_messages(path)
    as_markdown(list_sessions(tmp_path)[0])

    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_markdown_rendering(tmp_path):
    write_session(tmp_path, "p", "s", [user("Question"), assistant("Réponse")])

    text = as_markdown(list_sessions(tmp_path)[0])
    assert "**Vous**" in text and "**Claude**" in text
    assert "Réponse" in text
