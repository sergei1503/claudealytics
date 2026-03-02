"""
Single-pass content mining from conversation JSONL files.

Streams line-by-line through all JSONL files, extracting structural
metrics about human interventions, assistant behavior, tool sequences,
file activity, and error patterns. Aggregates during scan to keep
memory and cache size manageable (~40MB for 2GB of JSONL).

Uses file-level caching with 1-hour TTL, same pattern as TokenMiner.
"""

import difflib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ── Regex patterns (compiled once) ──────────────────────────────

_CORRECTION_RE = re.compile(
    r"(?:"
    # "no, " — explicit negation, but NOT when followed by approval words
    # (prevents "No, that looks good" from being classified as correction)
    r"\bno,\s(?!.*\b(?:looks?\s+good|that'?s?\s+(?:fine|good|great|perfect|right)|go\s+ahead|proceed)\b)"
    r"|\bwrong\b(?!\s+with)"  # "wrong" but not "wrong with" (diagnostic)
    r"|\bthat'?s\s+not\b"  # "that's not"
    r"|\bnot\s+what\s+I\b"  # "not what I"
    r"|\brevert\b"  # revert
    r"|\bundo\b"  # undo
    r"|\broll\s*back\b"  # roll back
    r"|\bthat\s+broke\b"  # that broke
    r"|\bstop\s*[.!]"  # "stop." or "stop!" — standalone
    r"|\bstop\s+doing\b"  # "stop doing"
    r")",
    re.IGNORECASE,
)
_APPROVAL_RE = re.compile(
    r"(?:"
    r"(?:^|\s)yes(?:\s|[,!.]|$)"  # "yes" standalone (not "yesterday")
    r"|\blooks\s+good\b"  # "looks good"
    r"|\bgo\s+ahead\b"  # "go ahead"
    r"|\bproceed\b"  # "proceed"
    r"|\blgtm\b"  # "lgtm"
    r"|\bapproved\b"  # "approved"
    r"|\bperfect\b"  # "perfect"
    r"|\bship\s+it\b"  # "ship it"
    r"|\bmerge\s+it\b"  # "merge it"
    r"|\bdo\s+it\b"  # "do it"
    r"|\bthat\s+works\b"  # "that works"
    r"|\bsounds\s+good\b"  # "sounds good"
    r"|\bsure(?:\s+thing|\s*,\s*go)|\bsure\s*[.!]?\s*$"  # "sure thing", "sure, go", "sure." at end
    r"|\bgreat(?:\s*[,!.]\s*(?:thanks|thank|go|yes|do)|\s*[!.]\s*$)"  # "great, thanks" / "great!" at end
    r")",
    re.IGNORECASE | re.MULTILINE,
)
# Require leading /, ./, ~/, or common directory prefixes to reduce false positives
_FILE_PATH_RE = re.compile(
    r"(?:"
    r"(?:^|[\s'\"`(])(?:~/|\.{1,2}/|(?:/(?:Users|home|var|etc|usr|opt|tmp|src|repos|projects)/))"
    r"[\w./-]+"
    r"|(?:^|[\s'\"`(])/(?:[\w.-]+/){1,}[\w.-]+"
    r")"
)
_CODE_BLOCK_RE = re.compile(r"```")
_DECISION_RE = re.compile(
    r"\b(chose|decided|opting|went with|choosing|using|going with|selected)\b.*\b(because|since|due to)\b",
    re.IGNORECASE,
)
# Tightened to require correction context: "actually" and "wait" alone match too
# broadly (normal explanatory text). Require correction-specific follow-up words.
_SELF_CORRECTION_RE = re.compile(
    r"(?:"
    r"\bactually,?\s+(?:I|that|this|it)\s+(?:should|was|is\s+wrong|need|made)\b"
    r"|(?:^|\.\s+)wait,?\s+"  # sentence-initial "wait," — less likely in normal text
    r"|\blet me reconsider\b"
    r"|\bon second thought\b"
    r"|\bI was wrong\b"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
# Strip fenced code blocks before checking for questions/inline code
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_REASONING_MARKER_RE = re.compile(
    r"^(Note:|Approach:|Decision:|Trade-off:|Rationale:|Reasoning:)",
    re.MULTILINE,
)
_BASH_CMD_CATEGORY = {
    "git": "git",
    "npm": "npm",
    "npx": "npm",
    "yarn": "npm",
    "pnpm": "npm",
    "docker": "docker",
    "kubectl": "docker",
    "pip": "pip",
    "python": "python",
    "python3": "python",
    "node": "node",
    "tsx": "node",
    "bun": "npm",
    "cargo": "cargo",
    "make": "build",
    "cmake": "build",
    "cd": "navigation",
    "ls": "navigation",
    "pwd": "navigation",
    "cat": "file_ops",
    "head": "file_ops",
    "tail": "file_ops",
    "grep": "search",
    "rg": "search",
    "find": "search",
    "curl": "network",
    "wget": "network",
    "pm2": "process",
    "pkill": "process",
    "kill": "process",
    "lsof": "process",
}

# ── Edit classification patterns (compiled at module level) ───
_ERROR_KW_RE = re.compile(r"\b(try|catch|except|finally|raise|throw|Error|Exception)\b")
_TYPE_KW_RE = re.compile(r"(?::\s*\w+[\[\]|,\s]*(?:=|$)|\bOptional\b|\bUnion\b|\bList\b|\bDict\b|->)")

# Git revert/undo detection in bash commands
_GIT_REVERT_RE = re.compile(
    r"\bgit\s+(?:checkout\s+--|reset\b|revert\b|restore\b)",
    re.IGNORECASE,
)

# ── Install / test / edit classification patterns ─────────────

_INSTALL_RE = {
    "pip": re.compile(r"\bpip3?\s+install\s+(.+?)(?:\s*&&|\s*;|\s*\||$)", re.I),
    "npm": re.compile(r"\bnpm\s+install\s+(?:--save(?:-dev)?\s+)?(.+?)(?:\s*&&|\s*;|\s*\||$)", re.I),
    "yarn": re.compile(r"\byarn\s+add\s+(.+?)(?:\s*&&|\s*;|\s*\||$)", re.I),
    "pnpm": re.compile(r"\bpnpm\s+add\s+(.+?)(?:\s*&&|\s*;|\s*\||$)", re.I),
    "cargo": re.compile(r"\bcargo\s+add\s+(\S+)", re.I),
    "go": re.compile(r"\bgo\s+get\s+(\S+)", re.I),
}

_TEST_CMD_RE = re.compile(
    r"\b(?:pytest|python3?\s+-m\s+(?:pytest|unittest))\b|"
    r"\b(?:npx\s+(?:jest|vitest|mocha))\b|"
    r"\b(?:npm\s+(?:run\s+)?test|yarn\s+test|pnpm\s+test)\b|"
    r"\b(?:cargo\s+test|go\s+test)\b|"
    r"(?:^|\s|&&\s*|;\s*)(?:jest|vitest|mocha)\b",
    re.I,
)

_INSTALL_CMD_RE = re.compile(r"\b(?:pip3?\s+install|npm\s+install|yarn\s+add|pnpm\s+add|cargo\s+add|go\s+get)\b", re.I)

_IMPORT_LINE_RE = re.compile(r"^\s*(?:import |from \S+ import |require\(|const .+ = require|export )", re.M)


def _extract_install_packages(cmd: str) -> str | None:
    """Extract installed packages from a command string.

    Returns 'manager:pkg1,manager:pkg2' or None.
    """
    parts = []
    for manager, pattern in _INSTALL_RE.items():
        m = pattern.search(cmd)
        if m:
            raw = m.group(1).strip()
            # Split on whitespace, skip flags
            for token in raw.split():
                if token.startswith("-"):
                    continue
                parts.append(f"{manager}:{token}")
    return ",".join(parts) if parts else None


def _is_test_command(cmd: str, description: str) -> bool:
    """Return True if the command is running tests (not installing test packages)."""
    if _INSTALL_CMD_RE.search(cmd):
        return False
    return bool(_TEST_CMD_RE.search(cmd) or _TEST_CMD_RE.search(description))


def _classify_edit(old_str: str, new_str: str) -> str:
    """Classify an edit operation by its semantic category.

    Uses difflib.SequenceMatcher to distinguish minor tweaks from structural
    changes. Module-level compiled regexes are used for all keyword checks.
    """
    if not old_str and new_str:
        if _IMPORT_LINE_RE.search(new_str):
            return "import_add"
        return "addition"
    if old_str and not new_str:
        return "deletion"

    # Check if adding imports
    old_imports = len(_IMPORT_LINE_RE.findall(old_str))
    new_imports = len(_IMPORT_LINE_RE.findall(new_str))
    if new_imports > old_imports:
        return "import_add"

    # Check for error handling additions (uses module-level compiled regex)
    old_err = len(_ERROR_KW_RE.findall(old_str))
    new_err = len(_ERROR_KW_RE.findall(new_str))
    if new_err > old_err:
        return "error_handling"

    # Check for type annotation additions (uses module-level compiled regex)
    old_types = len(_TYPE_KW_RE.findall(old_str))
    new_types = len(_TYPE_KW_RE.findall(new_str))
    if new_types > old_types:
        return "type_annotation"

    # Use SequenceMatcher to distinguish minor tweaks from structural changes
    similarity = difflib.SequenceMatcher(None, old_str, new_str).ratio()

    # Check if only string literals changed (string swap)
    old_no_strings = re.sub(r'["\'].*?["\']', '""', old_str)
    new_no_strings = re.sub(r'["\'].*?["\']', '""', new_str)
    if old_no_strings == new_no_strings and old_str != new_str:
        return "string_change"

    # Check if only identifier names changed (rename): same non-word punctuation structure
    # Only apply when similarity is high (same shape) to avoid over-matching
    if similarity > 0.6:
        old_structure = re.sub(r"\b[a-zA-Z_]\w*\b", "ID", old_str)
        new_structure = re.sub(r"\b[a-zA-Z_]\w*\b", "ID", new_str)
        if old_structure == new_structure:
            return "rename"

    # High similarity: minor config-level change (e.g. number/constant swap)
    if similarity > 0.85:
        return "config_change"

    # Low similarity: structural/logic change
    if similarity < 0.5:
        return "logic_change"

    return "refactor"


class ContentMiner:
    """Mines conversation content structure from JSONL files."""

    CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self, cache_dir: Path | None = None):
        self.projects_dir = Path.home() / ".claude" / "projects"
        self.cache_dir = cache_dir or Path.home() / ".cache" / "claudealytics"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / "content-mine.json"

    def _get_all_jsonl_files(self) -> list[Path]:
        """Get all main JSONL files recursively, skipping agent-*.jsonl.

        Agent subconversation files are excluded to match ConversationParser
        behavior and avoid double-counting tool calls from agent sidechains.
        """
        if not self.projects_dir.exists():
            return []
        all_files = []
        dropped = 0
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                for f in project_dir.rglob("*.jsonl"):
                    if f.name.startswith("agent-"):
                        dropped += 1
                    else:
                        all_files.append(f)
        if dropped:
            logger.debug("Skipped %d agent-*.jsonl files", dropped)
        return sorted(all_files, key=lambda f: f.stat().st_mtime)

    def _load_cache(self) -> dict | None:
        if not self.cache_path.exists():
            return None
        try:
            with open(self.cache_path) as f:
                cached = json.load(f)
            if cached.get("timestamp", 0) > datetime.now().timestamp() - self.CACHE_TTL_SECONDS:
                return cached.get("data")
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _save_cache(self, data: dict):
        cache_data = {"timestamp": datetime.now().timestamp(), "data": data}
        with open(self.cache_path, "w") as f:
            json.dump(cache_data, f)

    @staticmethod
    def _extract_project_name(file_path: Path) -> str:
        projects_dir = Path.home() / ".claude" / "projects"
        _SKIP_SEGMENTS = {"users", "home", "repos", "projects", "src", "root"}
        try:
            rel = file_path.relative_to(projects_dir)
            project_dir = rel.parts[0] if rel.parts else "unknown"
            parts = project_dir.strip("-").split("-")
            meaningful = [p for p in parts if p.lower() not in _SKIP_SEGMENTS and p]
            if len(meaningful) >= 2:
                return "-".join(meaningful[-2:])
            elif meaningful:
                return meaningful[-1]
        except ValueError:
            pass
        return "unknown"

    def mine(self, use_cache: bool = True) -> dict:
        """Run single-pass extraction over all JSONL files.

        Returns dict with keys: session_stats, tool_calls, error_results,
        daily_stats, human_message_lengths.
        """
        if use_cache:
            cached = self._load_cache()
            if cached:
                return cached

        # ── Accumulators ──
        # session_id -> session-level counters
        sessions: dict[str, dict] = {}
        # Per-session message ordering for autonomy calculation
        session_msg_roles: dict[str, list[str]] = defaultdict(list)
        # Per-session file tracking (for unique files count)
        session_files: dict[str, set] = defaultdict(set)
        # Per-session cwd tracking
        session_cwds: dict[str, set] = defaultdict(set)
        # Per-session read-before-write tracking: file_path -> was_read
        session_reads: dict[str, set] = defaultdict(set)
        # tool_use_id -> (session_id, tool_name, file_path) for matching results
        # Note: cleared per-file to prevent unbounded growth
        pending_tool_uses: dict[str, tuple] = {}
        # Per-session ordered timestamps for inter-message timing (Phase 6.1)
        session_timestamps: dict[str, list[str]] = defaultdict(list)

        # Output lists
        tool_calls: list[dict] = []
        error_results: list[dict] = []
        human_message_lengths: list[dict] = []

        # Daily aggregation
        daily: dict[str, dict] = defaultdict(
            lambda: {
                "date": "",
                "human_messages": 0,
                "assistant_messages": 0,
                "total_tool_calls": 0,
                "total_errors": 0,
                "intervention_correction": 0,
                "intervention_approval": 0,
                "intervention_guidance": 0,
                "intervention_new_instruction": 0,
                "thinking_blocks": 0,
                "decision_count": 0,
                "self_correction_count": 0,
                "reasoning_marker_count": 0,
                "total_text_length_human": 0,
                "total_text_length_assistant": 0,
                "total_thinking_length": 0,
                "messages_with_code_blocks": 0,
                "unique_sessions": set(),
                "unique_files": set(),
            }
        )

        for file_path in self._get_all_jsonl_files():
            project_name = self._extract_project_name(file_path)
            # Clear per-file to prevent unbounded growth across many sessions
            pending_tool_uses.clear()
            try:
                with open(file_path) as f:
                    for line in f:
                        # Fast-path skip
                        if '"progress"' in line[:50] or '"file-history-snapshot"' in line[:80]:
                            continue
                        if '"queue-operation"' in line[:50]:
                            continue

                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        line_type = data.get("type")
                        if line_type not in ("user", "assistant"):
                            continue

                        session_id = data.get("sessionId", "")
                        if not session_id:
                            continue

                        timestamp = data.get("timestamp", "")
                        date_str = timestamp[:10] if timestamp else ""
                        if not date_str:
                            continue

                        is_sidechain = data.get("isSidechain", False)
                        cwd = data.get("cwd", "")
                        git_branch = data.get("gitBranch", "")
                        uuid = data.get("uuid", "")
                        data.get("parentUuid", "")

                        # Initialize session if needed
                        if session_id not in sessions:
                            sessions[session_id] = {
                                "session_id": session_id,
                                "date": date_str,
                                "project": project_name,
                                "cwd": cwd,
                                "git_branch": git_branch,
                                "human_msg_count": 0,
                                "assistant_msg_count": 0,
                                "total_messages": 0,
                                "total_text_length_human": 0,
                                "total_text_length_assistant": 0,
                                "total_thinking_length": 0,
                                "thinking_message_count": 0,
                                "total_tool_calls": 0,
                                "total_errors": 0,
                                "unique_tools": set(),
                                "sidechain_count": 0,
                                "intervention_correction": 0,
                                "intervention_approval": 0,
                                "intervention_guidance": 0,
                                "intervention_new_instruction": 0,
                                "human_questions_count": 0,
                                "human_with_code_count": 0,
                                "human_with_file_paths_count": 0,
                                "decision_count": 0,
                                "self_correction_count": 0,
                                "reasoning_marker_count": 0,
                                "total_input_tokens": 0,
                                "total_output_tokens": 0,
                                "total_edits": 0,
                                "total_writes": 0,
                                "total_reads": 0,
                                "writes_with_prior_read_count": 0,
                                "writes_total_count": 0,
                                "has_code_blocks": 0,
                                "git_revert_count": 0,
                                "fast_approval_count": 0,
                            }

                        s = sessions[session_id]
                        s["total_messages"] += 1

                        if is_sidechain:
                            s["sidechain_count"] += 1

                        if cwd:
                            session_cwds[session_id].add(cwd)

                        # Daily tracking
                        d = daily[date_str]
                        d["date"] = date_str
                        d["unique_sessions"].add(session_id)

                        msg = data.get("message", {})
                        if not isinstance(msg, dict):
                            continue
                        content = msg.get("content", [])
                        if not isinstance(content, list):
                            content = []

                        # Track timestamp for inter-message timing (Phase 6.1)
                        if timestamp:
                            session_timestamps[session_id].append(timestamp)

                        # ── USER MESSAGE ──
                        if line_type == "user":
                            # Extract text from content blocks
                            text_parts = []
                            has_tool_result = False
                            for block in content:
                                if isinstance(block, dict):
                                    if block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                                    elif block.get("type") == "tool_result":
                                        has_tool_result = True
                                        tool_use_id = block.get("tool_use_id", "")
                                        is_error = bool(block.get("is_error"))
                                        c = block.get("content", "")
                                        content_length = len(c) if isinstance(c, str) else 0

                                        if is_error and tool_use_id:
                                            error_results.append(
                                                {
                                                    "session_id": session_id,
                                                    "timestamp": timestamp,
                                                    "tool_use_id": tool_use_id,
                                                    "content_length": content_length,
                                                }
                                            )
                                            s["total_errors"] += 1
                                            d["total_errors"] += 1
                                elif isinstance(block, str):
                                    text_parts.append(block)

                            full_text = " ".join(text_parts)
                            text_length = len(full_text)
                            word_count = len(full_text.split()) if full_text.strip() else 0

                            # Only count as human message if there's actual user text
                            # (tool_result-only or empty messages are not human messages)
                            is_human_message = bool(full_text.strip())

                            if is_human_message:
                                s["human_msg_count"] += 1
                                d["human_messages"] += 1
                                session_msg_roles[session_id].append("user")
                                s["total_text_length_human"] += text_length
                                d["total_text_length_human"] += text_length

                            # Skip classification for tool-result-only messages
                            if text_parts and not (has_tool_result and not full_text.strip()):
                                # Classify intervention type
                                # Check correction BEFORE approval to avoid
                                # misclassifying short corrections like "no, wrong"
                                classification = "new_instruction"
                                if _CORRECTION_RE.search(full_text):
                                    classification = "correction"
                                elif text_length < 150 and _APPROVAL_RE.search(full_text):
                                    classification = "approval"
                                elif (
                                    _FILE_PATH_RE.search(full_text)
                                    or _CODE_BLOCK_RE.search(full_text)
                                    or word_count > 100
                                ):
                                    classification = "guidance"

                                s[f"intervention_{classification}"] += 1
                                d[f"intervention_{classification}"] += 1

                                # Question detection: strip fenced code, inline code,
                                # and URLs before checking for ? to avoid false positives
                                text_no_code = _FENCED_CODE_RE.sub("", full_text)
                                text_no_code = _INLINE_CODE_RE.sub("", text_no_code)
                                text_no_code = re.sub(r"https?://\S+", "", text_no_code)
                                if re.search(r"\?\s|\?$", text_no_code):
                                    s["human_questions_count"] += 1
                                # Code detection: triple backticks or proper inline code
                                if "```" in full_text or _INLINE_CODE_RE.search(full_text):
                                    s["human_with_code_count"] += 1
                                if _FILE_PATH_RE.search(full_text):
                                    s["human_with_file_paths_count"] += 1

                                human_message_lengths.append(
                                    {
                                        "session_id": session_id,
                                        "text_length": text_length,
                                        "word_count": word_count,
                                        "classification": classification,
                                    }
                                )

                        # ── ASSISTANT MESSAGE ──
                        elif line_type == "assistant":
                            s["assistant_msg_count"] += 1
                            d["assistant_messages"] += 1
                            session_msg_roles[session_id].append("assistant")

                            msg.get("model", "")
                            msg.get("stop_reason", "")
                            usage = msg.get("usage", {})
                            if isinstance(usage, dict):
                                s["total_input_tokens"] += usage.get("input_tokens", 0) or 0
                                s["total_output_tokens"] += usage.get("output_tokens", 0) or 0

                            msg_has_thinking = False
                            msg_has_code = False
                            msg_text_length = 0
                            msg_tool_count = 0

                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                block_type = block.get("type")

                                if block_type == "text":
                                    text = block.get("text", "")
                                    msg_text_length += len(text)
                                    if "```" in text:
                                        msg_has_code = True
                                    # Decision pattern detection
                                    if _DECISION_RE.search(text):
                                        s["decision_count"] += 1
                                        d["decision_count"] += 1
                                    if _SELF_CORRECTION_RE.search(text):
                                        s["self_correction_count"] += 1
                                        d["self_correction_count"] += 1
                                    if _REASONING_MARKER_RE.search(text):
                                        s["reasoning_marker_count"] += 1
                                        d["reasoning_marker_count"] += 1

                                elif block_type == "thinking":
                                    thinking_text = block.get("thinking", "")
                                    thinking_len = len(thinking_text)
                                    s["total_thinking_length"] += thinking_len
                                    d["total_thinking_length"] += thinking_len
                                    d["thinking_blocks"] += 1
                                    msg_has_thinking = True

                                elif block_type == "tool_use":
                                    msg_tool_count += 1
                                    s["total_tool_calls"] += 1
                                    d["total_tool_calls"] += 1

                                    tool_name = block.get("name", "")
                                    s["unique_tools"].add(tool_name)
                                    tool_id = block.get("id", "")
                                    inp = block.get("input", {})
                                    if not isinstance(inp, dict):
                                        inp = {}

                                    file_path_val = None
                                    edit_delta = None
                                    bytes_written = None
                                    command_category = None
                                    bash_command = None
                                    install_packages = None
                                    is_test_command = False
                                    bash_description = None
                                    search_query = None
                                    fetch_url = None
                                    grep_pattern = None
                                    edit_category = None
                                    is_git_revert = False

                                    if tool_name in ("Read", "Glob"):
                                        file_path_val = inp.get("file_path") or inp.get("path", "")
                                        if file_path_val:
                                            s["total_reads"] += 1
                                            session_files[session_id].add(file_path_val)
                                            session_reads[session_id].add(file_path_val)

                                    elif tool_name == "Write":
                                        file_path_val = inp.get("file_path", "")
                                        content_val = inp.get("content", "")
                                        bytes_written = len(content_val)
                                        s["total_writes"] += 1
                                        s["writes_total_count"] += 1
                                        if file_path_val:
                                            session_files[session_id].add(file_path_val)
                                            if file_path_val in session_reads[session_id]:
                                                s["writes_with_prior_read_count"] += 1

                                    elif tool_name == "Edit":
                                        file_path_val = inp.get("file_path", "")
                                        old_str = inp.get("old_string", "")
                                        new_str = inp.get("new_string", "")
                                        edit_delta = len(new_str) - len(old_str)
                                        edit_category = _classify_edit(old_str, new_str)
                                        s["total_edits"] += 1
                                        s["writes_total_count"] += 1
                                        if file_path_val:
                                            session_files[session_id].add(file_path_val)
                                            if file_path_val in session_reads[session_id]:
                                                s["writes_with_prior_read_count"] += 1

                                    elif tool_name == "Bash":
                                        cmd = inp.get("command", "")
                                        first_word = cmd.split()[0] if cmd.strip() else ""
                                        command_category = _BASH_CMD_CATEGORY.get(first_word, "other")
                                        bash_command = cmd[:100] if cmd else None
                                        bash_description = inp.get("description", "")[:200] or None
                                        install_packages = _extract_install_packages(cmd)
                                        is_test_command = _is_test_command(cmd, bash_description or "")
                                        # Phase 6.4: detect git revert/undo operations
                                        if cmd and _GIT_REVERT_RE.search(cmd):
                                            s["git_revert_count"] += 1
                                            is_git_revert = True

                                    elif tool_name == "Grep":
                                        file_path_val = inp.get("path", "")
                                        grep_pattern = inp.get("pattern", "")[:200] or None

                                    elif tool_name == "WebSearch":
                                        search_query = inp.get("query", "")[:200] or None

                                    elif tool_name == "WebFetch":
                                        fetch_url = inp.get("url", "")[:300] or None

                                    elif tool_name == "Task":
                                        inp.get("subagent_type", "")

                                    elif tool_name == "Skill":
                                        inp.get("skill", "")

                                    # Track for tool_result matching
                                    if tool_id:
                                        pending_tool_uses[tool_id] = (session_id, tool_name, file_path_val)

                                    tool_calls.append(
                                        {
                                            "session_id": session_id,
                                            "timestamp": timestamp,
                                            "message_uuid": uuid,
                                            "tool_name": tool_name,
                                            "file_path": file_path_val,
                                            "edit_delta": edit_delta,
                                            "bytes_written": bytes_written,
                                            "command_category": command_category,
                                            "bash_command": bash_command,
                                            "install_packages": install_packages,
                                            "is_test_command": is_test_command,
                                            "bash_description": bash_description,
                                            "search_query": search_query,
                                            "fetch_url": fetch_url,
                                            "grep_pattern": grep_pattern,
                                            "edit_category": edit_category,
                                            "is_git_revert": is_git_revert,
                                        }
                                    )

                            s["total_text_length_assistant"] += msg_text_length
                            d["total_text_length_assistant"] += msg_text_length
                            if msg_has_thinking:
                                s["thinking_message_count"] += 1
                            if msg_has_code:
                                s["has_code_blocks"] += 1
                                d["messages_with_code_blocks"] += 1

            except OSError:
                continue

        # ── Post-process sessions: compute autonomy runs + timing ──
        # Phase 1.1 note: session_msg_roles appends "assistant" once per JSONL line.
        # In Claude Code JSONL, each assistant turn IS one line (tool_use blocks are
        # within a single message). So this correctly counts API turns, not sub-calls.
        session_stats_list = []
        for sid, s in sessions.items():
            # Compute autonomy run lengths
            roles = session_msg_roles.get(sid, [])
            runs = _compute_autonomy_runs(roles)
            avg_run = sum(runs) / len(runs) if runs else 0
            max_run = max(runs) if runs else 0

            # Phase 6.1: compute inter-message timing stats
            timestamps = session_timestamps.get(sid, [])
            avg_time_between = 0.0
            fast_approval_count = s.get("fast_approval_count", 0)
            if len(timestamps) >= 2:
                intervals = []
                for i in range(1, len(timestamps)):
                    try:
                        t0 = datetime.fromisoformat(timestamps[i - 1].replace("Z", "+00:00"))
                        t1 = datetime.fromisoformat(timestamps[i].replace("Z", "+00:00"))
                        diff_secs = (t1 - t0).total_seconds()
                        if 0 <= diff_secs < 3600:  # ignore gaps > 1h (idle)
                            intervals.append(diff_secs)
                            if diff_secs < 5:
                                fast_approval_count += 1
                    except (ValueError, OverflowError):
                        continue
                avg_time_between = sum(intervals) / len(intervals) if intervals else 0.0

            # Convert sets to counts/lists
            s["unique_tools"] = sorted(s["unique_tools"])
            s["unique_files_touched"] = len(session_files.get(sid, set()))
            s["cwd_switch_count"] = len(session_cwds.get(sid, set()))
            s["avg_autonomy_run_length"] = round(avg_run, 2)
            s["max_autonomy_run_length"] = max_run
            s["avg_time_between_messages"] = round(avg_time_between, 2)
            s["fast_approval_count"] = fast_approval_count

            session_stats_list.append(s)

        # ── Finalize daily stats ──
        daily_stats_list = []
        for date_str, d in sorted(daily.items()):
            d["unique_sessions"] = len(d["unique_sessions"])
            d["unique_files_touched"] = len(d["unique_files"]) if isinstance(d.get("unique_files"), set) else 0
            d.pop("unique_files", None)
            daily_stats_list.append(d)

        result = {
            "session_stats": session_stats_list,
            "tool_calls": tool_calls,
            "error_results": error_results,
            "daily_stats": daily_stats_list,
            "human_message_lengths": human_message_lengths,
        }

        if use_cache:
            self._save_cache(result)

        return result

    def mine_dataframes(self, use_cache: bool = True) -> dict[str, pd.DataFrame]:
        """Mine and return data as DataFrames for dashboard consumption."""
        raw = self.mine(use_cache=use_cache)

        dfs = {}

        if raw["session_stats"]:
            dfs["session_stats"] = pd.DataFrame(raw["session_stats"])
            if "date" in dfs["session_stats"].columns:
                dfs["session_stats"]["date"] = pd.to_datetime(dfs["session_stats"]["date"])
        else:
            dfs["session_stats"] = pd.DataFrame()

        if raw["tool_calls"]:
            dfs["tool_calls"] = pd.DataFrame(raw["tool_calls"])
            if "timestamp" in dfs["tool_calls"].columns:
                dfs["tool_calls"]["timestamp"] = pd.to_datetime(dfs["tool_calls"]["timestamp"])
        else:
            dfs["tool_calls"] = pd.DataFrame()

        if raw["error_results"]:
            dfs["error_results"] = pd.DataFrame(raw["error_results"])
            if "timestamp" in dfs["error_results"].columns:
                dfs["error_results"]["timestamp"] = pd.to_datetime(dfs["error_results"]["timestamp"])
        else:
            dfs["error_results"] = pd.DataFrame()

        if raw["daily_stats"]:
            dfs["daily_stats"] = pd.DataFrame(raw["daily_stats"])
            if "date" in dfs["daily_stats"].columns:
                dfs["daily_stats"]["date"] = pd.to_datetime(dfs["daily_stats"]["date"])
        else:
            dfs["daily_stats"] = pd.DataFrame()

        if raw["human_message_lengths"]:
            dfs["human_message_lengths"] = pd.DataFrame(raw["human_message_lengths"])
        else:
            dfs["human_message_lengths"] = pd.DataFrame()

        return dfs

    def clear_cache(self):
        if self.cache_path.exists():
            self.cache_path.unlink()


def _compute_autonomy_runs(roles: list[str]) -> list[int]:
    """Compute consecutive assistant turn lengths between human messages."""
    runs = []
    current_run = 0
    for role in roles:
        if role == "assistant":
            current_run += 1
        else:
            if current_run > 0:
                runs.append(current_run)
            current_run = 0
    if current_run > 0:
        runs.append(current_run)
    return runs


# Convenience function
def mine_content(use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """Mine conversation content from all JSONL files."""
    miner = ContentMiner()
    return miner.mine_dataframes(use_cache=use_cache)
