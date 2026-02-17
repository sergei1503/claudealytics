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
    agent: str = ""
    description: str = ""
    outcome_preview: str = ""


class SkillExecution(BaseModel):
    timestamp: str
    session_id: str = ""
    type: str = "skill"
    skill: str = ""
    args: str = ""
    outcome_preview: str = ""


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
