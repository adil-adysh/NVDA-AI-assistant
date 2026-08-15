"""Benchmark embedding retrieval over a stub accessibility graph.

Run with the repository environment:

    .venv\\Scripts\\python.exe embedding_engine\\benchmarks\\benchmark_accessibility_graph.py

The benchmark intentionally measures complete-graph size separately from
retrieval quality.  A complete graph can fit in an embedding model's input
window while still being a poor retrieval unit because it produces one vector
for the entire page.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
import sys

import embedding_engine


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "addon" / "globalPlugins" / "AI-assistant"))


@dataclass(frozen=True)
class StubNode:
	role: str
	name: str
	section: str
	state: str = ""


@dataclass(frozen=True)
class StubSection:
	title: str
	nodes: tuple[StubNode, ...]
	label: str

	def as_text(self) -> str:
		lines = [f"Section: {self.title}", f"Task context: {self.label}"]
		lines.extend(
			f"- {node.role}: {node.name}{f' [{node.state}]' if node.state else ''}"
			for node in self.nodes
		)
		return "\n".join(lines)


CASES = {
	"vscode": (
		"Find the problems and diagnostics for the current file so I can fix the code.",
		(
			StubSection("Editor", (StubNode("editor", "main.py current function", "Editor"),), "active code"),
			StubSection("Problems", (StubNode("alert", "3 errors and 2 warnings", "Problems", "error"),), "diagnostics"),
			StubSection("Run and Debug", (StubNode("button", "Start debugging", "Run and Debug"),), "debug actions"),
			StubSection("Source Control", (StubNode("panel", "4 modified files", "Source Control"),), "changes"),
			StubSection("Terminal", (StubNode("terminal", "PowerShell test session", "Terminal"),), "command output"),
			StubSection("File Explorer", (StubNode("tree", "workspace README files", "File Explorer"),), "files"),
			StubSection("Extensions", (StubNode("link", "recommended extensions", "Extensions"),), "marketplace"),
		),
	),
	"form": (
		"Complete the required fields near the current focus and fix validation errors.",
		(
			StubSection("Shipping address", (StubNode("textbox", "Postal code", "Shipping address", "required"), StubNode("alert", "Postal code is required", "Shipping address", "error")), "form fields"),
			StubSection("Address actions", (StubNode("button", "Continue to delivery", "Address actions"),), "next step"),
			StubSection("Location", (StubNode("combobox", "Country and state", "Location"),), "address selection"),
			StubSection("Marketing", (StubNode("checkbox", "Newsletter preferences", "Marketing", "optional"),), "optional"),
			StubSection("Order summary", (StubNode("text", "Shipping estimate and tax", "Order summary"),), "summary"),
			StubSection("Footer", (StubNode("link", "Privacy and terms", "Footer"),), "legal links"),
		),
	),
	"checkout": (
		"Continue the purchase from the current payment step and find the next required action.",
		(
			StubSection("Checkout progress", (StubNode("navigation", "Cart Shipping Payment Review", "Checkout progress"),), "workflow"),
			StubSection("Payment", (StubNode("radio", "Credit card or PayPal", "Payment"), StubNode("textbox", "Card number and expiration date", "Payment", "required")), "current step"),
			StubSection("Review", (StubNode("button", "Continue to review order", "Review"),), "next action"),
			StubSection("Order total", (StubNode("text", "Delivery cost tax final amount", "Order total"),), "purchase total"),
			StubSection("Recommendations", (StubNode("link", "Frequently bought together", "Recommendations"),), "product suggestions"),
			StubSection("Reviews", (StubNode("text", "Customer reviews and product description", "Reviews"),), "product content"),
		),
	),
}


def cosine(left: list[float], right: list[float]) -> float:
	dot = sum(a * b for a, b in zip(left, right))
	left_norm = math.sqrt(sum(value * value for value in left))
	right_norm = math.sqrt(sum(value * value for value in right))
	return dot / (left_norm * right_norm) if left_norm and right_norm else -1.0


def complete_graph_text(sections: tuple[StubSection, ...]) -> str:
	return "\n\n".join(section.as_text() for section in sections)


def stress_graph_text(sections: tuple[StubSection, ...], repetitions: int = 180) -> str:
	"""Create a realistic large graph for the complete-input capacity check."""
	parts: list[str] = []
	for index in range(repetitions):
		for section in sections:
			parts.append(
				section.as_text().replace(
					f"Section: {section.title}",
					f"Section: {section.title} {index + 1}",
				)
			)
	return "\n\n".join(parts)


def run_model(model_id: str) -> None:
	engine = embedding_engine.EmbeddingEngine(model_id)
	metadata = embedding_engine.EmbeddingEngine.model_info(model_id) or {}
	print(f"\nMODEL {model_id} dimensions={metadata.get('dimensions')} max_tokens={metadata.get('max_tokens')}")
	stress = stress_graph_text(next(iter(CASES.values()))[1])
	stress_tokens = (len(stress.strip()) + 3) // 4
	print(
		f"large_complete_graph: chars={len(stress)} approx_tokens={stress_tokens} "
		f"fits_32k={stress_tokens <= int(metadata.get('max_tokens', 0))}"
	)
	probe = stress_graph_text(next(iter(CASES.values()))[1], repetitions=24)
	probe_tokens = (len(probe.strip()) + 3) // 4
	if probe_tokens <= int(metadata.get("max_tokens", 0)):
		vector = engine.embed(probe)
		print(f"large_complete_graph_probe: approx_tokens={probe_tokens} embed=OK dimensions={len(vector)}")
	for case_name, (query, sections) in CASES.items():
		query_text = query
		if "harrier" in model_id:
			query_text = f"Instruct: Retrieve the most relevant accessibility context.\nQuery: {query}"
		query_vector = engine.embed(query_text)
		section_texts = [section.as_text() for section in sections]
		vectors = engine.embed_batch(section_texts)
		ranked = sorted(
			enumerate(vectors), key=lambda item: cosine(query_vector, item[1]), reverse=True
		)
		complete = complete_graph_text(sections)
		approx_tokens = (len(complete.strip()) + 3) // 4
		print(
			f"{case_name}: complete_chars={len(complete)} "
			f"approx_tokens={approx_tokens} fits_32k={approx_tokens <= int(metadata.get('max_tokens', 0))}"
		)
		for rank, (index, vector) in enumerate(ranked[:4], 1):
			print(f"  {rank}. {cosine(query_vector, vector):.4f} {sections[index].title}")


if __name__ == "__main__":
	for model in ("harrier-oss-v1-270m", "granite-embedding-97m-multilingual-r2"):
		run_model(model)
