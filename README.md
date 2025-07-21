# ErisPulse 邮箱适配器

一个为 ErisPulse 框架设计的强大邮箱适配器，支持在 ErisPulse 生态系统中以事件形式收发电子邮件。

## 功能特性

- **多账户支持**：可配置多个邮箱账户，每个账户可设置独立的SMTP/IMAP参数
- **全局配置**：可定义全局SMTP和IMAP设置，所有账户均可继承
- **邮件轮询**：自动检查邮箱账户中的新邮件(未读邮件)，并将其转换为标准ErisPulse事件
- **DSL发送**：使用标准ErisPulse `Send` DSL轻松发送邮件
- **附件支持**：支持发送和接收邮件附件
- **HTML与纯文本**：同时支持HTML和纯文本邮件内容

## 安装

像安装其他ErisPulse模块或适配器一样安装本适配器，通常通过pip：

```bash
epsdk install Email
```

如果与ErisPulse安装在同一个Python环境中，它将被自动发现。

## 配置

首次运行后，适配器会在您的`config.toml`文件中生成默认配置块。您需要用真实的邮箱账户信息更新它。

### 配置示例

```toml
[EmailAdapter.global]
imap_server = "imap.example.com"  # 全局IMAP服务器
imap_port = 993                   # IMAP端口
smtp_server = "smtp.example.com"  # 全局SMTP服务器
smtp_port = 465                   # SMTP端口
ssl = true                        # 使用SSL/TLS加密
timeout = 30                      # 连接超时时间(秒)
poll_interval = 10                # 邮件轮询间隔(秒)
max_retries = 3                   # 失败连接的最大重试次数

[EmailAdapter.accounts."support@example.com"]
email = "support@example.com"     # 账户邮箱地址
password = "yourpassword"         # 账户密码

[EmailAdapter.accounts."user@example.com"]
email = "user@example.com"
password = "anotherpassword"
```

## 使用方法

### 发送邮件

使用标准ErisPulse `Send` DSL发送邮件。接收者应为目标邮箱地址。

```python
from ErisPulse import sdk

# 从默认账户发送
await sdk.adapter.mail.Send.To("recipient@example.com").Text("来自ErisPulse的问候！")

# 从特定账户发送带主题的邮件
await sdk.adapter.mail.Send.Using("support@example.com").To("client@company.com") \
    .Subject("重要更新"). \
    .Attachment("document.pdf").
    Text("请查看附件中的文档。") \


# 发送HTML邮件
html_content = """
<h1>欢迎！</h1>
<p>感谢使用我们的服务。</p>
"""
await sdk.adapter.mail.Send.To("user@example.com") \
    .Subject("HTML邮件").Html(html_content)
```

### 接收邮件

收到的邮件会自动转换为标准`message`事件。您可以像监听其他消息一样监听它们。

```python
from ErisPulse import sdk, adapter

@adapter.on("message")
async def handle_email_messages(data: dict):
    # 检查消息是否来自邮箱适配器
    if data.get("platform") == "mail":
        sender = data.get("user_id")
        subject = data["email_raw"]["subject"]
        content = data["email_raw"]["text_content"]
        
        print(f"新邮件来自: {sender}")
        print(f"主题: {subject}")
        print(f"内容:\n{content}")
        
        # 检查附件
        if data.get("attachments"):
            print(f"附件: {[a['filename'] for a in data['attachments']]}")

        # 自动回复示例
        await sdk.adapter.mail.Send.To(sender) \
            .Subject(f"回复: {subject}") \
            .Text("已收到您的邮件，我们将尽快回复。")
```
