"""Pydantic models for Claude Code data structures."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


# ── Stats Cache Models ──────────────────────────────────────────────

class DailyActivity(BaseModel):
    date: str
    messageCount: int = 0
    sessionCount: int = 0
    toolCallCount: int = 0


class DailyModelTokens(BaseModel):
    date: str
    tokensByModel: dict[str, int] = Field(default_factory=dict)


class ModelUsageEntry(BaseModel):
    inputTokens: int = 0
    outputTokens: int = 0
    cacheReadInputTokens: int = 0
    cacheCreationInputTokens: int = 0
    webSearchRequests: int = 0
    costUSD: float = 0.0
    contextWindow: int = 0
    maxOutputTokens: int = 0


class LongestSession(BaseModel):
    sessionId: str = ""
    duration: int = 0
    messageCount: int = 0
    timestamp: str = ""


class StatsCache(BaseModel):
    version: int = 2
    lastComputedDate: str = ""
    dailyActivity: list[DailyActivity] = Field(default_factory=list)
    dailyModelTokens: list[DailyModelTokens] = Field(default_factory=list)
    modelUsage: dict[str, ModelUsageEntry] = Field(default_factory=dict)
    totalSessions: int = 0
    totalMessages: int = 0
    longestSession: LongestSession = Field(default_factory=LongestSession)
    firstSessionDate: str = ""
    hourCounts: dict[str, int] = Field(default_factory=dict)
    totalSpeculationTimeSavedMs: int = 0


# ── Execution Log Models ────────────────────────────────────────────

class AgentExecution(BaseModel):
    timestamp: str
    session_id: str = ""
    type: str = "agent"
    agent_type: str = ""  # Standardized field name
    agent: str = ""  # Keep for backward compatibility
    prompt: str = ""  # Added for conversation data
    description: str = ""
    outcome_preview: str = ""
    status: str = "unknown"  # Added for tracking completion status
    total_tokens: int = 0  # Added for token tracking
    model: str = "unknown"  # Added for model tracking

    def __init__(self, **data):
        # Handle both field names for backward compatibility
        if "agent" in data and "agent_type" not in data:
            data["agent_type"] = data["agent"]
        elif "agent_type" in data and "agent" not in data:
            data["agent"] = data["agent_type"]
        super().__init__(**data)


class SkillExecution(BaseModel):
    timestamp: str
    session_id: str = ""
    type: str = "skill"
    skill_name: str = ""  # Standardized field name
    skill: str = ""  # Keep for backward compatibility
    args: str = ""
    outcome_preview: str = ""
    status: str = "unknown"  # Added for tracking completion status

    def __init__(self, **data):
        # Handle both field names for backward compatibility
        if "skill" in data and "skill_name" not in data:
            data["skill_name"] = data["skill"]
        elif "skill_name" in data and "skill" not in data:
            data["skill"] = data["skill_name"]
        super().__init__(**data)


# ── Tool Usage Stats Models ─────────────────────────────────────────

class ToolUsageStats(BaseModel):
    """Aggregated statistics for tool usage - lightweight data structure."""
    agents: dict[str, int] = Field(default_factory=dict)  # agent_name -> count
    skills: dict[str, int] = Field(default_factory=dict)  # skill_name -> count
    daily_agents: dict[str, dict[str, int]] = Field(default_factory=dict)  # date -> agent -> count
    daily_skills: dict[str, dict[str, int]] = Field(default_factory=dict)  # date -> skill -> count
    total_conversations: int = 0
    date_range: tuple[str, str] = ("", "")  # (earliest, latest)


# ── Session Models ──────────────────────────────────────────────────

class SessionInfo(BaseModel):
    session_id: str
    project: str = ""
    date: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: float = 0.0
    message_count: int = 0


# ── Scanner Models ──────────────────────────────────────────────────

class ScanIssue(BaseModel):
    severity: str  # "high", "medium", "low"
    category: str  # "orphan", "missing", "inconsistency", "unused"
    message: str
    file: str = ""
    suggestion: str = ""


class AgentInfo(BaseModel):
    name: str
    file_path: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    model: str = ""
    execution_count: int = 0
    last_used: str = ""


class SkillInfo(BaseModel):
    name: str
    file_path: str
    description: str = ""
    user_invocable: bool = False
    execution_count: int = 0
    last_used: str = ""


class ScanReport(BaseModel):
    timestamp: str
    agents: list[AgentInfo] = Field(default_factory=list)
    skills: list[SkillInfo] = Field(default_factory=list)
    issues: list[ScanIssue] = Field(default_factory=list)
    total_agents: int = 0
    total_skills: int = 0
    total_claude_md_files: int = 0


# ── Config Health Models ───────────────────────────────────────────

class ConfigFileMetrics(BaseModel):
    path: str
    file_type: str  # "global_claude_md", "project_claude_md", "agent", "skill"
    name: str
    lines: int
    bytes: int


class ConfigSizeSnapshot(BaseModel):
    timestamp: str  # ISO format
    files: list[ConfigFileMetrics] = Field(default_factory=list)
    total_lines: int = 0
    total_bytes: int = 0


class ConfigSizeHistory(BaseModel):
    snapshots: list[ConfigSizeSnapshot] = Field(default_factory=list)


class ConfigQualityIssue(BaseModel):
    file_path: str
    issue_type: str  # "missing_section", "broken_reference", "stale_entry", "missing_frontmatter"
    severity: str  # "high", "medium", "low"
    message: str
    suggestion: str = ""


class ConfigComplexityMetrics(BaseModel):
    file_path: str
    name: str
    file_type: str
    lines: int
    avg_line_length: float
    max_line_length: int
    section_count: int
    table_count: int
    code_block_count: int
    word_count: int


class ConfigLLMReview(BaseModel):
    file_path: str
    clarity_score: float = 0.0
    redundancy_issues: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    summary: str = ""


class ConfigAnalysisResult(BaseModel):
    timestamp: str
    quality_issues: list[ConfigQualityIssue] = Field(default_factory=list)
    complexity_metrics: list[ConfigComplexityMetrics] = Field(default_factory=list)
    llm_reviews: dict[str, ConfigLLMReview] = Field(default_factory=dict)
    consistency_issues: list[ConfigQualityIssue] = Field(default_factory=list)
    cross_file_observations: list[str] = Field(default_factory=list)
    analysis_duration_seconds: float = 0.0


class UnmappedPreferences(BaseModel):
    dismissed_agents: list[str] = Field(default_factory=list)
    dismissed_skills: list[str] = Field(default_factory=list)


# ── Tool Version Models ───────────────────────────────────────────

class ToolVersionResult(BaseModel):
    name: str
    installed_version: str | None = None
    latest_version: str | None = None
    status: str = "unknown"  # "up_to_date", "update_available", "not_installed", "unknown"


# ── Content Mining Models ────────────────────────────────────────

class ContentMineResult(BaseModel):
    """Cached output from ContentMiner single-pass extraction."""
    session_stats: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    error_results: list[dict] = Field(default_factory=list)
    daily_stats: list[dict] = Field(default_factory=list)
    human_message_lengths: list[dict] = Field(default_factory=list)


# ── Full Report Models ──────────────────────────────────────────

class HealthSubScore(BaseModel):
    """A single dimension of the composite health score."""
    name: str
    label: str
    score: int | None = None
    weight: float = 0.0
    explanation: str = ""


class HealthScoreResult(BaseModel):
    """Composite platform health score with sub-scores."""
    overall_score: int = 0
    sub_scores: list[HealthSubScore] = Field(default_factory=list)
    active_count: int = 0
    total_count: int = 0


class FullReport(BaseModel):
    """Result of LLM-generated full platform report."""
    timestamp: str
    report_markdown: str = ""
    data_summary: str = ""
    data_json: dict = Field(default_factory=dict)
    model_used: str = ""
    generation_duration_seconds: float = 0.0
    error: str = ""
