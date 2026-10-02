"""MCP server exposing RL PCB tools to Claude Desktop / Claude Code / any MCP client (stdio).

Works with both MCP Python SDK generations (1.x decorator API and 2.x constructor-callback API).

Claude Desktop (Windows) config, %APPDATA%\\Claude\\claude_desktop_config.json:
{
  "mcpServers": {
    "rlpcb": {"command": "C:\\\\path\\\\to\\\\rlpcb\\\\.venv\\\\Scripts\\\\python.exe", "args": ["-m", "rlpcb.agent.mcp_server"]}
  }
}
"""
from __future__ import annotations

import asyncio
import base64
import os

from .prompt import SYSTEM_PROMPT
from .tools import TOOLS, Session, run_tool, to_json

SESSION = None


def _session():
    global SESSION
    if SESSION is None:
        SESSION = Session()
    return SESSION


def _tool_list():
    import mcp.types as types
    return [types.Tool.model_validate({"name": t.name, "description": t.description, "inputSchema": t.schema}) for t in TOOLS]


def _content_for(name: str, arguments: dict):
    import mcp.types as types
    res = run_tool(_session(), name, arguments or {})
    images = res.pop("image_paths", None) if isinstance(res, dict) else None
    content = [types.TextContent.model_validate({"type": "text", "text": to_json(res)})]
    for path in images or []:
        if path.lower().endswith(".png") and os.path.exists(path):
            with open(path, "rb") as f:
                content.append(types.ImageContent.model_validate(
                    {"type": "image", "data": base64.b64encode(f.read()).decode(), "mimeType": "image/png"}))
        else:
            content.append(types.TextContent.model_validate({"type": "text", "text": f"(image at {path})"}))
    return content, ("error" in res if isinstance(res, dict) else False)


_PROMPT = {"name": "design_session", "description": "Start a guided PCB design session with RL PCB",
           "arguments": [{"name": "goal", "description": "What you want to build", "required": False}]}


def _prompt_text(arguments):
    goal = (arguments or {}).get("goal", "")
    return ("Let's design a PCB together in KiCad. First run kicad_environment and open or create the project. "
            + (f"Goal: {goal}" if goal else "Ask me what I want to build."))


def build_server():
    from mcp.server.lowlevel import Server
    import mcp.types as types

    if hasattr(Server, "list_tools"):  # ---------------- MCP SDK 1.x
        server = Server("rlpcb", instructions=SYSTEM_PROMPT)

        @server.list_tools()
        async def list_tools():
            return _tool_list()

        @server.call_tool()
        async def call_tool(name: str, arguments: dict):
            content, _ = await asyncio.to_thread(_content_for, name, arguments)
            return content

        @server.list_prompts()
        async def list_prompts():
            return [types.Prompt.model_validate(_PROMPT)]

        @server.get_prompt()
        async def get_prompt(name: str, arguments):
            return types.GetPromptResult.model_validate(
                {"messages": [{"role": "user", "content": {"type": "text", "text": _prompt_text(arguments)}}]})
        return server

    # -------------------------------------------------------- MCP SDK 2.x
    async def on_list_tools(ctx, params):
        return types.ListToolsResult.model_validate({"tools": [t.model_dump(by_alias=True, exclude_none=True) for t in _tool_list()]})

    async def on_call_tool(ctx, params):
        content, is_err = await asyncio.to_thread(_content_for, params.name, params.arguments or {})
        return types.CallToolResult.model_validate(
            {"content": [c.model_dump(by_alias=True, exclude_none=True) for c in content], "isError": is_err})

    async def on_list_prompts(ctx, params):
        return types.ListPromptsResult.model_validate({"prompts": [_PROMPT]})

    async def on_get_prompt(ctx, params):
        return types.GetPromptResult.model_validate(
            {"messages": [{"role": "user", "content": {"type": "text", "text": _prompt_text(params.arguments)}}]})

    return Server("rlpcb", instructions=SYSTEM_PROMPT, on_list_tools=on_list_tools, on_call_tool=on_call_tool,
                  on_list_prompts=on_list_prompts, on_get_prompt=on_get_prompt)


async def _main():
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
