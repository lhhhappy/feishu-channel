# 飞书频道 for Claude Code

[English](README_EN.md)

为 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 打造的飞书双向消息频道，基于 MCP 协议实现实时推送。

这是一个开源的飞书 Channel。它的工作方式和 Claude Code 内置的 Telegram 频道完全一致：飞书消息实时推送到 Claude Code 会话中，Claude 通过 MCP 工具回复。

## 工作原理

```
飞书 App ──WebSocket──▶ lark-cli event +subscribe
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
                          飞书 App
```

## 环境要求

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) v2.1.87+
- Python 3.10+
- [lark-cli](https://www.npmjs.com/package/@larksuite/cli)（飞书命令行工具）
- 一个开启了机器人能力的飞书自建应用

## 安装步骤

### 1. 安装 lark-cli

```bash
npm install -g @larksuite/cli
npx skills add larksuite/cli -y -g
```

### 2. 安装 Python 依赖

```bash
pip install mcp
```

### 3. 配置 lark-cli

```bash
lark-cli config init
```

按提示创建或关联飞书应用，打开链接完成授权。

### 4. 配置飞书应用

进入[飞书开放平台](https://open.feishu.cn)，找到你的应用：

1. **添加应用能力** → 开启**机器人**
2. **事件与回调** → 订阅方式 → 选择**"使用长连接接收事件"**
3. **添加事件** → `im.message.receive_v1`（接收消息）
4. **权限管理** → 开通以下权限：
   - `im:message:receive_as_bot`（接收消息）
   - `im:message`（发送消息）
   - `im:chat:readonly`（读取群信息）
5. **发布应用**（版本管理 → 创建版本 → 发布）

### 5. 注册 MCP 服务

```bash
cd /path/to/feishu-channel
claude mcp add feishu -s project -- python3 $(pwd)/server.py
```

这会在你的项目中创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "feishu": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/feishu-channel/server.py"]
    }
  }
}
```

### 6. 启动 Claude Code

```bash
claude --dangerously-load-development-channels server:feishu
```

### 7. 在飞书中发消息

打开飞书，找到你的机器人，发一条消息。它会出现在 Claude Code 会话中：

```
feishu · ou_xxxxx: 你好！
```

Claude 会处理消息并通过机器人回复你。

## MCP 工具

| 工具 | 说明 |
|------|------|
| `reply` | 回复飞书消息。支持引用回复（`reply_to`）和文件附件（`files`）。 |
| `react` | 给消息添加表情回应（THUMBSUP、HEART、SMILE、FIRE 等） |
| `edit_message` | 编辑机器人之前发送的消息。编辑不会触发推送通知。 |

## 消息格式

收到的飞书消息以频道通知的形式出现：

```xml
<channel source="feishu" chat_id="oc_xxx" message_id="om_xxx" user="ou_xxx" ts="2025-01-01T00:00:00+00:00">
  你好！
</channel>
```

## 架构说明

服务端使用三个关键机制：

1. **WebSocket 事件订阅**：`lark-cli event +subscribe` 通过 WebSocket 长连接接收飞书事件。不需要公网 IP，不需要配置 Webhook。

2. **MCP 频道通知**：收到消息后，通过 `notifications/claude/channel` 推送到 Claude Code —— 和内置 Telegram 频道使用相同的协议。

3. **lark-cli IM 快捷命令**：发送消息使用 `lark-cli im +messages-send` 和 `+messages-reply`，稳定可靠。

## 常见问题

### 收不到消息

1. 确认机器人有 `im:message:receive_as_bot` 权限
2. 确认事件订阅方式选择了"使用长连接接收事件"
3. 确认已订阅 `im.message.receive_v1` 事件
4. 确认应用已发布（不只是保存）

### 机器人不回复

1. 确认机器人有 `im:message`（发送消息）权限
2. 手动测试：`lark-cli im +messages-send --chat-id oc_xxx --text "测试" --as bot`

### 频道无法加载

非 marketplace 的 MCP 服务需要 `--dangerously-load-development-channels` 标志，这是 Claude Code 的安全机制。

```bash
# 正确：
claude --dangerously-load-development-channels server:feishu

# 错误（会显示警告但不会加载）：
claude --channels server:feishu
```

## License

MIT
