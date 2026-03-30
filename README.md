# Feishu Channel for Claude Code

[中文文档](README_CN.md)

Bidirectional Feishu/Lark messaging channel for [Claude Code](https://docs.anthropic.com/en/docs/claude-code), implemented as an MCP server with real-time push notifications.

This is the **first open-source Feishu channel** for Claude Code. It works exactly like the built-in Telegram channel: messages from Feishu are pushed into your Claude Code session in real time, and you reply through MCP tools.

## How It Works

```
Feishu App ──WebSocket──▶ lark-cli event +subscribe
                              │
                              ▼
                     MCP Server (server.py)
                              │
              notifications/claude/channel
                              │
                              ▼
                        Claude Code
                              │
                     reply / react / edit
                              │
                              ▼
                     lark-cli im +messages-send
                              │
                              ▼
                         Feishu App
```

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) v2.1.87+
- Python 3.10+
- [lark-cli](https://github.com/riba2534/feishu-cli) (Feishu/Lark CLI tool)
- A Feishu custom app with bot capability

## Installation

### 1. Install lark-cli

```bash
npm install -g @anthropic-ai/lark-cli
# or from source:
# git clone https://github.com/riba2534/feishu-cli.git && cd feishu-cli && npm install -g .
```

### 2. Install Python dependencies

```bash
pip install mcp
```

### 3. Configure lark-cli

```bash
lark-cli config init
```

This will prompt you to create or connect a Feishu app. Follow the link to complete authorization.

### 4. Configure your Feishu app

In the [Feishu Open Platform console](https://open.feishu.cn):

1. **Add app capability** -> Enable **Bot**
2. **Events & Callbacks** -> Subscription method -> Select **"Use long connection to receive events"**
3. **Add event** -> `im.message.receive_v1` (Receive messages)
4. **Permissions** -> Enable:
   - `im:message:receive_as_bot` (receive messages)
   - `im:message` (send messages)
   - `im:chat:readonly` (read chat info)
5. **Publish** the app (Version Management -> Create version -> Publish)

### 5. Register the MCP server

```bash
cd /path/to/feishu_channel
claude mcp add feishu -s project -- python3 $(pwd)/server.py
```

This creates a `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "feishu": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/feishu_channel/server.py"]
    }
  }
}
```

### 6. Start Claude Code with the Feishu channel

```bash
claude --dangerously-load-development-channels server:feishu
```

### 7. Send a message in Feishu

Open your Feishu app, find the bot, and send a message. It will appear in your Claude Code session as:

```
feishu · ou_xxxxx: Hello!
```

Claude will process the message and reply through the bot.

## MCP Tools

| Tool | Description |
|------|-------------|
| `reply` | Send a text reply to a Feishu chat. Supports threading (`reply_to`) and file attachments (`files`). |
| `react` | Add an emoji reaction to a message (THUMBSUP, HEART, SMILE, FIRE, etc.) |
| `edit_message` | Edit a previously sent bot message. No push notification on edit. |

## Message Format

Inbound messages arrive as channel notifications:

```xml
<channel source="feishu" chat_id="oc_xxx" message_id="om_xxx" user="ou_xxx" ts="2025-01-01T00:00:00+00:00">
  Hello from Feishu!
</channel>
```

## Architecture

The server uses three key mechanisms:

1. **WebSocket event subscription**: `lark-cli event +subscribe` maintains a persistent WebSocket connection to Feishu's event gateway. No public IP or webhook endpoint needed.

2. **MCP channel notifications**: When a message arrives, the server pushes it to Claude Code via `notifications/claude/channel` — the same protocol the built-in Telegram channel uses.

3. **lark-cli IM shortcuts**: Outbound messages use `lark-cli im +messages-send` and `+messages-reply` for reliable delivery.

## Troubleshooting

### Messages not arriving

1. Check the bot has `im:message:receive_as_bot` permission
2. Ensure "Use long connection to receive events" is selected in the console
3. Verify `im.message.receive_v1` event is subscribed
4. Make sure the app is published (not just saved)

### Bot not replying

1. Check the bot has `im:message` (send message) permission
2. Test manually: `lark-cli im +messages-send --chat-id oc_xxx --text "test" --as bot`

### Channel not loading

The `--dangerously-load-development-channels` flag is required for non-marketplace MCP servers. This is a Claude Code security feature.

```bash
# Correct:
claude --dangerously-load-development-channels server:feishu

# Wrong (will show warning but not load):
claude --channels server:feishu
```

## License

MIT
