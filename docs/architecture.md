# Architecture

The implementation-grounded architecture reference is maintained in
[architecture-current.md](architecture-current.md).

It covers:

- the three-process topology and Python/Rust/WebView2 ownership;
- Python package responsibilities and the composition root;
- context, use-case, provider, local-runtime, chat, tool, image, embedding,
  and observability interactions;
- the named-pipe protocol and Svelte Web UI modules;
- native Rust/PyO3/build dependencies;
- a package-level dependency graph; and
- the complete NVDA API boundary inventory and thread-affinity rules.

Protocol details remain in [ui-host-protocol.md](ui-host-protocol.md), host
lifecycle details in [ui-host-runtime.md](ui-host-runtime.md), and extension
guidance in [extending-use-cases.md](extending-use-cases.md).
