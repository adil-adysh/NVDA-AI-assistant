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


MATH_ENVIRONMENTS = (
    "equation",
    "equation*",
    "align",
    "align*",
    "aligned",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "split",
    "cases",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "Vmatrix",
    "array",
    "alignedat",
    "smallmatrix",
)


def _looks_like_math(text: str) -> bool:
    return bool(
        re.search(
            r"\\(?:frac|sqrt|lim|int|sum|prod|sin|cos|tan|cot|sec|csc|log|ln|exp|left|right|pi|theta|alpha|beta|gamma|delta|epsilon|phi|psi|mu|nu|xi|omega|mathrm|mathbf|text|infty|cdot|le|ge|approx|rightarrow|to)|[_^]",
            text,
        )
    )


def _build_environment_pattern() -> str:
    escaped = "|".join(re.escape(env) for env in MATH_ENVIRONMENTS)
    return rf"\\begin\{{({escaped})\}}(.*?)\\end\{{\1\}}"


def convert_math_delimiters_to_mathml(text: str) -> str:
    """Convert inline and block LaTeX math into MathML markup."""
    if not isinstance(text, str) or not text:
        return text

    convert = _load_math_converter()
    if convert is None:
        return text

    def _try_convert(latex: str, display: str = "inline") -> str | None:
        if not latex or not latex.strip():
            return None
        try:
            return convert(latex.strip(), display=display)
        except Exception:
            return None

    def _match_content(match: re.Match[str]) -> str:
        return match.group(match.lastindex)

    def block_repl(match: re.Match[str]) -> str:
        latex = _match_content(match)
        converted = _try_convert(latex, display="block")
        return converted if converted is not None else match.group(0)

    def inline_repl(match: re.Match[str]) -> str:
        latex = _match_content(match)
        converted = _try_convert(latex, display="inline")
        return converted if converted is not None else match.group(0)

    def bracket_block_repl(match: re.Match[str]) -> str:
        latex = match.group(1)
        if not _looks_like_math(latex):
            return match.group(0)
        converted = _try_convert(latex, display="block")
        return converted if converted is not None else match.group(0)

    text = re.sub(_build_environment_pattern(), block_repl, text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*\[\s*\n(.*?)\n\s*\]", bracket_block_repl, text, flags=re.DOTALL)
    text = re.sub(r"\\\[(.*?)\\\]", block_repl, text, flags=re.DOTALL)
    text = re.sub(r"\$\$(.*?)\$\$", block_repl, text, flags=re.DOTALL)
    text = re.sub(r"\\\((.*?)\\\)", inline_repl, text, flags=re.DOTALL)
    text = re.sub(r"\$(.*?)\$", inline_repl, text, flags=re.DOTALL)
    return text
