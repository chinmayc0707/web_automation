import asyncio
import json
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from ollama import Client

load_dotenv()

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN  = ''
YELLOW = ''
RED    = ''
CYAN   = ''
BOLD   = ''
DIM    = ''
RESET  = ''


# ── MCP Connection ──────────────────────────────────────────────────────────
@asynccontextmanager
async def connect_mcp(emit=None):
    """Yield (session, ollama_tools) with a persistent Playwright MCP session."""
    npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
    server_params = StdioServerParameters(
        command=npx_cmd,
        args=["-y", "@executeautomation/playwright-mcp-server"],
    )

    if emit:
        await emit("Starting Playwright MCP server ...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if emit:
                await emit("✓ MCP connected\n")

            # Fetch tools and convert to Ollama / OpenAI format
            mcp_tools = (await session.list_tools()).tools
            ollama_tools = []
            tool_names = []
            for t in mcp_tools:
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema,
                    },
                })
                tool_names.append(t.name)

            if emit:
                await emit(f"Available tools ({len(tool_names)}): {', '.join(tool_names)}\n")
            yield session, ollama_tools


# ── Planner ─────────────────────────────────────────────────────────────────
class Planner:
    """Breaks a user task into an ordered list of concrete browser-action steps."""

    SYSTEM_PROMPT = (
        "You are a Planner LLM for a browser automation system.\n"
        "Given a user task, output a JSON object with a single key \"steps\" "
        "whose value is an ordered array of step objects.\n"
        "Each step object MUST have exactly these keys:\n"
        '  - "step": integer step number starting from 1\n'
        '  - "action": a clear, specific instruction that an executor agent can perform '
        "using Playwright browser tools (navigate, click, type, screenshot, etc.)\n"
        '  - "expected_result": what should happen after this action succeeds\n\n'
        "Rules:\n"
        "- Be specific: include URLs, CSS selectors (if obvious), and text to type.\n"
        "- Each step should map to one or two tool calls at most.\n"
        "- Do NOT call tools yourself; just describe what to do.\n"
        "- Always start with a navigation step if a URL is given.\n"
        "- End with a step that summarises the final result.\n"
    )

    def __init__(self):
        self.client = Client(
            host=os.getenv("OLLAMA_HOST_PLANNER") or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        )
        self.model = os.getenv("OLLAMA_MODEL_PLANNER") or os.getenv("OLLAMA_MODEL", "gpt-oss:20b")

    def plan(self, prompt: str, tool_names: list[str]) -> list[dict]:
        system = self.SYSTEM_PROMPT + f"\nAvailable browser tools: {', '.join(tool_names)}\n"

        response = self.client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            format="json",
        )

        content = response["message"]["content"]
        parsed = json.loads(content)

        # Accept {"steps": [...]} or a bare list
        steps = parsed.get("steps", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(steps, list):
            steps = [steps]

        return steps


# ── Executor ────────────────────────────────────────────────────────────────
class Executor:
    """Executes a single step by calling the LLM in a tool-call loop via MCP."""

    SYSTEM_PROMPT = (
        "You are an Executor LLM for browser automation.\n"
        "You receive a specific step to perform. Use the provided tools to carry it out.\n"
        "Call the appropriate tool(s) to complete the step.\n"
        "After all tool calls are done, respond with a short text summary of what happened.\n"
        "If a tool call fails, report the error and do NOT retry endlessly.\n"
    )

    MAX_ITERATIONS = 15  # safety cap for tool-call loop

    def __init__(self):
        self.client = Client(
            host=os.getenv("OLLAMA_HOST_EXECUTOR") or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        )
        self.model = os.getenv("OLLAMA_MODEL_EXECUTOR") or os.getenv("OLLAMA_MODEL", "gpt-oss:20b")

    async def execute(
        self,
        step_text: str,
        ollama_tools: list[dict],
        mcp_session: ClientSession,
        context: str = "",
        emit=None
    ) -> str:
        """Run the tool-call loop for one step. Returns a text summary."""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
        ]
        if context:
            messages.append({"role": "system", "content": f"Context from previous steps:\n{context}"})
        messages.append({"role": "user", "content": step_text})

        for iteration in range(self.MAX_ITERATIONS):
            response = self.client.chat(
                model=self.model,
                messages=messages,
                tools=ollama_tools,
            )

            msg = response["message"]

            # If no tool calls → LLM is done, return its text answer
            if not msg.get("tool_calls"):
                return msg.get("content", "(no response)")

            # Process each tool call
            messages.append(msg)  # append assistant message with tool_calls

            for tool_call in msg["tool_calls"]:
                fn = tool_call["function"]
                tool_name = fn["name"]
                tool_args = fn.get("arguments", {})

                if emit:
                    await emit(f"  🔧 {tool_name}({json.dumps(tool_args, indent=2)})")

                try:
                    result = await mcp_session.call_tool(tool_name, tool_args)
                    # Extract text from MCP result
                    if hasattr(result, "content") and result.content:
                        result_text = "\n".join(
                            getattr(c, "text", str(c)) for c in result.content
                        )
                    else:
                        result_text = str(result)

                    # Truncate very long results to avoid context overflow
                    if len(result_text) > 4000:
                        result_text = result_text[:4000] + "\n... (truncated)"

                    if emit:
                        await emit(f"     ↳ {result_text[:200]}")

                except Exception as e:
                    result_text = f"ERROR: {e}"
                    if emit:
                        await emit(f"     ↳ {result_text}")

                messages.append({
                    "role": "tool",
                    "content": result_text,
                })

        return "(max iterations reached – step may be incomplete)"


# ── Orchestrator ────────────────────────────────────────────────────────────
async def run(prompt: str, emit=None):
    """Main loop: Plan → Execute each step → Print summary."""
    planner = Planner()
    executor = Executor()

    async with connect_mcp(emit=emit) as (session, ollama_tools):
        # Extract tool names for the planner
        tool_names = [t["function"]["name"] for t in ollama_tools]

        # ── Plan ────────────────────────────────────────────────────────
        if emit:
            await emit("📋 Planning ...")
        steps = planner.plan(prompt, tool_names)

        if emit:
            await emit(f"Plan ({len(steps)} steps):")
        for s in steps:
            step_num = s.get("step", "?")
            action = s.get("action", s.get("summary", str(s)))
            if emit:
                await emit(f"  {step_num}. {action}")
        if emit:
            await emit("")

        # ── Execute ─────────────────────────────────────────────────────
        context_lines = []  # cumulative context from prior steps
        results = []

        for s in steps:
            step_num = s.get("step", "?")
            action = s.get("action", s.get("summary", str(s)))
            expected = s.get("expected_result", "")

            if emit:
                await emit(f"▶ Step {step_num}: {action}")
            if expected:
                if emit:
                    await emit(f"  Expected: {expected}")

            step_prompt = f"Step {step_num}: {action}"
            if expected:
                step_prompt += f"\nExpected result: {expected}"

            context = "\n".join(context_lines[-5:])  # last 5 step summaries
            summary = await executor.execute(step_prompt, ollama_tools, session, context, emit=emit)

            if emit:
                await emit(f"  ✓ {summary}\n")

            context_lines.append(f"Step {step_num}: {action} → {summary}")
            results.append({"step": step_num, "action": action, "result": summary})

        # ── Final Summary ───────────────────────────────────────────────
        if emit:
            await emit(f"\n{'=' * 60}")
            await emit(f"  Task Complete!")
            await emit(f"{'=' * 60}")
            for r in results:
                await emit(f"  Step {r['step']}: {r['result']}")
            await emit("")


# ── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def print_emit(msg):
        print(msg)

    print(f"{'=' * 60}")
    print(f"  🤖 AI Web Agent (Planner + Executor)")
    print(f"{'=' * 60}\n")

    user_prompt = input(f"Enter your task: ").strip()
    if not user_prompt:
        print(f"No prompt provided. Exiting.")
    else:
        asyncio.run(run(user_prompt, emit=print_emit))
