"""
ChatBot Platform — Prompt Builder
Builds LLM message arrays for project-scoped chat.
"""
from typing import Optional


def build_project_prompt(
    *,
    system_prompt: str,
    thread: list[dict],
    project_files: list[dict] = None,
) -> list[dict]:
    """
    Build the full OpenAI-format message array for a project chat.

    Args:
        system_prompt: The project's active system prompt (may be empty string).
        thread: List of {role, content} dicts (already normalized to user/assistant).

    Returns:
        OpenAI-compatible message list: [{role: system, content: ...}, ...thread]
    """
    messages: list[dict] = []

    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
        
    if project_files:
        files_context = "\n\n--- ADDITIONAL UPLOADED KNOWLEDGE ---\n"
        for f in project_files:
            files_context += f"File: {f.get('file_name')}\n{f.get('extracted_text')}\n\n"
        
        # If there's no system prompt, create one just for the files
        if not messages or messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": files_context})
        else:
            messages[0]["content"] += files_context

    for m in thread:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content})

    return messages


def build_summarization_prompt(messages: list[dict]) -> list[dict]:
    """
    Builds a summarisation request from a conversation.
    messages: list of {role, content} dicts.
    """
    transcript = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')}"
        for m in messages
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a conversation summariser.\n"
                "Summarise the conversation below into 2–4 sentences.\n\n"
                "Focus on:\n"
                "- The main topics discussed\n"
                "- Key decisions or outcomes\n"
                "- Any open questions or next steps\n\n"
                "Write in third person. Be concise and factual."
            ),
        },
        {
            "role": "user",
            "content": f"Conversation:\n{transcript}\n\nSummary:",
        },
    ]
