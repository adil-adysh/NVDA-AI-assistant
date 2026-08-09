# -*- coding: utf-8 -*-
"""LaTeX math → MathML conversion for markdown rendering.

Converts LaTeX math delimiters ($...$, $$...$$, \\(...\\), \\[...\\],
\\begin{env}...\\end{env}) into MathML markup so that downstream
markdown→HTML conversion produces accessible math.

Only content that contains recognizable LaTeX commands or math
operators (_, ^) is converted — plain text between $ delimiters
(such as shell variables like $PROFILE) is left untouched.
"""

from __future__ import annotations

import re
from typing import Callable

MathConverter = Callable[[str], str]


# ---------------------------------------------------------------------------
# Lazy-loaded LaTeX → MathML converter
# ---------------------------------------------------------------------------


def _load_math_converter() -> MathConverter | None:
	"""Return the latex2mathml converter, or None if unavailable."""
	try:
		from latex2mathml.converter import convert

		return convert
	except Exception:
		return None


# ---------------------------------------------------------------------------
# Known LaTeX math environments
# ---------------------------------------------------------------------------

MATH_ENVIRONMENTS: tuple[str, ...] = (
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


# ---------------------------------------------------------------------------
# LaTeX math content detection
# ---------------------------------------------------------------------------

# Regex matching backslash-commands that strongly indicate LaTeX math.
# The trailing \w+ fallback catches any other \command not explicitly
# listed (e.g. user-defined macros, less-common symbols).
_LATEX_MATH_INDICATORS = re.compile(
	r"\\(?:"
	# Greek letters (lowercase)
	r"alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|"
	r"lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega|"
	# Greek letters (uppercase)
	r"Alpha|Beta|Gamma|Delta|Epsilon|Zeta|Eta|Theta|Iota|Kappa|"
	r"Lambda|Mu|Nu|Xi|Omicron|Pi|Rho|Sigma|Tau|Upsilon|Phi|Chi|Psi|Omega|"
	# Functions & operators
	r"frac|sqrt|lim|int|sum|prod|oint|iint|iiint|"
	r"sin|cos|tan|cot|sec|csc|"
	r"log|ln|exp|max|min|gcd|hom|ker|Pr|"
	r"left|right|big|Big|bigg|Bigg|"
	r"partial|nabla|infty|emptyset|varnothing|forall|exists|neg|lnot|"
	# Decorations & accents
	r"bar|hat|vec|dot|ddot|tilde|widehat|widetilde|"
	r"overline|underline|overrightarrow|overleftarrow|"
	# Binary operators & relations
	r"pm|mp|times|div|ast|star|circ|bullet|cdot|"
	r"leq|geq|neq|equiv|approx|sim|simeq|propto|ll|gg|"
	r"subset|supset|subseteq|supseteq|in|notin|ni|"
	r"cup|cap|setminus|land|lor|wedge|vee|"
	# Arrows
	r"rightarrow|leftarrow|Rightarrow|Leftarrow|leftrightarrow|"
	r"longrightarrow|longleftarrow|mapsto|longmapsto|"
	r"to|gets|implies|iff|"
	# Dots & spacing
	r"ldots|cdots|vdots|ddots|"
	r"quad|qquad|,|:|;|!|"
	# Font / style commands
	r"mathrm|mathbf|mathsf|mathtt|mathit|mathcal|mathbb|mathfrak|mathscr|"
	r"text|displaystyle|textstyle|scriptstyle|scriptscriptstyle|"
	# Environments
	r"begin|end|"
	# Catch-all: any other \command not listed above
	r"\w+"
	r")"
)

# Subscript / superscript operators also indicate math content.
_MATH_SUB_SUPER = re.compile(r"[_^]")


def _looks_like_math(text: str) -> bool:
	"""Return True if *text* contains LaTeX math patterns.

	Checks for:
	- Backslash-commands (\\\\alpha, \\\\frac, \\\\mathbb{R}, etc.)
	- Subscript/superscript operators (_, ^)

	Plain text containing only alphanumeric characters, spaces, and
	punctuation will return False — preventing false positives on
	shell variables ($PROFILE), currency ($50), etc.
	"""
	if not text or not text.strip():
		return False
	if _LATEX_MATH_INDICATORS.search(text):
		return True
	if _MATH_SUB_SUPER.search(text):
		return True
	return False


# ---------------------------------------------------------------------------
# Delimiter patterns (pre-compiled)
# ---------------------------------------------------------------------------


def _build_environment_pattern() -> str:
	"""Build a regex pattern for \\\\begin{env}...\\\\end{env} blocks."""
	escaped = "|".join(re.escape(env) for env in MATH_ENVIRONMENTS)
	return rf"\\begin\{{{escaped}\}}(.*?)\\end\{{\1\}}"


# Inline $...$ with false-positive guards:
#   - opening $ must NOT be preceded by \ (escaped) or another $
#   - opening $ must NOT be followed by digit, whitespace, or another $
#     (avoids $50, $ PROFILE, $$)
#   - closing $ must NOT be preceded by whitespace
_INLINE_DOLLAR_RE = re.compile(
	r"(?<!\\)(?<!\$)\$(?![\d\s\$])(.+?)(?<!\s)\$(?!\$)",
	re.DOTALL,
)

# Block $$...$$ (display math)
_BLOCK_DOLLAR_RE = re.compile(
	r"(?<!\\)\$\$(.+?)\$\$",
	re.DOTALL,
)

# Inline \(...\) — unambiguous LaTeX, always math
_INLINE_PAREN_RE = re.compile(
	r"\\\((.*?)\\\)",
	re.DOTALL,
)

# Block \[...\] — unambiguous LaTeX, always math
_BLOCK_BRACKET_RE = re.compile(
	r"\\\[(.*?)\\\]",
	re.DOTALL,
)

# Non-standard bracket block: [...] on separate lines.
# Kept for backwards compatibility; guard still applies.
_BARE_BRACKET_BLOCK_RE = re.compile(
	r"(?m)^\s*\[\s*\n(.*?)\n\s*\]",
	re.DOTALL,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert_math_delimiters_to_mathml(text: str) -> str:
	"""Convert LaTeX math delimiters into MathML markup.

	Supported delimiters:
	    $...$       inline math  (content must pass LaTeX detection)
	    $$...$$     display math (content must pass LaTeX detection)
	    \\(...\\)   inline math  (unambiguous)
	    \\[...\\]   display math (unambiguous)
	    \\begin{env}...\\end{env}  named math environments

	Content between delimiters is only converted when it contains
	recognizable LaTeX commands or math operators (_, ^), avoiding
	false positives on currency amounts, shell/PowerShell variables,
	and other non-math uses of $.
	"""
	if not isinstance(text, str) or not text:
		return text

	convert = _load_math_converter()
	if convert is None:
		return text

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	def _try_convert(latex: str, display: str = "inline") -> str | None:
		"""Try to convert LaTeX to MathML; return None on failure."""
		stripped = latex.strip()
		if not stripped:
			return None
		try:
			return convert(stripped, display=display)
		except Exception:
			return None

	def _captured(match: re.Match[str]) -> str:
		"""Return the highest-numbered capture group from *match*.

		Works across all our patterns:
		- Single-group patterns ($$...$$, \\(...\\), etc.) → group 1
		- Two-group environment pattern → group 2 (the body)
		"""
		return match.group(match.lastindex or 1)

	def _block_replacer(match: re.Match[str]) -> str:
		latex = _captured(match)
		if not _looks_like_math(latex):
			return match.group(0)
		converted = _try_convert(latex, display="block")
		return converted if converted is not None else match.group(0)

	def _inline_replacer(match: re.Match[str]) -> str:
		latex = _captured(match)
		if not _looks_like_math(latex):
			return match.group(0)
		converted = _try_convert(latex, display="inline")
		return converted if converted is not None else match.group(0)

	# ------------------------------------------------------------------
	# Apply patterns in order (block → inline, most-specific first)
	# ------------------------------------------------------------------

	# 1. Named math environments: \begin{equation}...\end{equation}
	text = re.sub(_build_environment_pattern(), _block_replacer, text, flags=re.DOTALL)

	# 2. Display math: \[...\] and $$...$$
	text = _BLOCK_BRACKET_RE.sub(_block_replacer, text)
	text = _BLOCK_DOLLAR_RE.sub(_block_replacer, text)

	# 3. Non-standard bare-bracket blocks (legacy compatibility)
	text = _BARE_BRACKET_BLOCK_RE.sub(_block_replacer, text)

	# 4. Inline math: \(...\) and $...$
	text = _INLINE_PAREN_RE.sub(_inline_replacer, text)
	text = _INLINE_DOLLAR_RE.sub(_inline_replacer, text)

	return text
