"""
Curated test datasets for Harrier embedding model validation.

Every test case carries metadata (id, category, language, difficulty,
expected_relationship) so the test runner can produce structured reports.

Data categories:
  01_numerical_parity  — inputs for HF vs Rust tensor comparison
  02_semantic_similarity — positive / hard-negative / unrelated pairs
  03_retrieval         — document collections with relevance labels
  04_hard_negatives    — lexically similar but semantically different docs
  05_multilingual      — cross-lingual pairs and retrieval
  06_nvda_realworld    — screen-reader and accessibility text
  07_long_context      — documents at various token lengths
  08_edge_cases        — empty, punctuation, code, emoji, etc.
  09_regression        — known-bug regression tests

All strings are hand-curated to represent realistic NVDA AI Assistant content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Shared type
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    """A single test data point with full metadata."""

    id: str
    category: str
    query: str | None = None
    documents: list[str] = field(default_factory=list)
    relevant_document_ids: list[int] = field(default_factory=list)
    text_a: str | None = None
    text_b: str | None = None
    language: str = "en"
    difficulty: str = "medium"
    expected_relationship: str = "unknown"
    note: str = ""


# ---------------------------------------------------------------------------
# 01 — Numerical Parity inputs
# ---------------------------------------------------------------------------

NUMERICAL_PARITY_SHORT_QUERIES: list[dict[str, Any]] = [
    {"id": "np_query_001", "text": "How do I change my Windows password?", "lang": "en"},
    {"id": "np_query_002", "text": "Best practices for Python virtual environments", "lang": "en"},
    {"id": "np_query_003", "text": "How to fix Docker permission denied error", "lang": "en"},
    {"id": "np_query_004", "text": "NVDA screen reader configuration guide", "lang": "en"},
    {"id": "np_query_005", "text": "Rust async programming with tokio", "lang": "en"},
    {"id": "np_query_006", "text": "Git merge conflict resolution steps", "lang": "en"},
    {"id": "np_query_007", "text": "Windows PowerShell scripting tutorial", "lang": "en"},
    {"id": "np_query_008", "text": "How to optimize SQL query performance", "lang": "en"},
    {"id": "np_query_009", "text": "Bluetooth audio device troubleshooting", "lang": "en"},
    {"id": "np_query_010", "text": "Machine learning model deployment strategies", "lang": "en"},
    {"id": "np_query_011", "text": "Accessible web design ARIA landmarks", "lang": "en"},
    {"id": "np_query_012", "text": "How to create a system restore point", "lang": "en"},
    {"id": "np_query_013", "text": "Python list comprehension vs generator expression", "lang": "en"},
    {"id": "np_query_014", "text": "NGINX reverse proxy configuration example", "lang": "en"},
    {"id": "np_query_015", "text": "How to recover deleted files on Windows 11", "lang": "en"},
    {"id": "np_query_016", "text": "Kubernetes pod scheduling best practices", "lang": "en"},
    {"id": "np_query_017", "text": "CSS flexbox vs grid layout comparison", "lang": "en"},
    {"id": "np_query_018", "text": "How to encrypt files with GPG on Linux", "lang": "en"},
    {"id": "np_query_019", "text": "TypeScript type narrowing techniques", "lang": "en"},
    {"id": "np_query_020", "text": "Audio latency reduction in DAW software", "lang": "en"},
]

NUMERICAL_PARITY_DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "np_doc_001",
        "text": (
            "To change your Windows password, open Settings, navigate to Accounts, "
            "select Sign-in options, and click Change under Password. You will need "
            "to enter your current password before setting a new one."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_002",
        "text": (
            "Python virtual environments allow you to isolate project dependencies. "
            "Use `python -m venv .venv` to create one, then activate with "
            "`.venv\\Scripts\\activate` on Windows or `source .venv/bin/activate` on Unix."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_003",
        "text": (
            "The Docker permission denied error typically occurs when your user is not "
            "in the docker group. Run `sudo usermod -aG docker $USER` and log out and "
            "back in for the change to take effect."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_004",
        "text": (
            "NVDA (NonVisual Desktop Access) is a free, open-source screen reader for "
            "Windows. It supports web browsing, email, office applications, and "
            "programming tools through synthesized speech and braille output."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_005",
        "text": (
            "Tokio is an asynchronous runtime for Rust that provides building blocks "
            "for writing reliable network applications. It uses an event-driven, "
            "non-blocking I/O model with work-stealing scheduler."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_006",
        "text": (
            "When Git encounters a merge conflict, it marks the conflicting sections "
            "with <<<<<<<, =======, and >>>>>>> markers. Resolve conflicts by editing "
            "the files, then use `git add` and `git commit` to complete the merge."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_007",
        "text": (
            "PowerShell is a task automation framework from Microsoft, consisting of "
            "a command-line shell and scripting language. It is built on .NET and "
            "provides full access to COM and WMI."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_008",
        "text": (
            "To optimize SQL query performance, start by analyzing query execution "
            "plans with EXPLAIN. Add appropriate indexes, avoid SELECT *, use JOINs "
            "instead of subqueries, and consider query caching strategies."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_009",
        "text": (
            "Bluetooth audio issues can often be resolved by removing and re-pairing "
            "the device, updating Bluetooth drivers, disabling audio enhancements, "
            "or running the Windows Bluetooth troubleshooter."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_010",
        "text": (
            "ML model deployment involves packaging a trained model and serving it "
            "via REST API, gRPC, or edge devices. Common frameworks include TensorFlow "
            "Serving, TorchServe, ONNX Runtime, and Triton Inference Server."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_011",
        "text": (
            "ARIA landmarks help screen reader users navigate web pages by identifying "
            "regions like banner, navigation, main, complementary, and contentinfo. "
            "Use role attributes to make your site accessible."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_012",
        "text": (
            "System Restore in Windows creates snapshots of system files and registry "
            "settings. To create a restore point, search for 'Create a restore point' "
            "in the Start menu and click Create in the System Protection tab."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_013",
        "text": (
            "List comprehensions in Python create lists eagerly in memory using "
            "[expr for x in iterable], while generator expressions use parentheses "
            "and produce values lazily, saving memory for large sequences."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_014",
        "text": (
            "An NGINX reverse proxy sits between clients and backend servers, "
            "forwarding requests and returning responses. Configure it with "
            "`proxy_pass` directives in server blocks for load balancing and caching."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_015",
        "text": (
            "To recover deleted files on Windows 11, first check the Recycle Bin. "
            "If emptied, use File History backup, Windows File Recovery tool, or "
            "third-party recovery software. Act quickly to avoid overwriting data."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_016",
        "text": (
            "Kubernetes schedules pods to nodes based on resource requests, affinity "
            "rules, taints and tolerations, and topology spread constraints. Use "
            "requests/limits to ensure fair resource allocation across the cluster."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_017",
        "text": (
            "CSS Flexbox is designed for one-dimensional layouts (rows or columns), "
            "while CSS Grid excels at two-dimensional layouts. Use Flexbox for "
            "navigation bars and Grid for overall page structure."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_018",
        "text": (
            "GPG (GNU Privacy Guard) encrypts files using public-key cryptography. "
            "Use `gpg --encrypt --recipient user@example.com file.txt` to encrypt, "
            "and `gpg --decrypt file.txt.gpg` to decrypt with your private key."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_019",
        "text": (
            "TypeScript type narrowing refines union types through control flow "
            "analysis. Use typeof checks, instanceof, discriminated unions with "
            "literal type properties, and custom type guard functions."
        ),
        "lang": "en",
    },
    {
        "id": "np_doc_020",
        "text": (
            "Audio latency in DAW (Digital Audio Workstation) software can be reduced "
            "by using ASIO drivers, increasing buffer size, disabling plugin delay "
            "compensation, and ensuring your audio interface has up-to-date firmware."
        ),
        "lang": "en",
    },
]

NUMERICAL_PARITY_MULTILINGUAL: list[dict[str, Any]] = [
    {"id": "np_ml_001", "text": "मैं अपना विंडोज पासवर्ड कैसे बदलूं?", "lang": "hi"},
    {"id": "np_ml_002", "text": "Comment changer mon mot de passe Windows?", "lang": "fr"},
    {"id": "np_ml_003", "text": "Wie ändere ich mein Windows-Passwort?", "lang": "de"},
    {"id": "np_ml_004", "text": "Cómo cambiar mi contraseña de Windows?", "lang": "es"},
    {"id": "np_ml_005", "text": "Como alterar minha senha do Windows?", "lang": "pt"},
    {"id": "np_ml_006", "text": "Как изменить пароль Windows?", "lang": "ru"},
    {"id": "np_ml_007", "text": "كيفية تغيير كلمة مرور ويندوز؟", "lang": "ar"},
    {"id": "np_ml_008", "text": "Windowsのパスワードを変更する方法", "lang": "ja"},
    {"id": "np_ml_009", "text": "Windows 비밀번호 변경 방법", "lang": "ko"},
    {"id": "np_ml_010", "text": "如何更改Windows密码", "lang": "zh"},
    {"id": "np_ml_011", "text": "ગુજરાતીમાં ટેક્સ્ટ પ્રોસેસિંગ કેવી રીતે કરવું", "lang": "gu"},
    {"id": "np_ml_012", "text": "Python वर्चुअल एनवायरनमेंट कैसे सेटअप करें", "lang": "hi"},
    {"id": "np_ml_013", "text": "Configuration de NVDA lecteur d'écran", "lang": "fr"},
    {"id": "np_ml_014", "text": "Einrichtung eines barrierefreien Webdesigns", "lang": "de"},
    {"id": "np_ml_015", "text": "Configuración de lector de pantalla NVDA", "lang": "es"},
    {"id": "np_ml_016", "text": "إعداد قارئ الشاشة NVDA", "lang": "ar"},
    {"id": "np_ml_017", "text": "NVDAスクリーンリーダーの設定", "lang": "ja"},
    {"id": "np_ml_018", "text": "Python 가상 환경 모범 사례", "lang": "ko"},
    {"id": "np_ml_019", "text": "Rust异步编程与tokio框架", "lang": "zh"},
    {"id": "np_ml_020", "text": "Resolução de conflitos de merge no Git", "lang": "pt"},
]

NUMERICAL_PARITY_LONG: list[dict[str, Any]] = [
    {
        "id": "np_long_001",
        "text": (
            "The Python programming language is widely used for scientific computing, "
            "web development, automation, and artificial intelligence. Its extensive "
            "standard library and third-party ecosystem make it versatile. Python "
            "supports multiple programming paradigms including procedural, "
            "object-oriented, and functional programming. The language emphasizes "
            "code readability with significant whitespace. Python 3 introduced many "
            "improvements over Python 2, including better Unicode handling, "
            "division operator changes, and print as a function. The Global "
            "Interpreter Lock (GIL) has been a topic of much discussion, though "
            "Python 3.13 introduces an experimental free-threaded mode. "
            "Popular web frameworks include Django, Flask, and FastAPI. "
            "For data science, NumPy, Pandas, and Matplotlib form the core stack."
        ),
        "lang": "en",
    },
    {
        "id": "np_long_002",
        "text": (
            "Accessibility in software ensures that applications can be used by "
            "people with various disabilities. Screen readers like NVDA convert "
            "on-screen text and UI elements into speech or braille output. Web "
            "Content Accessibility Guidelines (WCAG) define standards for web "
            "accessibility at levels A, AA, and AAA. ARIA (Accessible Rich Internet "
            "Applications) provides additional semantics for dynamic content and "
            "custom widgets. Keyboard navigation, sufficient color contrast, and "
            "alternative text for images are fundamental accessibility requirements. "
            "Automated testing tools like axe-core, Lighthouse, and WAVE can detect "
            "many accessibility issues, but manual testing with assistive "
            "technologies remains essential for comprehensive evaluation."
        ),
        "lang": "en",
    },
    {
        "id": "np_long_003",
        "text": (
            "Machine learning encompasses supervised, unsupervised, and reinforcement "
            "learning paradigms. Supervised learning uses labeled training data to "
            "predict outputs for new inputs. Common algorithms include linear "
            "regression, decision trees, random forests, support vector machines, "
            "and neural networks. Deep learning, a subset of machine learning, uses "
            "multi-layered neural networks to automatically learn hierarchical "
            "feature representations. Transformer architectures have revolutionized "
            "natural language processing since their introduction in 2017. Models "
            "like BERT, GPT, and T5 demonstrate remarkable performance on tasks "
            "including translation, summarization, and question answering."
        ),
        "lang": "en",
    },
    {
        "id": "np_long_004",
        "text": (
            "The Rust programming language emphasizes memory safety without garbage "
            "collection through its ownership system. Variables have a single owner "
            "at any time, and the compiler tracks lifetimes to prevent dangling "
            "references. The borrow checker enforces rules at compile time: you can "
            "have either one mutable reference or any number of immutable references "
            "to a value. Rust's type system includes algebraic data types through "
            "enums, pattern matching with exhaustive checking, and traits for "
            "polymorphism. The standard library provides collections like Vec, "
            "HashMap, and BTreeMap. Error handling uses Result and Option types "
            "rather than exceptions. Cargo serves as the package manager and build "
            "system, with crates.io hosting community libraries."
        ),
        "lang": "en",
    },
    {
        "id": "np_long_005",
        "text": (
            "Git is a distributed version control system that tracks changes in "
            "source code during software development. Unlike centralized systems, "
            "every Git directory is a full repository with complete history. Key "
            "concepts include commits (snapshots), branches (divergent lines of "
            "development), merges (combining branches), and remotes (connections to "
            "other repositories). The staging area (index) allows selective "
            "committing. Common workflows include feature branching, GitFlow, and "
            "trunk-based development. GitHub, GitLab, and Bitbucket provide hosting "
            "with pull request code review, issue tracking, and CI/CD integration."
        ),
        "lang": "en",
    },
]

# ---------------------------------------------------------------------------
# 02 — Semantic Similarity pairs
# ---------------------------------------------------------------------------

SEMANTIC_POSITIVE_PAIRS: list[TestCase] = [
    # Exact duplicates
    TestCase("ss_exact_001", "semantic_similarity",
             text_a="How do I change my Windows password?",
             text_b="How do I change my Windows password?",
             expected_relationship="exact_match", difficulty="trivial"),
    TestCase("ss_exact_002", "semantic_similarity",
             text_a="NVDA is a free screen reader for Windows.",
             text_b="NVDA is a free screen reader for Windows.",
             expected_relationship="exact_match", difficulty="trivial"),
    TestCase("ss_exact_003", "semantic_similarity",
             text_a="Python virtual environments isolate project dependencies.",
             text_b="Python virtual environments isolate project dependencies.",
             expected_relationship="exact_match", difficulty="trivial"),
    # Formatting variations
    TestCase("ss_format_001", "semantic_similarity",
             text_a="How do I change my Windows password?",
             text_b="how do i change my windows password",
             expected_relationship="paraphrase", difficulty="easy",
             note="case difference"),
    TestCase("ss_format_002", "semantic_similarity",
             text_a="Python   virtual   environments  isolate   dependencies.",
             text_b="Python virtual environments isolate dependencies.",
             expected_relationship="paraphrase", difficulty="easy",
             note="whitespace difference"),
    TestCase("ss_format_003", "semantic_similarity",
             text_a="The quick brown fox... jumps over the lazy dog!",
             text_b="The quick brown fox jumps over the lazy dog.",
             expected_relationship="paraphrase", difficulty="easy",
             note="punctuation difference"),
    # Paraphrases (same meaning, different wording)
    TestCase("ss_para_001", "semantic_similarity",
             text_a="How can I reset my Windows password?",
             text_b="What steps should I follow to change my Windows login password?",
             expected_relationship="paraphrase", difficulty="medium"),
    TestCase("ss_para_002", "semantic_similarity",
             text_a="How do I set up a Python virtual environment?",
             text_b="What is the procedure for creating an isolated Python environment?",
             expected_relationship="paraphrase", difficulty="medium"),
    TestCase("ss_para_003", "semantic_similarity",
             text_a="NVDA stopped speaking after the update.",
             text_b="My screen reader went silent following the NVDA upgrade.",
             expected_relationship="paraphrase", difficulty="medium"),
    TestCase("ss_para_004", "semantic_similarity",
             text_a="The Docker container failed to start.",
             text_b="I cannot get my Docker container running.",
             expected_relationship="paraphrase", difficulty="medium"),
    TestCase("ss_para_005", "semantic_similarity",
             text_a="How do I revert the last Git commit?",
             text_b="What command undoes my most recent commit in Git?",
             expected_relationship="paraphrase", difficulty="medium"),
    TestCase("ss_para_006", "semantic_similarity",
             text_a="My Bluetooth headphones keep disconnecting.",
             text_b="My wireless audio device drops connection repeatedly.",
             expected_relationship="paraphrase", difficulty="medium"),
    TestCase("ss_para_007", "semantic_similarity",
             text_a="How do I configure keyboard shortcuts in NVDA?",
             text_b="Where can I customize NVDA's key bindings?",
             expected_relationship="paraphrase", difficulty="medium"),
    TestCase("ss_para_008", "semantic_similarity",
             text_a="The website is not accessible with a screen reader.",
             text_b="Screen reader users cannot navigate this site properly.",
             expected_relationship="paraphrase", difficulty="medium"),
    # Same topic, different meaning — should rank below paraphrases
    TestCase("ss_same_topic_001", "semantic_similarity",
             text_a="How do I install a new printer on Windows?",
             text_b="How do I uninstall a printer from Windows?",
             expected_relationship="related", difficulty="medium",
             note="install vs uninstall — should NOT be treated identical"),
    TestCase("ss_same_topic_002", "semantic_similarity",
             text_a="How do I enable NVDA at startup?",
             text_b="How do I disable NVDA from starting automatically?",
             expected_relationship="related", difficulty="medium"),
    TestCase("ss_same_topic_003", "semantic_similarity",
             text_a="git commit creates a new snapshot of changes.",
             text_b="git revert undoes a previous commit.",
             expected_relationship="related", difficulty="medium"),
    # Hard negatives — lexically similar, semantically different
    TestCase("ss_hardneg_001", "semantic_similarity",
             text_a="How do I install a Windows driver?",
             text_b="How do I uninstall a Windows driver?",
             expected_relationship="hard_negative", difficulty="hard"),
    TestCase("ss_hardneg_002", "semantic_similarity",
             text_a="Python is great for data science.",
             text_b="Python is terrible for data science.",
             expected_relationship="hard_negative", difficulty="hard"),
    TestCase("ss_hardneg_003", "semantic_similarity",
             text_a="NVDA works well with Firefox.",
             text_b="NVDA does not work well with Firefox.",
             expected_relationship="hard_negative", difficulty="hard"),
    TestCase("ss_hardneg_004", "semantic_similarity",
             text_a="The server is running and accepting connections.",
             text_b="The server is not running and rejecting connections.",
             expected_relationship="hard_negative", difficulty="hard"),
    TestCase("ss_hardneg_005", "semantic_similarity",
             text_a="Enable the feature in settings.",
             text_b="Disable the feature in settings.",
             expected_relationship="hard_negative", difficulty="hard"),
    TestCase("ss_hardneg_006", "semantic_similarity",
             text_a="Increase the font size for better readability.",
             text_b="Decrease the font size for better readability.",
             expected_relationship="hard_negative", difficulty="hard"),
    # Completely unrelated pairs
    TestCase("ss_unrel_001", "semantic_similarity",
             text_a="How do I configure a printer on Windows?",
             text_b="Best techniques for acoustic guitar recording.",
             expected_relationship="unrelated", difficulty="easy"),
    TestCase("ss_unrel_002", "semantic_similarity",
             text_a="Python virtual environments best practices.",
             text_b="How to bake sourdough bread at home.",
             expected_relationship="unrelated", difficulty="easy"),
    TestCase("ss_unrel_003", "semantic_similarity",
             text_a="NVDA screen reader documentation.",
             text_b="Olympic swimming records history.",
             expected_relationship="unrelated", difficulty="easy"),
    TestCase("ss_unrel_004", "semantic_similarity",
             text_a="Git merge conflict resolution.",
             text_b="Types of tropical fish for home aquariums.",
             expected_relationship="unrelated", difficulty="easy"),
    TestCase("ss_unrel_005", "semantic_similarity",
             text_a="Docker container orchestration with Kubernetes.",
             text_b="Medieval European castle architecture.",
             expected_relationship="unrelated", difficulty="easy"),
    TestCase("ss_unrel_006", "semantic_similarity",
             text_a="Machine learning model evaluation metrics.",
             text_b="How to train a puppy to sit and stay.",
             expected_relationship="unrelated", difficulty="easy"),
]

# ---------------------------------------------------------------------------
# 03 — Retrieval document collection
# ---------------------------------------------------------------------------


@dataclass
class RetrievalDataset:
    """A document collection with queries and relevance labels."""

    name: str
    description: str
    documents: list[str]
    queries: list[dict[str, Any]]  # {query, relevant_doc_indices}


RETRIEVAL_TECH_DOCS = RetrievalDataset(
    name="tech_docs",
    description="Technical documentation snippets — Windows, Python, NVDA, Git, Docker, Rust",
    documents=[
        # 0: Windows password
        "To change your Windows password, open Settings > Accounts > Sign-in options. "
        "Click 'Change' under Password. Enter your current password, then set and "
        "confirm the new password. Your password must meet complexity requirements.",
        # 1: NVDA basics
        "NVDA (NonVisual Desktop Access) is a free and open-source screen reader for "
        "the Microsoft Windows operating system. Providing feedback via synthetic "
        "speech and Braille, it enables blind and vision-impaired people to access "
        "computers running Windows for no more cost than a sighted person.",
        # 2: Python venv
        "To create a Python virtual environment, run `python -m venv .venv` in your "
        "project directory. Activate it with `.venv\\Scripts\\activate` on Windows "
        "or `source .venv/bin/activate` on macOS/Linux. Use `deactivate` to exit.",
        # 3: Git merge
        "When Git encounters a merge conflict, it inserts conflict markers "
        "(<<<<<<<, =======, >>>>>>>) into the affected files. Edit the files to "
        "resolve the conflicts, then `git add` the resolved files and `git commit`.",
        # 4: Docker
        "The Docker daemon requires root privileges. If you see 'permission denied', "
        "add your user to the docker group: `sudo usermod -aG docker $USER`. "
        "Log out and back in for changes to take effect.",
        # 5: NVDA key commands
        "NVDA key is typically Insert or CapsLock. NVDA+T reads the window title, "
        "NVDA+F7 shows the elements list, NVDA+Space toggles browse mode. "
        "NVDA+Q quits NVDA. NVDA+N opens the NVDA menu.",
        # 6: Rust ownership
        "Rust's ownership system ensures memory safety without garbage collection. "
        "Each value has exactly one owner. When the owner goes out of scope, "
        "the value is dropped. References allow borrowing without transferring ownership.",
        # 7: Bluetooth fixes
        "If your Bluetooth device keeps disconnecting, try: 1) Remove and re-pair "
        "the device. 2) Update Bluetooth drivers. 3) Disable power saving for "
        "Bluetooth adapter. 4) Run Windows Bluetooth troubleshooter.",
        # 8: Screen reader web
        "To make websites accessible with screen readers, use semantic HTML elements, "
        "ARIA landmarks, proper heading hierarchy, alt text for images, and ensure "
        "all interactive elements are keyboard-accessible.",
        # 9: Python generators
        "Generator expressions in Python use parentheses and produce values lazily. "
        "Unlike list comprehensions which create the entire list in memory, "
        "generators yield items one at a time, saving memory for large datasets.",
        # 10: CSS layout
        "CSS Flexbox handles one-dimensional layouts (row or column). CSS Grid "
        "handles two-dimensional layouts. Use Grid for page structure and Flexbox "
        "for component-level alignment like navigation bars.",
        # 11: NVDA add-ons
        "NVDA add-ons extend the screen reader's functionality. Install them from "
        "the NVDA Add-on Store (NVDA+N > Tools > Add-on Store). Some add-ons "
        "provide app-specific enhancements, synthesizers, or braille display drivers.",
        # 12: System restore
        "Windows System Restore creates snapshots of system files and registry. "
        "To create a restore point: search 'Create a restore point' > System "
        "Protection tab > Create. Useful before installing new software or drivers.",
        # 13: Docker compose
        "Docker Compose defines multi-container applications in a YAML file. "
        "Use `docker-compose up` to start all services, `docker-compose down` to "
        "stop and remove them. Services can share networks and volumes.",
        # 14: Git rebase
        "`git rebase` rewrites commit history by applying commits on top of another "
        "branch. Unlike `git merge` which creates a merge commit, rebase produces "
        "a linear history. Never rebase commits that have been pushed to shared repos.",
        # 15: NVDA speech
        "NVDA uses speech synthesizers to read screen content aloud. The default "
        "is eSpeak NG. You can install additional synthesizers like Microsoft Speech "
        "API voices or third-party options. Adjust speech rate in NVDA settings.",
        # 16: PowerShell
        "PowerShell is a task automation and configuration management framework. "
        "It includes a command-line shell and scripting language built on .NET. "
        "Cmdlets follow Verb-Noun naming. Use Get-Help for documentation.",
        # 17: ML embeddings
        "Embedding models convert text into dense vector representations where "
        "semantically similar texts are close in vector space. They are used for "
        "semantic search, clustering, and retrieval-augmented generation (RAG).",
        # 18: NGINX
        "NGINX is a high-performance web server and reverse proxy. Configure virtual "
        "hosts in server blocks. Use `proxy_pass` to forward requests to backend "
        "servers. NGINX also supports load balancing and caching.",
        # 19: Windows Narrator
        "Windows Narrator is the built-in screen reader in Windows. NVDA offers more "
        "features and customization than Narrator. Both read screen content aloud, "
        "but NVDA has a larger add-on ecosystem and application-specific support.",
        # 20: audio latency
        "Audio latency in recording software can be reduced by: using ASIO drivers, "
        "adjusting buffer size (smaller = lower latency but higher CPU), disabling "
        "unused plugins, and ensuring drivers are up to date.",
        # 21: Python typing
        "Python 3.5+ supports type hints. Use `def func(x: int) -> str:` syntax. "
        "Type hints are optional and not enforced at runtime. Use mypy or pyright "
        "for static type checking. Generics support `List[str]` and `Dict[str, int]`.",
        # 22: accessible UX
        "Accessible user experience design ensures that digital products can be used "
        "by everyone regardless of ability. Key principles include perceivable "
        "content, operable interfaces, understandable information, and robust "
        "compatibility with assistive technologies.",
        # 23: Wi-Fi troubleshooting
        "If Wi-Fi keeps disconnecting: restart router and modem, update network "
        "adapter drivers, change Wi-Fi channel to avoid interference, check for "
        "Windows updates, and run the network troubleshooter.",
        # 24: tokenizers
        "Tokenizers split text into tokens that models can process. Subword "
        "tokenization (BPE, WordPiece, SentencePiece) handles out-of-vocabulary "
        "words by splitting them into known subword units. The tokenizer must "
        "match the model's training vocabulary.",
        # 25: VS Code
        "Visual Studio Code is a lightweight but powerful source code editor. "
        "It supports debugging, syntax highlighting, intelligent code completion, "
        "snippets, and Git integration. Extensions add language support and tools.",
        # 26: aria labels
        "ARIA labels (`aria-label`, `aria-labelledby`) provide accessible names "
        "for elements that lack visible text. Use them on icon buttons, form inputs "
        "without labels, and landmarks. Prefer native HTML semantics over ARIA.",
        # 27: Cargo build
        "Cargo is Rust's build system and package manager. `cargo build` compiles "
        "your project, `cargo run` builds and runs it, `cargo test` runs tests. "
        "Dependencies are specified in Cargo.toml. Cargo.lock pins exact versions.",
        # 28: screen reader testing
        "Screen reader testing should include: verifying all content is announced, "
        "checking focus order, testing forms and modals, ensuring dynamic content "
        "updates are announced, and testing with both speech and braille output.",
        # 29: JSON Schema
        "JSON Schema defines the structure of JSON data for validation. It specifies "
        "required properties, types, patterns, and constraints. Useful for API "
        "contracts and configuration validation. Tools can auto-generate forms from schema.",
        # 30: NVDA troubleshooting
        "If NVDA is not speaking: check audio output device, ensure NVDA is running "
        "(system tray icon), try restarting NVDA with Ctrl+Alt+N, check speech "
        "synthesizer settings, or reinstall NVDA if issues persist.",
        # 31: async Python
        "Python's asyncio provides asynchronous I/O. Use `async def` and `await`. "
        "`asyncio.gather()` runs multiple coroutines concurrently. Async is useful "
        "for network-bound tasks but does not bypass the GIL for CPU-bound work.",
        # 32: hard negatives
        "Semantic search models must distinguish between semantically similar and "
        "semantically different texts even when they share the same vocabulary. "
        "Hard negatives are crucial for training and evaluating retrieval models.",
        # 33: Windows updates
        "Windows Update delivers security patches, feature updates, and driver "
        "updates. Check for updates in Settings > Windows Update. You can pause "
        "updates, set active hours, and choose when to restart for updates.",
        # 34: token limits
        "Embedding models have a maximum token limit. Inputs longer than this limit "
        "are truncated, potentially losing important information. Long documents "
        "should be split into chunks before embedding for semantic search.",
        # 35: braille display
        "NVDA supports refreshable braille displays from multiple manufacturers. "
        "Configure braille settings in NVDA preferences. Choose between contracted "
        "and uncontracted braille, adjust cursor presentation, and set input table.",
        # 36: pip install
        "pip is Python's package installer. `pip install package` installs from PyPI. "
        "Use `pip install -r requirements.txt` for project dependencies. "
        "`pip freeze > requirements.txt` exports current environment packages.",
        # 37: heading navigation
        "Screen reader users navigate web pages by headings. Use h1-h6 elements "
        "in a logical hierarchy. NVDA users press H to jump to next heading, "
        "Shift+H for previous, and 1-6 to navigate by heading level.",
        # 38: VSCode accessibility
        "VS Code has built-in accessibility features: screen reader mode, zoom, "
        "high contrast themes, and keyboard-only navigation. Enable screen reader "
        "mode with Ctrl+Shift+P > 'Screen Reader Mode'. All features are operable "
        "without a mouse.",
        # 39: rate limits
        "Many APIs enforce rate limiting to prevent abuse. HTTP 429 Too Many "
        "Requests responses indicate you've exceeded the rate limit. Implement "
        "exponential backoff and respect Retry-After headers in your API clients.",
        # 40: GPU compute
        "GPUs accelerate machine learning through massively parallel computation. "
        "CUDA (NVIDIA) and ROCm (AMD) provide GPU programming frameworks. Models "
        "can be quantized to INT8 or FP16 to reduce memory and increase throughput.",
        # 41: focus management
        "Managing keyboard focus is critical for screen reader accessibility. "
        "When opening modals, move focus to the modal. When closing, return focus "
        "to the triggering element. Use `element.focus()` and `tabindex` carefully.",
        # 42: ollama
        "Ollama runs large language models locally. Install with `ollama pull model` "
        "then `ollama run model`. It exposes a REST API on localhost:11434. Supports "
        "models like Llama, Mistral, and Gemma with GPU acceleration.",
        # 43: python debugging
        "Python debugging tools include pdb (built-in debugger), ipdb (IPython "
        "debugger), pudb (console visual debugger), and IDE-integrated debuggers. "
        "Set breakpoints with `breakpoint()` in Python 3.7+ or `import pdb; pdb.set_trace()`.",
        # 44: live regions
        "ARIA live regions announce dynamic content changes to screen readers. "
        "Use `aria-live=\"polite\"` for non-urgent updates and `aria-live=\"assertive\"` "
        "for important alerts. `role=\"alert\"` is implicitly assertive.",
        # 45: git stash
        "`git stash` temporarily saves uncommitted changes. `git stash pop` restores "
        "the most recent stash. `git stash list` shows all stashes. Use stashing "
        "when you need to switch branches but have uncommitted work.",
        # 46: sentence transformers
        "SentenceTransformers is a Python framework for computing sentence and "
        "text embeddings. It wraps HuggingFace Transformers and provides an easy "
        "API for encoding texts into dense vector representations.",
        # 47: web forms
        "Accessible web forms require: labels associated with inputs, error messages "
        "linked to fields, clear instructions, sufficient color contrast, keyboard "
        "accessibility, and proper focus management after submission.",
        # 48: matplotlib
        "Matplotlib is a comprehensive Python plotting library. Create figures with "
        "`plt.figure()`, add subplots with `plt.subplots()`, and customize with "
        "titles, labels, legends, and color maps. Save figures with `plt.savefig()`.",
        # 49: embedding normalization
        "Embedding vectors are typically L2-normalized so that cosine similarity "
        "equals dot product. Normalization ensures consistent similarity scores "
        "regardless of embedding magnitude. Most embedding models output normalized vectors.",
    ],
    queries=[
        # Each query maps to relevant document indices
        {"query": "How do I change my Windows password?", "relevant": [0]},
        {"query": "What is NVDA and what does it do?", "relevant": [1]},
        {"query": "How do I create a Python virtual environment?", "relevant": [2]},
        {"query": "How do I resolve a Git merge conflict?", "relevant": [3]},
        {"query": "Why do I get permission denied with Docker?", "relevant": [4]},
        {"query": "What are the most common NVDA keyboard shortcuts?", "relevant": [5]},
        {"query": "How does Rust manage memory safely?", "relevant": [6]},
        {"query": "My Bluetooth headphones keep disconnecting, how do I fix it?", "relevant": [7]},
        {"query": "How do I make my website accessible for screen readers?", "relevant": [8, 26, 37, 44, 47]},
        {"query": "What's the difference between list comprehension and generators in Python?", "relevant": [9]},
        {"query": "When should I use CSS Grid vs Flexbox?", "relevant": [10]},
        {"query": "How do I install NVDA add-ons?", "relevant": [11]},
        {"query": "How do I create a Windows system restore point?", "relevant": [12]},
        {"query": "How do I use Docker Compose for multi-container apps?", "relevant": [13]},
        {"query": "What is the difference between git merge and git rebase?", "relevant": [14, 3]},
        {"query": "How do I change NVDA's speech settings and voice?", "relevant": [15]},
        {"query": "What is PowerShell and how do I get help with commands?", "relevant": [16]},
        {"query": "How do embedding models work for semantic search?", "relevant": [17, 24, 32, 46]},
        {"query": "How do I configure NGINX as a reverse proxy?", "relevant": [18]},
        {"query": "How do I reduce audio latency in my recording software?", "relevant": [20]},
        {"query": "How do I add type hints to my Python code?", "relevant": [21]},
        {"query": "My Wi-Fi keeps disconnecting, what should I check?", "relevant": [23]},
        {"query": "How do I install Python packages with pip?", "relevant": [36]},
        {"query": "How does cargo build and run Rust projects?", "relevant": [27]},
        {"query": "What accessibility features does VS Code have?", "relevant": [38]},
        {"query": "How do I debug Python code?", "relevant": [43]},
        {"query": "How do I set up Ollama to run LLMs locally?", "relevant": [42]},
        {"query": "What are ARIA live regions and how do they work?", "relevant": [44]},
        {"query": "How do I use git stash?", "relevant": [45]},
        {"query": "How does sentence-transformers work for text embeddings?", "relevant": [46]},
    ],
)

# ---------------------------------------------------------------------------
# 04 — Hard-negative retrieval queries
# ---------------------------------------------------------------------------

HARD_NEGATIVE_QUERIES: list[TestCase] = [
    TestCase(
        "hn_001", "hard_negatives",
        query="How do I uninstall a Windows driver?",
        documents=[
            "How to install a new Windows driver",
            "How to update an existing Windows driver",
            "How to uninstall a Windows driver completely",  # correct
            "How to disable a Windows device temporarily",
            "How to reinstall a corrupted Windows driver",
        ],
        relevant_document_ids=[2],
        difficulty="hard",
    ),
    TestCase(
        "hn_002", "hard_negatives",
        query="How do I disable NVDA from starting automatically?",
        documents=[
            "How to enable NVDA to start automatically with Windows",  # hard neg
            "How to disable NVDA automatic startup on Windows login",  # correct
            "How to configure NVDA startup behavior in settings",
            "How to install NVDA on a new Windows computer",
            "How to update NVDA to the latest version",
        ],
        relevant_document_ids=[1],
        difficulty="hard",
    ),
    TestCase(
        "hn_003", "hard_negatives",
        query="Python is terrible for data processing, what alternatives exist?",
        documents=[
            "Python is excellent for data processing and analysis",  # hard neg
            "Why Python is great for machine learning and data science",
            "Alternatives to Python for data processing: R, Julia, Scala",
            "Quick overview of Python's data processing libraries",
            "Python vs R for statistical data analysis",  # partially relevant
        ],
        relevant_document_ids=[2],
        difficulty="hard",
    ),
    TestCase(
        "hn_004", "hard_negatives",
        query="How do I increase the font size in my browser?",
        documents=[
            "How to decrease the font size in your browser for more content",
            "How to adjust browser font size: zoom and default font settings",
            "How to increase browser font size using keyboard shortcuts",  # correct
            "How to change the default browser font family",
            "How to customize browser color scheme and themes",
        ],
        relevant_document_ids=[2],
        difficulty="hard",
    ),
    TestCase(
        "hn_005", "hard_negatives",
        query="How do I stop Docker containers from running?",
        documents=[
            "How to start Docker containers with docker run",
            "How to stop and remove Docker containers with docker stop/rm",  # correct
            "How to restart Docker containers with docker restart",
            "How to list all running Docker containers",
            "How to build Docker images from Dockerfiles",
        ],
        relevant_document_ids=[1],
        difficulty="hard",
    ),
    TestCase(
        "hn_006", "hard_negatives",
        query="My NVDA speech is too slow, how do I speed it up?",
        documents=[
            "How to decrease NVDA speech rate for better comprehension",
            "How to increase NVDA speech rate and adjust voice speed settings",  # correct
            "How to change NVDA speech synthesizer voice",
            "How to install additional NVDA speech synthesizers",
            "How to pause and resume NVDA speech output",
        ],
        relevant_document_ids=[1],
        difficulty="hard",
    ),
    TestCase(
        "hn_007", "hard_negatives",
        query="How do I push changes to a remote Git repository?",
        documents=[
            "How to pull changes from a remote Git repository",
            "How to push local commits to a remote Git repository using git push",  # correct
            "How to fetch remote changes without merging",
            "How to clone a remote Git repository",
            "How to create a new Git branch for feature development",
        ],
        relevant_document_ids=[1],
        difficulty="hard",
    ),
    TestCase(
        "hn_008", "hard_negatives",
        query="Remove Python package from virtual environment",
        documents=[
            "How to install Python packages in a virtual environment with pip",
            "How to uninstall Python packages using pip uninstall",  # correct
            "How to list installed Python packages in current environment",
            "How to upgrade Python packages to latest versions",
            "How to create a requirements.txt file from installed packages",
        ],
        relevant_document_ids=[1],
        difficulty="hard",
    ),
    TestCase(
        "hn_009", "hard_negatives",
        query="The server is down and I need to bring it back up.",
        documents=[
            "How to gracefully shut down a production server",
            "How to restart a server and restore services after failure",  # correct
            "How to monitor server uptime and health status",
            "How to deploy new application code to production servers",
            "How to configure server firewall rules for security",
        ],
        relevant_document_ids=[1],
        difficulty="hard",
    ),
    TestCase(
        "hn_010", "hard_negatives",
        query="How do I lock my Windows computer quickly?",
        documents=[
            "How to unlock a Windows computer after being locked out",
            "How to lock your Windows computer with Win+L keyboard shortcut",  # correct
            "How to sign out of Windows and switch user accounts",
            "How to put Windows computer to sleep or hibernate mode",
            "How to restart or shut down your Windows computer",
        ],
        relevant_document_ids=[1],
        difficulty="hard",
    ),
]

# ---------------------------------------------------------------------------
# 05 — Multilingual test data
# ---------------------------------------------------------------------------

MULTILINGUAL_PAIRS: list[TestCase] = [
    # Same meaning across languages — should score high
    TestCase("ml_001", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="मैं अपना विंडोज पासवर्ड कैसे रीसेट करूं?",
             language="en-hi", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_002", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="Comment réinitialiser mon mot de passe Windows?",
             language="en-fr", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_003", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="Wie setze ich mein Windows-Passwort zurück?",
             language="en-de", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_004", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="¿Cómo restablezco mi contraseña de Windows?",
             language="en-es", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_005", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="Como redefinir minha senha do Windows?",
             language="en-pt", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_006", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="Как сбросить пароль Windows?",
             language="en-ru", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_007", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="كيفية إعادة تعيين كلمة مرور ويندوز؟",
             language="en-ar", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_008", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="Windowsのパスワードをリセットする方法",
             language="en-ja", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_009", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="Windows 비밀번호를 재설정하는 방법",
             language="en-ko", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_010", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="如何重置Windows密码",
             language="en-zh", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_011", "multilingual",
             text_a="How do I reset my Windows password?",
             text_b="ગુજરાતીમાં વિન્ડોઝ પાસવર્ડ રીસેટ કેવી રીતે કરવો",
             language="en-gu", expected_relationship="cross_language", difficulty="hard"),
    # Cross-language unrelated
    TestCase("ml_012", "multilingual",
             text_a="How do I configure a Python virtual environment?",
             text_b="सबसे अच्छी ध्वनिक गिटार रिकॉर्डिंग तकनीकें (Best acoustic guitar recording techniques)",
             language="en-hi", expected_relationship="unrelated", difficulty="easy"),
    TestCase("ml_013", "multilingual",
             text_a="How do I configure a Python virtual environment?",
             text_b="Meilleures techniques pour la guitare acoustique",
             language="en-fr", expected_relationship="unrelated", difficulty="easy"),
    # Same language, different scripts
    TestCase("ml_014", "multilingual",
             text_a="नमस्ते, मुझे NVDA स्क्रीन रीडर के बारे में जानकारी चाहिए।",
             text_b="NVDA एक मुफ्त और ओपन-सोर्स स्क्रीन रीडर है जो विंडोज के लिए उपलब्ध है।",
             language="hi", expected_relationship="related", difficulty="medium"),
    TestCase("ml_015", "multilingual",
             text_a="مرحباً، أحتاج معلومات عن قارئ الشاشة NVDA.",
             text_b="NVDA هو قارئ شاشة مجاني ومفتوح المصدر لنظام ويندوز.",
             language="ar", expected_relationship="related", difficulty="medium"),
    # Mixed English + non-English
    TestCase("ml_016", "multilingual",
             text_a="Python में virtual environment कैसे सेटअप करें?",
             text_b="Creating isolated Python environments with venv module",
             language="hi-en", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_017", "multilingual",
             text_a="Git merge conflict को कैसे resolve करें?",
             text_b="Steps to resolve merge conflicts in Git using command line",
             language="hi-en", expected_relationship="cross_language", difficulty="hard"),
    TestCase("ml_018", "multilingual",
             text_a="Comment configurer NVDA avec des voix françaises?",
             text_b="How to configure NVDA screen reader with French speech voices",
             language="fr-en", expected_relationship="cross_language", difficulty="medium"),
    # Code + natural language
    TestCase("ml_019", "multilingual",
             text_a="async def fetch_data(url): return await aiohttp.get(url)",
             text_b="Python async function that fetches data from a URL using aiohttp",
             language="code-en", expected_relationship="related", difficulty="medium"),
    TestCase("ml_020", "multilingual",
             text_a="docker run -d --name web -p 8080:80 nginx:latest",
             text_b="Run an NGINX web server container in detached mode on port 8080",
             language="code-en", expected_relationship="related", difficulty="medium"),
]

MULTILINGUAL_RETRIEVAL: list[TestCase] = [
    TestCase(
        "ml_ret_001", "multilingual_retrieval",
        query="NVDAスクリーンリーダーの設定方法 (How to configure NVDA screen reader)",
        documents=[
            "NVDA is a free screen reader for Microsoft Windows.",
            "NVDAの設定は環境設定メニューから行います。音声、点字、キーボード設定などがあります。",
            "Windows Update delivers security patches and feature updates.",
            "Python virtual environments isolate project dependencies.",
        ],
        relevant_document_ids=[1],
        language="ja", difficulty="hard",
    ),
    TestCase(
        "ml_ret_002", "multilingual_retrieval",
        query="कैसे एक Python virtual environment बनाएं",
        documents=[
            "To create a virtual environment, use python -m venv .venv",
            "पायथन वर्चुअल एनवायरनमेंट बनाने के लिए python -m venv कमांड का उपयोग करें",
            "Docker containers run isolated processes on a shared kernel.",
            "Git branches allow parallel development of features.",
        ],
        relevant_document_ids=[1],
        language="hi", difficulty="hard",
    ),
    TestCase(
        "ml_ret_003", "multilingual_retrieval",
        query="Comment résoudre un conflit de merge Git?",
        documents=[
            "Edit files to remove conflict markers and git add resolved files.",
            "Les conflits Git se résolvent en éditant les fichiers et en utilisant git add puis git commit.",
            "CSS Grid handles two-dimensional layouts in web design.",
            "ARIA landmarks help screen readers navigate web pages.",
        ],
        relevant_document_ids=[1],
        language="fr", difficulty="hard",
    ),
]

# ---------------------------------------------------------------------------
# 06 — NVDA real-world text
# ---------------------------------------------------------------------------

NVDA_REALWORLD_TEXTS: list[TestCase] = [
    TestCase(
        "nvda_001", "nvda_realworld",
        query="How do I change the keyboard layout in NVDA?",
        documents=[
            # Web page with navigation noise
            (
                "Home  Products  Documentation  Support  Blog  Login\n"
                "Skip to main content\n"
                "heading level 1  NVDA User Guide\n"
                "heading level 2  Keyboard Settings\n"
                "link  Table of Contents\n"
                "To change keyboard layout in NVDA, open the NVDA menu with NVDA+N, "
                "select Preferences, then Keyboard settings. Choose between desktop "
                "and laptop keyboard layouts. Desktop layout uses the numpad for "
                "navigation while laptop layout provides alternatives.\n"
                "link  Next: Speech Settings\n"
                "link  Previous: General Settings\n"
                "Footer  Copyright NV Access 2024  Privacy Policy  Contact"
            ),
            "The keyboard layout determines which keys perform which NVDA commands.",
            "Speech synthesizer settings control voice, rate, and pitch.",
        ],
        relevant_document_ids=[0],
        difficulty="medium", note="noisy web navigation mixed with content",
    ),
    TestCase(
        "nvda_002", "nvda_realworld",
        query="NVDA not reading web page content",
        documents=[
            (
                "Stack Overflow — NVDA not reading web page content\n"
                "Asked 2 years ago  Modified 6 months ago  Viewed 1.2k times\n"
                "Question: I'm using NVDA 2023.1 on Windows 10. When I navigate to "
                "certain web pages, NVDA stops reading the content. The focus moves "
                "but no speech output. I've tried restarting NVDA. Has anyone else "
                "experienced this?\n"
                "Answer 1 (accepted): Check if you accidentally entered focus mode. "
                "Press NVDA+Space to toggle browse mode. Also check if the page uses "
                "heavy JavaScript that might interfere with accessibility.\n"
                "Answer 2: Try clearing your browser cache and NVDA configuration. "
                "Sometimes corrupted settings cause this.\n"
                "Share  Edit  Follow  Flag"
            ),
            "NVDA is working fine on my system with the latest update.",
            "Python web scraping with BeautifulSoup tutorial for beginners.",
        ],
        relevant_document_ids=[0],
        difficulty="medium", note="StackOverflow format with timestamps and markup",
    ),
    TestCase(
        "nvda_003", "nvda_realworld",
        query="Windows error 0x80070005 access denied",
        documents=[
            (
                "=== Event Log ===\n"
                "[2024-08-11 14:32:17] Error: Application Error 1000\n"
                "[2024-08-11 14:32:17] Faulting application: svchost.exe\n"
                "[2024-08-11 14:32:18] Windows Update failed with error 0x80070005\n"
                "[2024-08-11 14:32:18] Access is denied. This typically occurs when "
                "the user does not have sufficient permissions to modify system files. "
                "Run as administrator or check security policy settings.\n"
                "=== End of Log ==="
            ),
            "How to bake chocolate chip cookies from scratch.",
            "The weather forecast for this weekend shows clear skies.",
        ],
        relevant_document_ids=[0],
        difficulty="easy", note="log file format with timestamps",
    ),
    TestCase(
        "nvda_004", "nvda_realworld",
        query="How to access NVDA add-on store?",
        documents=[
            (
                "NVDA  menu bar\n"
                "File  Edit  View  Tools  Help\n"
                "    Tools submenu:\n"
                "        Check for update…\n"
                "        Add-on Store…        Alt+T, A\n"
                "        Run COM Registration Fixing tool…\n"
                "        Reload plugins\n"
                "        View log\n"
                "        Speech dictionaries…\n"
                "The Add-on Store lets you browse, install, and manage NVDA add-ons. "
                "You can search by name, filter by category, and enable or disable "
                "installed add-ons."
            ),
            "Windows Media Player has stopped working.",
            "How to make homemade pasta from scratch.",
        ],
        relevant_document_ids=[0],
        difficulty="medium", note="menu structure with keyboard shortcuts",
    ),
    TestCase(
        "nvda_005", "nvda_realworld",
        query="NVDA GitHub issue: Braille display not connecting",
        documents=[
            (
                "#4321 Braille display not connecting after NVDA update to 2024.1\n\n"
                "**Environment:**\n"
                "- NVDA version: 2024.1\n"
                "- Windows version: Windows 11 23H2\n"
                "- Braille display: HumanWare Brailliant BI 40X\n\n"
                "**Steps to reproduce:**\n"
                "1. Update NVDA to 2024.1\n"
                "2. Connect Brailliant BI 40X via USB\n"
                "3. Open NVDA Braille settings\n"
                "4. Select HumanWare Brailliant BI from display list\n\n"
                "**Expected:** Braille display connects and shows output\n"
                "**Actual:** NVDA shows 'No braille display detected'\n\n"
                "**Workaround:** Downgrading to NVDA 2023.3 restores functionality\n\n"
                "**Labels:** bug, braille, regression"
            ),
            "New NVDA 2024.1 release includes performance improvements.",
            "Recipe for vegetarian lasagna with spinach and ricotta.",
        ],
        relevant_document_ids=[0],
        difficulty="medium", note="GitHub issue format",
    ),
    TestCase(
        "nvda_006", "nvda_realworld",
        query="release notes nvda 2024.1",
        documents=[
            (
                "NVDA 2024.1 Release Notes\n"
                "==========================\n\n"
                "**New Features:**\n"
                "- Added support for Windows 11 24H2 preview builds\n"
                "- New Add-on Store with improved search and filtering\n"
                "- Enhanced braille support for new displays\n\n"
                "**Bug Fixes:**\n"
                "- Fixed crash when using Firefox with certain extensions\n"
                "- Resolved issue where NVDA would not start after Windows Update\n"
                "- Fixed braille display detection on USB-C connections\n\n"
                "**Changes for Developers:**\n"
                "- Updated Python to 3.11\n"
                "- New API for add-on update notifications\n"
                "- wxPython upgraded to 4.2.1"
            ),
            "Python 3.13 introduces a new interactive interpreter.",
            "Docker 26.0 release adds new networking features.",
        ],
        relevant_document_ids=[0],
        difficulty="easy", note="release notes format",
    ),
]

# ---------------------------------------------------------------------------
# 07 — Long context documents
# ---------------------------------------------------------------------------

# Token-count helpers (approximate: 1 token ≈ 0.75 words)
def _generate_long_doc(target_words: int, topic: str) -> str:
    """Generate a long document with approximate target word count."""
    templates = {
        "python": (
            "Python is a high-level, interpreted programming language known for "
            "its readability and versatility. It supports multiple programming "
            "paradigms including procedural, object-oriented, and functional "
            "programming. Python's extensive standard library provides modules "
            "for file I/O, networking, regular expressions, unit testing, "
            "logging, and more. "
        ),
        "nvda": (
            "NVDA (NonVisual Desktop Access) is a free, open-source screen reader "
            "for Microsoft Windows. It enables blind and vision-impaired users to "
            "access computers through synthetic speech and braille output. NVDA "
            "supports web browsers, email clients, office suites, and many other "
            "applications through its extensive add-on ecosystem. "
        ),
        "rust": (
            "Rust is a systems programming language focused on safety, speed, and "
            "concurrency. Its ownership system prevents memory errors at compile "
            "time without needing a garbage collector. Rust's type system and "
            "borrow checker ensure thread safety and eliminate data races. "
        ),
    }
    base = templates.get(topic, templates["python"])
    repeat_count = max(1, target_words // len(base.split()))
    return (base * repeat_count)[: target_words * 6]  # rough char estimate


LONG_CONTEXT_TEXTS: list[dict[str, Any]] = [
    {"id": "long_128", "text": _generate_long_doc(128, "python"), "approx_tokens": 128},
    {"id": "long_256", "text": _generate_long_doc(256, "nvda"), "approx_tokens": 256},
    {"id": "long_512", "text": _generate_long_doc(512, "rust"), "approx_tokens": 512},
    {"id": "long_513", "text": _generate_long_doc(513, "python"), "approx_tokens": 513, "note": "Crosses 512 boundary (previous sliding-window limit)"},
    {"id": "long_768", "text": _generate_long_doc(768, "nvda"), "approx_tokens": 768},
    {"id": "long_1024", "text": _generate_long_doc(1024, "rust"), "approx_tokens": 1024},
    {"id": "long_2048", "text": _generate_long_doc(2048, "python"), "approx_tokens": 2048},
    {"id": "long_4096", "text": _generate_long_doc(4096, "nvda"), "approx_tokens": 4096},
]

LONG_CONTEXT_POSITION_TESTS: list[TestCase] = [
    TestCase(
        "long_pos_001", "long_context",
        query="How do I change my Windows password?",
        documents=[
            # Relevant info at beginning
            "To change your Windows password, go to Settings then Accounts. "
            + _generate_long_doc(700, "python"),
            # Relevant info at end
            _generate_long_doc(700, "rust")
            + " To change your Windows password, open Settings and navigate to Accounts.",
            # Irrelevant long doc
            _generate_long_doc(1000, "python"),
        ],
        relevant_document_ids=[0, 1],
        difficulty="hard",
        note="relevant info at beginning vs end of long docs",
    ),
]

# ---------------------------------------------------------------------------
# 08 — Edge cases
# ---------------------------------------------------------------------------

EDGE_CASES: list[dict[str, Any]] = [
    {"id": "edge_empty", "text": "", "expected_behavior": "error_or_default"},
    {"id": "edge_one_char", "text": "x", "expected_behavior": "valid_embedding"},
    {"id": "edge_one_word", "text": "Hello", "expected_behavior": "valid_embedding"},
    {"id": "edge_punctuation", "text": "!!! ??? ... --- ***", "expected_behavior": "valid_embedding"},
    {"id": "edge_numbers", "text": "12345 67890 3.14159 -42 1e10", "expected_behavior": "valid_embedding"},
    {"id": "edge_url", "text": "https://www.example.com/path/to/page?query=value&foo=bar", "expected_behavior": "valid_embedding"},
    {"id": "edge_email", "text": "user.name+tag@example-domain.co.uk", "expected_behavior": "valid_embedding"},
    {"id": "edge_windows_path", "text": r"C:\Users\username\Documents\project\src\main.py", "expected_behavior": "valid_embedding"},
    {"id": "edge_linux_path", "text": "/home/username/projects/nvda-ai-assistant/src/lib.rs", "expected_behavior": "valid_embedding"},
    {"id": "edge_json", "text": '{"name":"test","values":[1,2,3],"nested":{"key":"value"}}', "expected_behavior": "valid_embedding"},
    {"id": "edge_xml", "text": "<root><item id='1'><name>Test</name></item></root>", "expected_behavior": "valid_embedding"},
    {"id": "edge_markdown", "text": "# Heading\n\n**bold** and *italic*\n\n- list item 1\n- list item 2\n\n```python\nprint('hello')\n```", "expected_behavior": "valid_embedding"},
    {"id": "edge_stack_trace", "text": (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 42, in <module>\n'
        "    result = process(data)\n"
        '  File "utils.py", line 15, in process\n'
        "    raise ValueError('Invalid input')\n"
        "ValueError: Invalid input"
    ), "expected_behavior": "valid_embedding"},
    {"id": "edge_compiler_error", "text": (
        "error[E0382]: borrow of moved value: `data`\n"
        "  --> src/main.rs:15:20\n"
        "   |\n"
        "14 |     let handle = process(data);\n"
        "   |                          ---- value moved here\n"
        "15 |     println!(\"{}\", data);\n"
        "   |                    ^^^^ value borrowed here after move"
    ), "expected_behavior": "valid_embedding"},
    {"id": "edge_repetitive", "text": "test test test test test test test test test test " * 20, "expected_behavior": "valid_embedding"},
    {"id": "edge_duplicate", "text": "This is a sentence. " * 50, "expected_behavior": "valid_embedding"},
    {"id": "edge_emoji", "text": "Hello world! 😀🎉🚀💻🔒 Testing emoji embeddings ❤️🌈", "expected_behavior": "valid_embedding"},
    {"id": "edge_mixed_scripts", "text": "Hello 世界 नमस्ते мир 🌍 123 test", "expected_behavior": "valid_embedding"},
    {"id": "edge_whitespace_only", "text": "   \t\n   ", "expected_behavior": "error_or_default"},
    {"id": "edge_very_long_word", "text": "a" * 500, "expected_behavior": "valid_embedding"},
]

# ---------------------------------------------------------------------------
# 09 — Regression tests (known bugs)
# ---------------------------------------------------------------------------

REGRESSION_TESTS: list[TestCase] = [
    TestCase(
        "reg_001", "regression",
        query="What is the correct RMSNorm formula?",
        text_a="Attention output should be normalized with RMSNorm using weight+1 scaling.",
        text_b="Same normalization with plain RMSNorm without weight+1.",
        expected_relationship="related",
        difficulty="trivial",
        note="RMSNorm must use (1+weight), not weight alone. Regression for RMSNorm fix.",
    ),
    TestCase(
        "reg_002", "regression",
        query="Attention scaling regression",
        text_a="QK^T attention should use single scaling factor 1/sqrt(query_pre_attn_scalar).",
        text_b="Double-scaled attention that divides Q and then QK^T separately.",
        expected_relationship="related",
        difficulty="trivial",
        note="Attention must apply single scaling to QK^T, not pre-divide Q. Regression for double-scaling bug.",
    ),
    TestCase(
        "reg_003", "regression",
        query="GELU activation regression",
        text_a="MLP gate activation uses gelu_pytorch_tanh: 0.5*x*(1+tanh(sqrt(2/pi)*(x+0.044715*x^3))).",
        text_b="MLP gate activation uses SiLU (x*sigmoid(x)).",
        expected_relationship="related",
        difficulty="trivial",
        note="Harrier must use gelu_pytorch_tanh, not SiLU. Regression for activation fix.",
    ),
    TestCase(
        "reg_004", "regression",
        query="Causal mask regression",
        text_a="Attention mask is pure causal (j>i => -inf), all layers full attention.",
        text_b="Attention mask uses sliding window of 512 tokens.",
        expected_relationship="related",
        difficulty="trivial",
        note="All Harrier layers use full causal attention, not sliding window. Regression for mask fix.",
    ),
    TestCase(
        "reg_005", "regression",
        query="Query instruction format regression",
        text_a="Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: How do I change my password?",
        text_b="How do I change my password?",
        expected_relationship="related",
        difficulty="medium",
        note="Query embedding must use instruction prefix. Regression for instruction formatting.",
    ),
]


# ---------------------------------------------------------------------------
# Aggregation helper
# ---------------------------------------------------------------------------

def all_datasets() -> dict[str, Any]:
    """Return all datasets keyed by category name."""
    return {
        "numerical_parity_queries": NUMERICAL_PARITY_SHORT_QUERIES,
        "numerical_parity_documents": NUMERICAL_PARITY_DOCUMENTS,
        "numerical_parity_multilingual": NUMERICAL_PARITY_MULTILINGUAL,
        "numerical_parity_long": NUMERICAL_PARITY_LONG,
        "semantic_pairs": SEMANTIC_POSITIVE_PAIRS,
        "retrieval_dataset": RETRIEVAL_TECH_DOCS,
        "hard_negatives": HARD_NEGATIVE_QUERIES,
        "multilingual_pairs": MULTILINGUAL_PAIRS,
        "multilingual_retrieval": MULTILINGUAL_RETRIEVAL,
        "nvda_realworld": NVDA_REALWORLD_TEXTS,
        "long_context": LONG_CONTEXT_TEXTS,
        "long_context_position": LONG_CONTEXT_POSITION_TESTS,
        "edge_cases": EDGE_CASES,
        "regression": REGRESSION_TESTS,
    }
