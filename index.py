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
GREEN  = '\033[92m'
YELLOW = '\033[93m'
RED    = '\033[91m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
RESET  = '\033[0m'


# ── MCP Connection ──────────────────────────────────────────────────────────
@asynccontextmanager
async def connect_mcp():
    """Yield (session, ollama_tools) with a persistent Playwright MCP session."""
    npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
    server_params = StdioServerParameters(
        command=npx_cmd,
        args=["-y", "@executeautomation/playwright-mcp-server"],
    )

    print(f"{DIM}Starting Playwright MCP server …{RESET}")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"{GREEN}✓ MCP connected{RESET}\n")

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

            print(f"{DIM}Available tools ({len(tool_names)}): {', '.join(tool_names)}{RESET}\n")
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

                print(f"  {CYAN}🔧 {tool_name}{RESET}({json.dumps(tool_args, indent=2)})")

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

                    print(f"  {DIM}   ↳ {result_text[:200]}{RESET}")

                except Exception as e:
                    result_text = f"ERROR: {e}"
                    print(f"  {RED}   ↳ {result_text}{RESET}")

                messages.append({
                    "role": "tool",
                    "content": result_text,
                })

        return "(max iterations reached – step may be incomplete)"


# ── Orchestrator ────────────────────────────────────────────────────────────
async def run(prompt: str):
    """Main loop: Plan → Execute each step → Print summary."""
    planner = Planner()
    executor = Executor()

    async with connect_mcp() as (session, ollama_tools):
        # Extract tool names for the planner
        tool_names = [t["function"]["name"] for t in ollama_tools]

        # ── Plan ────────────────────────────────────────────────────────
        print(f"{BOLD}{YELLOW}📋 Planning …{RESET}")
        steps = planner.plan(prompt, tool_names)

        print(f"{BOLD}{GREEN}Plan ({len(steps)} steps):{RESET}")
        for s in steps:
            step_num = s.get("step", "?")
            action = s.get("action", s.get("summary", str(s)))
            print(f"  {YELLOW}{step_num}.{RESET} {action}")
        print()

        # ── Execute ─────────────────────────────────────────────────────
        context_lines = []  # cumulative context from prior steps
        results = []

        for s in steps:
            step_num = s.get("step", "?")
            action = s.get("action", s.get("summary", str(s)))
            expected = s.get("expected_result", "")

            print(f"{BOLD}{CYAN}▶ Step {step_num}: {action}{RESET}")
            if expected:
                print(f"  {DIM}Expected: {expected}{RESET}")

            step_prompt = f"Step {step_num}: {action}"
            if expected:
                step_prompt += f"\nExpected result: {expected}"

            context = "\n".join(context_lines[-5:])  # last 5 step summaries
            summary = await executor.execute(step_prompt, ollama_tools, session, context)

            print(f"  {GREEN}✓ {summary}{RESET}\n")

            context_lines.append(f"Step {step_num}: {action} → {summary}")
            results.append({"step": step_num, "action": action, "result": summary})

        # ── Final Summary ───────────────────────────────────────────────
        print(f"\n{BOLD}{GREEN}{'═' * 60}")
        print(f"  Task Complete!")
        print(f"{'═' * 60}{RESET}")
        for r in results:
            print(f"  {YELLOW}Step {r['step']}:{RESET} {r['result']}")
        print()


# ── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"{BOLD}{GREEN}{'═' * 60}")
    print(f"  🤖 AI Web Agent (Planner + Executor)")
    print(f"{'═' * 60}{RESET}\n")

    user_prompt = input(f"{BOLD}Enter your task:{RESET} ").strip()
    if not user_prompt:
        print(f"{RED}No prompt provided. Exiting.{RESET}")
    else:
        asyncio.run(run(user_prompt))
