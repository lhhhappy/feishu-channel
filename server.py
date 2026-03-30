#!/usr/bin/env python3
"""
Feishu Channel for Claude Code

A bidirectional Feishu/Lark messaging channel for Claude Code, implemented as
an MCP server with real-time push notifications — just like the built-in
Telegram channel.

Architecture:
  lark-cli event +subscribe (WebSocket) → MCP notifications/claude/channel → Claude Code
  Claude Code → reply/react/edit_message tools → lark-cli im → Feishu

Requirements:
  - Python 3.10+
  - mcp (pip install mcp)
  - lark-cli (npm install -g @anthropic-ai/lark-cli, or see README)

Usage:
  1. Configure lark-cli:  lark-cli config init
  2. Register MCP server: claude mcp add feishu -s project -- python3 server.py
  3. Start Claude Code:   claude --dangerously-load-development-channels server:feishu
"""

import asyncio
import json
import subprocess
import sys
import threading
from datetime import datetime, timezone

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import (
    JSONRPCMessage,
    JSONRPCNotification,
    Tool,
    TextContent,
)

__version__ = "0.1.0"


# ── Logging ─────────────────────────────────────────────────

def _log(msg: str):
    """Log to stderr (captured by Claude Code) and optionally to file."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[feishu {ts}] {msg}", file=sys.stderr)


# ── lark-cli wrappers ──────────────────────────────────────

def _run(cmd: list[str]) -> tuple[bool, str]:
    """Run a lark-cli command, return (success, output)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout or result.stderr
    ok = result.returncode == 0 and ('"ok": true' in output or '"ok":true' in output)
    return ok, output


def _send_text(chat_id: str, text: str) -> tuple[bool, str]:
    return _run([
        "lark-cli", "im", "+messages-send",
        "--chat-id", chat_id, "--text", text, "--as", "bot",
    ])


def _reply_text(message_id: str, text: str) -> tuple[bool, str]:
    return _run([
        "lark-cli", "im", "+messages-reply",
        "--message-id", message_id, "--text", text, "--as", "bot",
    ])


def _send_image(chat_id: str, image_path: str) -> tuple[bool, str]:
    return _run([
        "lark-cli", "im", "+messages-send",
        "--chat-id", chat_id, "--image", image_path, "--as", "bot",
    ])


def _send_file(chat_id: str, file_path: str) -> tuple[bool, str]:
    return _run([
        "lark-cli", "im", "+messages-send",
        "--chat-id", chat_id, "--file", file_path, "--as", "bot",
    ])


def _react(message_id: str, emoji: str) -> tuple[bool, str]:
    data = json.dumps({"reaction_type": {"emoji_type": emoji}})
    return _run([
        "lark-cli", "api", "POST",
        f"/open-apis/im/v1/messages/{message_id}/reactions",
        "--data", data, "--as", "bot",
    ])


def _edit(message_id: str, text: str) -> tuple[bool, str]:
    data = json.dumps({"msg_type": "text", "content": json.dumps({"text": text})})
    return _run([
        "lark-cli", "api", "PATCH",
        f"/open-apis/im/v1/messages/{message_id}",
        "--data", data, "--as", "bot",
    ])


# ── MCP Server ──────────────────────────────────────────────

server = Server(
    name="feishu",
    version=__version__,
    instructions="\n".join([
        "The sender reads Feishu, not this session. Anything you want them to see "
        "must go through the reply tool -- your transcript output never reaches their chat.",
        "",
        'Messages from Feishu arrive as <channel source="feishu" chat_id="..." message_id="..." user="..." ts="...">. '
        "Reply with the reply tool -- pass chat_id back. Use reply_to (set to a message_id) "
        "only when replying to an earlier message; the latest message doesn't need a quote-reply, "
        "omit reply_to for normal responses.",
        "",
        "reply accepts file paths (files: ['/abs/path.png']) for attachments. "
        "Use react to add emoji reactions, and edit_message for interim progress updates. "
        "Edits don't trigger push notifications -- when a long task completes, send a new reply "
        "so the user's device pings.",
        "",
        "Feishu's Bot API exposes no history or search -- you only see messages as they arrive. "
        "If you need earlier context, ask the user to paste it or summarize.",
    ]),
)

# ── Tool definitions ────────────────────────────────────────

TOOLS = [
    Tool(
        name="reply",
        description=(
            "Reply on Feishu. Pass chat_id from the inbound message. "
            "Optionally pass reply_to (message_id) for threading, "
            "and files (absolute paths) to attach images or documents."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "text": {"type": "string"},
                "reply_to": {
                    "type": "string",
                    "description": "Message ID to thread under. Use message_id from the inbound <channel> block.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute file paths to attach (images sent as photos, others as documents).",
                },
            },
            "required": ["chat_id", "text"],
        },
    ),
    Tool(
        name="react",
        description="Add an emoji reaction to a Feishu message. Common types: THUMBSUP, HEART, SMILE, FIRE, CLAP, OK.",
        inputSchema={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "message_id": {"type": "string"},
                "emoji": {"type": "string"},
            },
            "required": ["chat_id", "message_id", "emoji"],
        },
    ),
    Tool(
        name="edit_message",
        description=(
            "Edit a message the bot previously sent. Useful for interim progress updates. "
            "Edits don't trigger push notifications -- send a new reply when a long task completes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["message_id", "text"],
        },
    ),
]


@server.list_tools()
async def list_tools():
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "reply":
        return await _handle_reply(arguments)
    elif name == "react":
        return await _handle_react(arguments)
    elif name == "edit_message":
        return await _handle_edit(arguments)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Tool handlers ───────────────────────────────────────────

async def _handle_reply(args: dict):
    chat_id = args["chat_id"]
    text = args["text"]
    reply_to = args.get("reply_to", "")
    files = args.get("files") or []

    # Send text
    if reply_to:
        ok, output = _reply_text(reply_to, text)
    else:
        ok, output = _send_text(chat_id, text)

    # Send file attachments
    import mimetypes
    for fpath in files:
        mime, _ = mimetypes.guess_type(fpath)
        if mime and mime.startswith("image/"):
            _send_image(chat_id, fpath)
        else:
            _send_file(chat_id, fpath)

    return [TextContent(type="text", text="sent" if ok else output)]


async def _handle_react(args: dict):
    ok, output = _react(args["message_id"], args["emoji"])
    return [TextContent(type="text", text="reacted" if ok else output)]


async def _handle_edit(args: dict):
    ok, output = _edit(args["message_id"], args["text"])
    return [TextContent(type="text", text="edited" if ok else output)]


# ── Feishu event listener → channel push ────────────────────

_write_stream = None


def _start_event_listener(loop: asyncio.AbstractEventLoop):
    """Background thread: lark-cli WebSocket → MCP channel notifications."""
    try:
        proc = subprocess.Popen(
            [
                "lark-cli", "event", "+subscribe",
                "--event-types", "im.message.receive_v1",
                "--as", "bot", "--compact", "--quiet", "--force",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        _log("WebSocket event listener connected")
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            content = msg.get("content", "")
            chat_id = msg.get("chat_id", "")
            message_id = msg.get("message_id", "")
            sender_id = msg.get("sender_id", "")
            chat_type = msg.get("chat_type", "")
            ts = msg.get("create_time", "")

            try:
                ts_iso = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).isoformat()
            except (ValueError, TypeError):
                ts_iso = ts

            meta = {
                "chat_id": chat_id,
                "message_id": message_id,
                "user": sender_id,
                "chat_type": chat_type,
                "ts": ts_iso,
            }

            asyncio.run_coroutine_threadsafe(_push(content, meta), loop)
            _log(f"[{sender_id}] {content[:80]}")

    except Exception as e:
        _log(f"listener error: {e}")


async def _push(content: str, meta: dict):
    """Push a channel notification to Claude Code via MCP protocol."""
    global _write_stream
    if _write_stream is None:
        return
    try:
        notif = JSONRPCNotification(
            jsonrpc="2.0",
            method="notifications/claude/channel",
            params={"content": content, "meta": meta},
        )
        await _write_stream.send(SessionMessage(message=JSONRPCMessage(notif)))
    except Exception as e:
        _log(f"push error: {e}")


# ── Entrypoint ──────────────────────────────────────────────

async def main():
    global _write_stream

    async with stdio_server() as (read_stream, write_stream):
        _write_stream = write_stream
        loop = asyncio.get_running_loop()

        init_options = server.create_initialization_options(
            experimental_capabilities={"claude/channel": {}},
        )

        listener = threading.Thread(
            target=_start_event_listener, args=(loop,), daemon=True,
        )
        listener.start()
        _log(f"feishu channel v{__version__} started")

        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
