# Python development and tests

Python development uses [uv](https://docs.astral.sh/uv/) and Python 3.13.12,
matching the sibling NVDA source checkout. Clone NVDA beside this repository:

~~~powershell
cd ..
git clone https://github.com/nvaccess/nvda.git nvda
git -C nvda checkout 797a881381f8bedabc13456d3aa76bdd77d71503
cd NVDA-AI-assistant
uv sync --locked
~~~

The pytest bootstrap resolves `../nvda` relative to this repository and adds
NVDA's `source` and `miscDeps/python` directories itself. No `PYTHONPATH` or
machine-specific path is required. A missing checkout produces an actionable
pytest startup error instead of installing or creating a fake NVDA package.
The tested NVDA commit is recorded in `nvda-source.toml`; local runs warn on a
different revision and CI rejects it.

Run the suite and lint checks with:

~~~powershell
uv run pytest
uv run ruff check .
~~~

The default suite uses importable NVDA API definitions but does not require
NVDA's native build outputs. To prepare and build the optional runtime tier:

~~~powershell
git -C ../nvda submodule update --init --recursive
cd ../nvda
uv sync
uv run scons
cd ../NVDA-AI-assistant
~~~

The integration bootstrap also discovers the sibling checkout's `.venv` for
NVDA's locked runtime-only dependencies. Then run the runtime-bound tier
explicitly:

~~~powershell
uv run pytest -m nvda_integration
~~~

Run one file or one test by passing its pytest node ID:

~~~powershell
uv run pytest tests/integration/test_nvda_imports.py
uv run pytest tests/integration/test_nvda_imports.py::test_nvda_api_definitions_come_from_sibling_checkout
~~~

Cross-component integration tests live under `tests/integration/`. Controlled
providers use `threading.Event` barriers so tests decide exactly when a request
streams, completes, or fails. Race tests should assert the intended ordering at
the provider, session, persistence, and presentation boundaries and must not use
arbitrary sleeps. The fakes implement the provider contract and never contact a
paid or external model API.

Managed llama.cpp and LiteRT-LM process/cache behavior is specified in
`docs/local-provider-lifecycle.md`. Its integration tests keep the real
supervisor locking, startup fingerprinting, invalidation, and cleanup code in
the loop while replacing only the heavyweight OS process and health boundary.

The standalone suite imports real NVDA API definitions. Live process state
(focus objects, the event loop, GUI objects, speech, and native helper DLLs)
is still replaced at narrow test boundaries when a running, built NVDA process
would otherwise be required. The normal add-on package build remains `scons`.
The bundle writer rejects test directories, test modules, pytest configuration,
and bytecode unconditionally, so none of these files can enter an
`.nvda-addon` archive.
