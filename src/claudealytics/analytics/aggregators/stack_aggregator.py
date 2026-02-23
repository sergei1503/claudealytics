"""Tech stack analysis: languages, frameworks, ecosystems, dev layers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import pandas as pd
from collections import Counter

# ── Extension → Language mapping ────────────────────────────────

EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".css": "CSS",
    ".scss": "CSS",
    ".less": "CSS",
    ".html": "HTML",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".sql": "SQL",
    ".md": "Markdown",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".json": "Config",
    ".yaml": "Config",
    ".yml": "Config",
    ".toml": "Config",
    ".env": "Config",
    ".ini": "Config",
    ".tf": "Terraform",
    ".dockerfile": "Docker",
    ".proto": "Protobuf",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
}

# ── Layer classification rules ──────────────────────────────────

_FRONTEND_EXTS = {".tsx", ".jsx", ".css", ".scss", ".less", ".html", ".vue", ".svelte"}
_BACKEND_EXTS = {".py", ".java", ".go", ".rs", ".rb", ".php", ".kt", ".cs"}
_INFRA_EXTS = {".tf", ".dockerfile"}
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".env", ".ini"}
_DOC_EXTS = {".md"}

_FRONTEND_PATHS = re.compile(r"(^|/)(?:components|pages|styles|public|src/app|src/pages|layouts|views)/", re.I)
_BACKEND_PATHS = re.compile(r"(^|/)(?:api|routes|middleware|models|services|controllers|handlers|lib)/", re.I)
_INFRA_PATHS = re.compile(r"(^|/)(?:\.github/workflows|k8s|helm|deploy|terraform|infra|docker)/", re.I)
_DOC_PATHS = re.compile(r"(^|/)docs/", re.I)

# ── Framework detection patterns ────────────────────────────────

_FRAMEWORK_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("Next.js", re.compile(r"(^|/)next\.config\.\w+$"), "config"),
    ("Next.js", re.compile(r"(^|/)app/(page|layout)\.\w+$"), "path"),
    ("React", re.compile(r"\.tsx$|\.jsx$"), "ext"),
    ("Django", re.compile(r"(^|/)(?:manage\.py|urls\.py|wsgi\.py|asgi\.py)$"), "config"),
    ("Django", re.compile(r"(^|/)migrations/\d+"), "path"),
    ("Flask", re.compile(r"(^|/)app\.py$"), "config"),
    ("FastAPI", re.compile(r"(^|/)(?:main\.py|routers/)"), "path"),
    ("Streamlit", re.compile(r"streamlit"), "path"),
    ("Vue.js", re.compile(r"\.vue$"), "ext"),
    ("Svelte", re.compile(r"\.svelte$"), "ext"),
    ("Tailwind CSS", re.compile(r"tailwind\.config"), "config"),
    ("Prisma", re.compile(r"schema\.prisma$"), "config"),
    ("Express.js", re.compile(r"(^|/)(?:express|app)\.\w+$"), "config"),
    ("Angular", re.compile(r"angular\.json$|\.component\.ts$"), "config"),
]

# ── Database signal patterns ────────────────────────────────────

_DB_FILE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("PostgreSQL", re.compile(r"postgres|psql|\.sql$", re.I)),
    ("SQLite", re.compile(r"sqlite|\.db$", re.I)),
    ("MongoDB", re.compile(r"mongo", re.I)),
    ("Redis", re.compile(r"redis", re.I)),
    ("Prisma", re.compile(r"prisma", re.I)),
    ("Neon", re.compile(r"neon", re.I)),
]

_DB_BASH_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("PostgreSQL", re.compile(r"\bpsql\b")),
    ("MongoDB", re.compile(r"\bmongosh?\b")),
    ("Redis", re.compile(r"\bredis-cli\b")),
    ("SQLite", re.compile(r"\bsqlite3\b")),
    ("MySQL", re.compile(r"\bmysql\b")),
    ("Neon", re.compile(r"\bneon\b")),
]

# ── Ecosystem detection from bash commands ──────────────────────

_ECOSYSTEM_BASH_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Node.js", re.compile(r"\b(?:npm|npx|yarn|pnpm|bun)\b")),
    ("Python", re.compile(r"\b(?:pip|python3?|uv|poetry|conda)\b")),
    ("Go", re.compile(r"\bgo (?:build|run|test|mod)\b")),
    ("Rust", re.compile(r"\b(?:cargo|rustc)\b")),
    ("Docker", re.compile(r"\bdocker\b")),
    ("Kubernetes", re.compile(r"\b(?:kubectl|helm)\b")),
    ("Terraform", re.compile(r"\bterraform\b")),
    ("GCP", re.compile(r"\bgcloud\b")),
    ("AWS", re.compile(r"\baws\b")),
    ("Vercel", re.compile(r"\bvercel\b")),
]


def _get_extension(file_path: str) -> str:
    """Extract normalized extension from a file path."""
    if not file_path:
        return ""
    name = PurePosixPath(file_path).name.lower()
    # Handle Dockerfile specially
    if name == "dockerfile" or name.startswith("dockerfile."):
        return ".dockerfile"
    if "." in name:
        return "." + name.rsplit(".", 1)[-1]
    return ""


def _classify_layer(file_path: str, ext: str) -> str:
    """Classify a file into a development layer."""
    if not file_path:
        return "Unknown"
    fp = file_path

    # Check path patterns first (more specific)
    if _INFRA_PATHS.search(fp):
        return "Infra"
    if _DOC_PATHS.search(fp):
        return "Docs"
    if _FRONTEND_PATHS.search(fp):
        return "Frontend"
    if _BACKEND_PATHS.search(fp):
        return "Backend"

    # Fall back to extension
    if ext in _FRONTEND_EXTS:
        return "Frontend"
    if ext in _BACKEND_EXTS:
        return "Backend"
    if ext in _INFRA_EXTS:
        return "Infra"
    if ext in _CONFIG_EXTS:
        return "Config"
    if ext in _DOC_EXTS:
        return "Docs"
    return "Other"


# ── Public API ──────────────────────────────────────────────────

def compute_language_distribution(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """File extension → language mapping with read/write/edit breakdowns."""
    if tool_calls.empty or "file_path" not in tool_calls.columns:
        return pd.DataFrame(columns=["language", "total", "reads", "writes", "edits"])

    df = tool_calls[tool_calls["file_path"].notna() & (tool_calls["file_path"] != "")].copy()
    if df.empty:
        return pd.DataFrame(columns=["language", "total", "reads", "writes", "edits"])

    df["extension"] = df["file_path"].apply(_get_extension)
    df["language"] = df["extension"].map(EXTENSION_LANGUAGE).fillna("Other")

    reads = df[df["tool_name"].isin(["Read", "Glob", "Grep"])].groupby("language").size()
    writes = df[df["tool_name"] == "Write"].groupby("language").size()
    edits = df[df["tool_name"] == "Edit"].groupby("language").size()

    all_langs = set(reads.index) | set(writes.index) | set(edits.index)
    rows = []
    for lang in all_langs:
        r = int(reads.get(lang, 0))
        w = int(writes.get(lang, 0))
        e = int(edits.get(lang, 0))
        rows.append({"language": lang, "total": r + w + e, "reads": r, "writes": w, "edits": e})

    result = pd.DataFrame(rows).sort_values("total", ascending=False)
    return result.reset_index(drop=True)


def compute_language_daily(tool_calls: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    """Daily language counts for top N languages (for stacked area chart)."""
    if tool_calls.empty or "file_path" not in tool_calls.columns:
        return pd.DataFrame(columns=["date", "language", "count"])

    df = tool_calls[tool_calls["file_path"].notna() & (tool_calls["file_path"] != "")].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "language", "count"])

    df["extension"] = df["file_path"].apply(_get_extension)
    df["language"] = df["extension"].map(EXTENSION_LANGUAGE).fillna("Other")
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date

    # Identify top N languages
    top_langs = df["language"].value_counts().head(top_n).index.tolist()
    df.loc[~df["language"].isin(top_langs), "language"] = "Other"

    daily = df.groupby(["date", "language"]).size().reset_index(name="count")
    return daily


def compute_ecosystem_signals(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Ecosystem signals from bash categories, config files, and bash commands."""
    if tool_calls.empty:
        return pd.DataFrame(columns=["ecosystem", "signal_count", "signal_type"])

    rows: list[dict] = []

    # 1. Bash command category signals
    if "command_category" in tool_calls.columns:
        cats = tool_calls[tool_calls["command_category"].notna()]
        cat_counts = cats["command_category"].value_counts()
        category_ecosystem = {
            "git": "Git",
            "npm": "Node.js",
            "docker": "Docker",
            "k8s": "Kubernetes",
            "python": "Python",
        }
        for cat, eco in category_ecosystem.items():
            if cat in cat_counts.index:
                rows.append({"ecosystem": eco, "signal_count": int(cat_counts[cat]), "signal_type": "bash_category"})

    # 2. Config file signals
    if "file_path" in tool_calls.columns:
        files = tool_calls[tool_calls["file_path"].notna()]["file_path"]
        config_signals = {
            "package.json": "Node.js",
            "tsconfig.json": "TypeScript",
            "pyproject.toml": "Python",
            "requirements.txt": "Python",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "Gemfile": "Ruby",
            "docker-compose": "Docker",
            "Dockerfile": "Docker",
            "vercel.json": "Vercel",
            ".vercel": "Vercel",
        }
        for pattern, eco in config_signals.items():
            count = int(files.str.contains(pattern, case=False, na=False).sum())
            if count > 0:
                rows.append({"ecosystem": eco, "signal_count": count, "signal_type": "config_file"})

    # 3. Bash command text signals
    if "bash_command" in tool_calls.columns:
        bash_cmds = tool_calls[tool_calls["bash_command"].notna()]["bash_command"]
        for eco, pattern in _ECOSYSTEM_BASH_PATTERNS:
            count = int(bash_cmds.str.contains(pattern, na=False).sum())
            if count > 0:
                rows.append({"ecosystem": eco, "signal_count": count, "signal_type": "bash_command"})

    if not rows:
        return pd.DataFrame(columns=["ecosystem", "signal_count", "signal_type"])

    result = pd.DataFrame(rows)
    # Aggregate by ecosystem (sum across signal types)
    return result


def compute_framework_detection(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Detect frameworks from file path patterns."""
    if tool_calls.empty or "file_path" not in tool_calls.columns:
        return pd.DataFrame(columns=["framework", "file_count", "confidence"])

    files = tool_calls[tool_calls["file_path"].notna()]["file_path"]
    if files.empty:
        return pd.DataFrame(columns=["framework", "file_count", "confidence"])

    framework_counts: Counter = Counter()
    framework_types: dict[str, set] = {}

    for fw, pattern, sig_type in _FRAMEWORK_PATTERNS:
        count = int(files.str.contains(pattern, na=False).sum())
        if count > 0:
            framework_counts[fw] += count
            framework_types.setdefault(fw, set()).add(sig_type)

    if not framework_counts:
        return pd.DataFrame(columns=["framework", "file_count", "confidence"])

    rows = []
    for fw, count in framework_counts.most_common():
        types = framework_types.get(fw, set())
        # Higher confidence if detected via config files
        confidence = "high" if "config" in types else "medium" if count > 5 else "low"
        rows.append({"framework": fw, "file_count": count, "confidence": confidence})

    return pd.DataFrame(rows)


def compute_layer_classification(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Classify files into development layers (Frontend/Backend/Infra/Config/Docs)."""
    if tool_calls.empty or "file_path" not in tool_calls.columns:
        return pd.DataFrame(columns=["layer", "file_count", "pct"])

    df = tool_calls[tool_calls["file_path"].notna() & (tool_calls["file_path"] != "")].copy()
    if df.empty:
        return pd.DataFrame(columns=["layer", "file_count", "pct"])

    df["extension"] = df["file_path"].apply(_get_extension)
    df["layer"] = df.apply(lambda r: _classify_layer(r["file_path"], r["extension"]), axis=1)

    layer_counts = df["layer"].value_counts().reset_index()
    layer_counts.columns = ["layer", "file_count"]
    total = layer_counts["file_count"].sum()
    layer_counts["pct"] = round(layer_counts["file_count"] / total * 100, 1)

    return layer_counts


def compute_database_signals(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Detect database technologies from file paths and bash commands."""
    if tool_calls.empty:
        return pd.DataFrame(columns=["database", "signal_count"])

    counts: Counter = Counter()

    # File path patterns
    if "file_path" in tool_calls.columns:
        files = tool_calls[tool_calls["file_path"].notna()]["file_path"]
        for db, pattern in _DB_FILE_PATTERNS:
            c = int(files.str.contains(pattern, na=False).sum())
            if c > 0:
                counts[db] += c

    # Bash command patterns
    if "bash_command" in tool_calls.columns:
        bash_cmds = tool_calls[tool_calls["bash_command"].notna()]["bash_command"]
        for db, pattern in _DB_BASH_PATTERNS:
            c = int(bash_cmds.str.contains(pattern, na=False).sum())
            if c > 0:
                counts[db] += c

    if not counts:
        return pd.DataFrame(columns=["database", "signal_count"])

    rows = [{"database": db, "signal_count": cnt} for db, cnt in counts.most_common()]
    return pd.DataFrame(rows)


def compute_project_profiles(tool_calls: pd.DataFrame, session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per-project tech stack summary."""
    if tool_calls.empty or "file_path" not in tool_calls.columns:
        return pd.DataFrame(columns=["project", "primary_language", "languages", "frameworks", "layer_split", "session_count"])

    # Derive project from file_path (first meaningful directory component)
    df = tool_calls[tool_calls["file_path"].notna() & (tool_calls["file_path"] != "")].copy()
    if df.empty:
        return pd.DataFrame(columns=["project", "primary_language", "languages", "frameworks", "layer_split", "session_count"])

    df["extension"] = df["file_path"].apply(_get_extension)
    df["language"] = df["extension"].map(EXTENSION_LANGUAGE).fillna("Other")
    df["layer"] = df.apply(lambda r: _classify_layer(r["file_path"], r["extension"]), axis=1)

    # Extract project name from session_stats if available
    if not session_stats.empty and "project" in session_stats.columns:
        session_project = session_stats.set_index("session_id")["project"].to_dict()
        df["project"] = df["session_id"].map(session_project).fillna("unknown")
    else:
        df["project"] = "unknown"

    rows = []
    for project, grp in df.groupby("project"):
        if project == "unknown":
            continue

        lang_counts = grp["language"].value_counts()
        primary_lang = lang_counts.index[0] if len(lang_counts) > 0 else "Unknown"
        top_langs = lang_counts.head(5).index.tolist()

        # Framework detection for this project
        files = grp["file_path"]
        fw_set = set()
        for fw, pattern, _ in _FRAMEWORK_PATTERNS:
            if files.str.contains(pattern, na=False).any():
                fw_set.add(fw)

        # Layer split
        layer_counts = grp["layer"].value_counts()
        total = layer_counts.sum()
        layer_pcts = {l: round(c / total * 100) for l, c in layer_counts.items()} if total > 0 else {}

        # Session count
        sess_count = grp["session_id"].nunique()

        rows.append({
            "project": str(project),
            "primary_language": primary_lang,
            "languages": ", ".join(top_langs),
            "frameworks": ", ".join(sorted(fw_set)) if fw_set else "-",
            "layer_split": " / ".join(f"{l}:{p}%" for l, p in sorted(layer_pcts.items(), key=lambda x: -x[1])),
            "session_count": sess_count,
        })

    if not rows:
        return pd.DataFrame(columns=["project", "primary_language", "languages", "frameworks", "layer_split", "session_count"])

    result = pd.DataFrame(rows).sort_values("session_count", ascending=False)
    return result.reset_index(drop=True)
