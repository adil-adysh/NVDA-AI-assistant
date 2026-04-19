# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Callable

MathConverter = Callable[[str], str]


def _load_math_converter() -> MathConverter | None:
    try:
        from latex2mathml.converter import convert

        return convert
    except Exception:
        return None


def convert_math_delimiters_to_mathml(text: str) -> str:
    """Convert inline and block LaTeX math into MathML markup."""
    if not isinstance(text, str) or not text:
        return text

    convert = _load_math_converter()
    if convert is None:
        return text

    def block_repl(match: re.Match[str]) -> str:
        latex = match.group(1)
        try:
            return convert(latex)
        except Exception:
            return match.group(0)

    def inline_repl(match: re.Match[str]) -> str:
        latex = match.group(1)
        try:
            return convert(latex)
        except Exception:
            return match.group(0)

    text = re.sub(r"\$\$(.*?)\$\$", block_repl, text, flags=re.DOTALL)
    text = re.sub(r"\$(.*?)\$", inline_repl, text)
    return text


def contains_mathml(text: str) -> bool:
    if not isinstance(text, str):
        return False
    lower_text = text.lower()
    return "<math" in lower_text or "</math>" in lower_text
