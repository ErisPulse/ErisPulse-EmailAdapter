# Email 适配器与 OneBot12 协议的转换对照

## Email 特有事件类型

### 1. 新邮件事件 (email_new)

#### 原始邮件数据

```
From: "Saber" <wsu2059@qq.com>
To: <bot@example.com>
Subject: 321
Date: Wed, 9 Jul 2026 02:00:46 +0800
Content-Type: text/plain

邮件正文内容
```

#### OneBot12 标准事件

```json
{
  "id": "<message-id@example.com>",
  "time": 1751990446,
  "type": "message",
  "detail_type": "private",
  "platform": "email",
  "self": {
    "platform": "email",
    "user_id": "bot@example.com"
  },
  "message": [
    {
      "type": "text",
      "data": {
        "text": "邮件正文内容"
      }
    }
  ],
  "alt_message": "321",
  "user_id": "wsu2059@qq.com",
  "user_nickname": "Saber",
  "email_subject": "321",
  "email_from": "wsu2059@qq.com",
  "email_raw": {
    "subject": "321",
    "from": "\"Saber\" <wsu2059@qq.com>",
    "to": "<bot@example.com>",
    "date": "Wed, 9 Jul 2026 02:00:46 +0800",
    "message_id": "<message-id@example.com>",
    "references": "",
    "in_reply_to": "",
    "cc": "",
    "bcc": "",
    "text_content": "邮件正文内容",
    "html_content": "",
    "attachments": []
  },
  "email_raw_type": "email_new",
  "attachments": []
}
```

### 2. 回复邮件事件 (email_reply)

当邮件包含 `References` 或 `In-Reply-To` 头时，识别为回复邮件。

```json
{
  "email_raw_type": "email_reply",
  "email_raw": {
    "references": "<original-msg-id@example.com>",
    "in_reply_to": "<original-msg-id@example.com>"
  }
}
```

### 3. 带附件的邮件

```json
{
  "message": [
    {
      "type": "text",
      "data": {
        "text": "请查收附件"
      }
    },
    {
      "type": "file",
      "data": {
        "file_id": "document.pdf",
        "file_name": "document.pdf",
        "size": 102400
      }
    }
  ],
  "email_raw": {
    "attachments": ["document.pdf"]
  },
  "attachments": [
    {
      "filename": "document.pdf",
      "content_type": "application/pdf",
      "size": 102400,
      "data": "..."
    }
  ]
}
```

### 4. HTML 邮件

当邮件只有 HTML 内容（无纯文本）时，自动提取简单文本：

```json
{
  "message": [
    {
      "type": "text",
      "data": {
        "text": "从HTML提取的纯文本内容"
      }
    }
  ],
  "email_raw": {
    "text_content": "",
    "html_content": "<p>从HTML提取的纯文本内容</p>"
  }
}
```

## 字段映射说明

### 标准字段

| OB12 字段 | 来源 | 说明 |
|-----------|------|------|
| `id` | `Message-ID` 头 | 邮件唯一标识 |
| `time` | `Date` 头 | Unix 时间戳（秒） |
| `type` | 固定 `message` | 邮件均为消息事件 |
| `detail_type` | 固定 `private` | 邮件默认为私聊 |
| `platform` | 固定 `email` | 平台标识 |
| `self.user_id` | 账户邮箱 | 接收邮件的邮箱地址 |
| `user_id` | `From` 头（纯邮箱） | 发件人邮箱地址 |
| `user_nickname` | `From` 头（显示名） | 发件人显示名 |
| `alt_message` | `Subject` | 邮件主题 |
| `message` | 邮件正文+附件 | OB12 消息段列表 |

### 扩展字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `email_raw` | dict | 完整原始邮件数据（向后兼容） |
| `email_raw_type` | str | `email_new` 或 `email_reply` |
| `email_subject` | str | 邮件主题（便捷访问） |
| `email_from` | str | 发件人纯邮箱地址 |
| `attachments` | list | 附件数据列表（含二进制数据，向后兼容） |

## 消息段类型映射

### 接收方向（邮件 → OB12）

| 邮件内容 | OB12 消息段 |
|----------|------------|
| 纯文本正文 | `{"type": "text", "data": {"text": "..."}}` |
| HTML 正文（无纯文本时） | 提取纯文本 → `{"type": "text", ...}` |
| 附件 | `{"type": "file", "data": {"file_id": "...", "file_name": "...", "size": N}}` |

### 发送方向（OB12 → 邮件）

| OB12 消息段 | 邮件内容 |
|------------|----------|
| `text` | 纯文本正文 |
| `image` | 图片附件 |
| `video` | 视频附件 |
| `file` | 文件附件 |
| `audio` | 音频附件 |
| `markdown` | 转为 HTML 正文 |

## 事件处理示例

```python
from ErisPulse import sdk

@sdk.on_message(platform="email")
async def handle_email(event):
    # 获取发件人邮箱（纯地址）
    sender = event["user_id"]  # wsu2059@qq.com
    
    # 获取发件人昵称
    nickname = event.get("user_nickname", "")  # Saber
    
    # 获取邮件主题
    subject = event.get("email_subject", "")
    
    # 获取纯文本正文
    text = event.get_text()  # 直接获取第一个 text 段的内容
    
    # 访问完整原始数据
    raw = event.get("email_raw", {})
    html = raw.get("html_content", "")
    
    # 处理附件
    for seg in event.get("message", []):
        if seg["type"] == "file":
            filename = seg["data"]["file_name"]
            size = seg["data"]["size"]
    
    # 回复邮件
    await event.reply(f"已收到你的邮件：{subject}")
```
