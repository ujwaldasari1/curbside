"""Shared runtime for Curbside agents (Claude Agent SDK).

Every agent runs with:
  - no built-in Claude Code tools (tools=[]): no shell, no filesystem, MCP only
  - no user/project settings (setting_sources=[]): nothing from ~/.claude leaks in
  - only the MCP servers passed here (strict_mcp_config)
  - an explicit tool allow-list, OpenMetadata write tools disallowed, and a PreToolUse
    hook that denies them again (defence in depth). Agents change metadata only by
    proposing through curbside-mcp; a human approves.
  - a budget and turn cap, a JSONL trace of every tool call, and a row in ops.agent_runs
"""

import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    ToolUseBlock,
    query,
)

from shared.env import ROOT, load_dotenv

load_dotenv()

DEFAULT_MODEL = os.environ.get("CURBSIDE_MODEL", "claude-opus-5")
FALLBACK_MODEL = os.environ.get("CURBSIDE_FALLBACK_MODEL", "claude-opus-4-8")
TRACE_DIR = ROOT / ".traces"
PROMPTS = Path(__file__).parent / "prompts"

# OpenMetadata MCP (2.0.2) read tools the agents may use. Write tools are never allowed.
OM_READ_TOOLS = [
    "search_metadata",
    "get_entity_details",
    "get_entity_lineage",
    "root_cause_analysis",
    "get_test_definitions",
    "describe_entity_type",
]
OM_WRITE_TOOLS = ["create_entity", "patch_entity", "create_lineage", "create_test_case"]


def om_tool(name: str) -> str:
    return f"mcp__openmetadata__{name}"


def curbside_tool(name: str) -> str:
    return f"mcp__curbside__{name}"


def mcp_servers(agent: str, sql_schemas: str) -> dict[str, Any]:
    return {
        "openmetadata": {
            "type": "http",
            "url": os.environ.get("OPENMETADATA_MCP_URL", "http://localhost:8585/mcp"),
            "headers": {"Authorization": f"Bearer {os.environ['OPENMETADATA_JWT_TOKEN']}"},
        },
        "curbside": {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "mcp_servers.curbside_mcp"],
            "env": {
                "PYTHONPATH": str(ROOT),
                "PATH": os.environ.get("PATH", ""),
                "CURBSIDE_AGENT_NAME": agent,
                "CURBSIDE_SQL_SCHEMAS": sql_schemas,
                "DAGSTER_URL": os.environ.get("DAGSTER_URL", "http://127.0.0.1:3000"),
            },
        },
    }


async def deny_catalog_writes(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
    """PreToolUse: OpenMetadata write tools are never callable by agents."""
    tool = input_data.get("tool_name", "")
    if tool in {om_tool(t) for t in OM_WRITE_TOOLS}:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Agents may not change OpenMetadata directly. Use "
                    "mcp__curbside__propose_metadata_change so a human can approve it."
                ),
            }
        }
    return {}


@dataclass
class AgentSpec:
    name: str
    prompt_file: str
    curbside_tools: list[str]
    om_tools: list[str] = field(default_factory=lambda: list(OM_READ_TOOLS))
    sql_schemas: str = "marts"
    effort: str = "high"
    max_turns: int = 40
    max_budget_usd: float = 2.0
    output_schema: dict | None = None


@dataclass
class AgentResult:
    agent: str
    output: Any
    text: str | None
    is_error: bool
    num_turns: int
    duration_ms: int
    cost_usd: float | None
    session_id: str
    tool_calls: list[dict]
    trace_path: str


def _response_json(response: Any) -> dict:
    """An MCP tool result as PostToolUse sees it: [{"type": "text", "text": "<json>"}]."""
    blocks = response if isinstance(response, list) else [response]
    for block in blocks:
        text = block.get("text") if isinstance(block, dict) else block
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _executed_query(tool: str | None, tool_input: dict | None, response: Any) -> dict:
    """{"sql", "query_id"} for a successful warehouse tool call, else {}."""
    result = _response_json(response)
    if tool == curbside_tool("query_metric"):
        sql = result.get("sql")
    elif tool == curbside_tool("run_readonly_sql") and "rows" in result:
        sql = (tool_input or {}).get("sql")
    else:
        return {}
    return {"sql": sql, "query_id": result.get("query_id")} if sql else {}


def executed_sql(tool_calls: list[dict]) -> list[str]:
    """Distinct SQL the agent's tool calls ran, in order."""
    return list(dict.fromkeys(t["sql"] for t in tool_calls if t.get("sql")))


def _options(spec: AgentSpec, trace: list[dict]) -> ClaudeAgentOptions:
    async def record_tool_call(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        tool, tool_input = input_data.get("tool_name"), input_data.get("tool_input")
        response = input_data.get("tool_response")
        entry = {
            "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "tool": tool,
            "input": tool_input,
            "response_chars": len(json.dumps(response, default=str)) if response is not None else 0,
        }
        entry.update(_executed_query(tool, tool_input, response))
        trace.append(entry)
        return {}

    allowed = [curbside_tool(t) for t in spec.curbside_tools] + [om_tool(t) for t in spec.om_tools]
    return ClaudeAgentOptions(
        model=os.environ.get(f"CURBSIDE_{spec.name.upper()}_MODEL", DEFAULT_MODEL),
        fallback_model=FALLBACK_MODEL,
        system_prompt=(PROMPTS / spec.prompt_file).read_text(),
        tools=[],
        allowed_tools=allowed,
        disallowed_tools=[om_tool(t) for t in OM_WRITE_TOOLS],
        permission_mode="dontAsk",
        mcp_servers=mcp_servers(spec.name, spec.sql_schemas),
        strict_mcp_config=True,
        setting_sources=[],
        cwd=str(ROOT),
        max_turns=spec.max_turns,
        max_budget_usd=spec.max_budget_usd,
        thinking={"type": "adaptive"},
        effort=os.environ.get(f"CURBSIDE_{spec.name.upper()}_EFFORT", spec.effort),
        output_format={"type": "json_schema", "schema": spec.output_schema} if spec.output_schema else None,
        hooks={
            "PreToolUse": [HookMatcher(matcher="mcp__openmetadata__.*", hooks=[deny_catalog_writes])],
            "PostToolUse": [HookMatcher(hooks=[record_tool_call])],
        },
    )


def _record_run(result: AgentResult, trigger: str, model: str) -> None:
    from mcp_servers.curbside_mcp.warehouse import app_dsn

    summary = result.text if isinstance(result.text, str) else json.dumps(result.output, default=str)
    try:
        with psycopg.connect(app_dsn(), connect_timeout=5) as conn:
            conn.execute(
                """
                INSERT INTO ops.agent_runs (agent, trigger, session_id, model, num_turns,
                    duration_ms, total_cost_usd, is_error, result_summary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (result.agent, trigger, result.session_id, model, result.num_turns,
                 result.duration_ms, result.cost_usd, result.is_error, (summary or "")[:4000]),
            )
    except psycopg.Error as err:  # observability must never break the agent
        print(f"warning: could not record agent run: {err}", file=sys.stderr)


async def run_agent(spec: AgentSpec, prompt: str, trigger: str = "manual") -> AgentResult:
    trace: list[dict] = []
    options = _options(spec, trace)
    result_message: ResultMessage | None = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"  [{spec.name}] -> {block.name}", file=sys.stderr)
        elif isinstance(message, ResultMessage):
            result_message = message
    if result_message is None:
        raise RuntimeError(f"{spec.name}: agent finished without a result message")

    TRACE_DIR.mkdir(exist_ok=True)
    trace_path = TRACE_DIR / f"{spec.name}-{result_message.session_id}.jsonl"
    trace_path.write_text("\n".join(json.dumps(t, default=str) for t in trace) + "\n")

    result = AgentResult(
        agent=spec.name,
        output=result_message.structured_output,
        text=result_message.result,
        is_error=result_message.is_error,
        num_turns=result_message.num_turns,
        duration_ms=result_message.duration_ms,
        cost_usd=result_message.total_cost_usd,
        session_id=result_message.session_id,
        tool_calls=trace,
        trace_path=str(trace_path),
    )
    _record_run(result, trigger, options.model or DEFAULT_MODEL)
    return result
