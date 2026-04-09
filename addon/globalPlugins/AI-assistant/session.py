# -*- coding: utf-8 -*-
from typing import Dict, List


class Session:
    """Minimal in-memory conversation session."""

    def __init__(self) -> None:
        """Initialize an empty session."""
        self._messages: List[Dict[str, str]] = []

    def append_user_message(self, content: str) -> None:
        """Append a user message to the session history.

        Args:
            content: The user message text.

        Raises:
            TypeError: If content is not a string.
        """
        self._append("user", content)

    def append_assistant_message(self, content: str) -> None:
        """Append an assistant message to the session history.

        Args:
            content: The assistant message text.

        Raises:
            TypeError: If content is not a string.
        """
        self._append("assistant", content)

    def append_system_message(self, content: str) -> None:
        """Append a system message to the session history.

        Args:
            content: The system instruction text.

        Raises:
            TypeError: If content is not a string.
        """
        self._append("system", content)

    def get_messages(self) -> List[Dict[str, str]]:
        """Return a copy of the current message history.

        Guarantees:
            - preserves message order
            - returns a shallow copy of the list
            - does not expose the internal list for mutation
        """
        return list(self._messages)

    def reset(self) -> None:
        """Clear all messages from the session history."""
        self._messages = []

    def _append(self, role: str, content: str) -> None:
        if not isinstance(content, str):
            raise TypeError("Message content must be a string.")
        self._messages.append({"role": role, "content": content})
