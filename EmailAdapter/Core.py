import asyncio
import email
import imaplib
import smtplib
import ssl
import time
import uuid
from dataclasses import dataclass, field
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Union

from ErisPulse.Core import adapter as adapter_mgr
from ErisPulse.Core import client
from ErisPulse.Core.Bases.adapter import BaseAdapter
from ErisPulse.Core.config import config as config_mgr
from ErisPulse.Core.i18n import i18n
from ErisPulse.runtime.config_schema import (
    AdapterConfig,
    BotAccountConfig,
    dict_to_dataclass,
)


@dataclass
class EmailGlobalConfig(AdapterConfig):
    """Email 适配器全局配置（适用于所有账户的默认值）"""

    imap_server: str = field(
        default="imap.example.com",
        metadata={
            "description": {"i18n": "email.imap_server", "default": "默认 IMAP 服务器地址"},
            "ui": {"widget": "text", "group": "imap", "order": 1},
        },
    )
    imap_port: int = field(
        default=993,
        metadata={
            "description": {"i18n": "email.imap_port", "default": "默认 IMAP 端口"},
            "ui": {"widget": "number", "group": "imap", "order": 2},
        },
    )
    smtp_server: str = field(
        default="smtp.example.com",
        metadata={
            "description": {"i18n": "email.smtp_server", "default": "默认 SMTP 服务器地址"},
            "ui": {"widget": "text", "group": "smtp", "order": 3},
        },
    )
    smtp_port: int = field(
        default=465,
        metadata={
            "description": {"i18n": "email.smtp_port", "default": "默认 SMTP 端口"},
            "ui": {"widget": "number", "group": "smtp", "order": 4},
        },
    )
    ssl: bool = field(
        default=True,
        metadata={
            "description": {"i18n": "email.ssl", "default": "是否默认启用 SSL"},
            "ui": {"widget": "switch", "group": "basic", "order": 5},
        },
    )
    timeout: int = field(
        default=30,
        metadata={
            "description": {"i18n": "email.timeout", "default": "默认连接超时（秒）"},
            "ui": {"widget": "number", "group": "basic", "order": 6},
        },
    )
    poll_interval: int = field(
        default=60,
        metadata={
            "description": {"i18n": "email.poll_interval", "default": "IMAP 轮询间隔（秒）"},
            "ui": {"widget": "number", "group": "polling", "order": 7},
        },
    )
    max_retries: int = field(
        default=3,
        metadata={
            "description": {"i18n": "email.max_retries", "default": "连接失败最大重试次数"},
            "ui": {"widget": "number", "group": "polling", "order": 8},
        },
    )


EmailGlobalConfig._schema_meta = {
    "group_labels": {
        "basic": {"i18n": "email.group.basic", "default": "基本设置"},
        "imap": {"i18n": "email.group.imap", "default": "IMAP 设置"},
        "smtp": {"i18n": "email.group.smtp", "default": "SMTP 设置"},
        "polling": {"i18n": "email.group.polling", "default": "轮询设置"},
    }
}  # type: ignore[attr-defined]


@dataclass
class EmailAccountConfig(BotAccountConfig):
    """Email 单个账户配置"""

    email: str = field(
        default="",
        metadata={
            "description": {"i18n": "email.account.email", "default": "邮箱地址"},
            "required": True,
            "secret": True,
            "ui": {"widget": "text", "group": "basic", "order": 1},
        },
    )
    password: str = field(
        default="",
        metadata={
            "description": {"i18n": "email.account.password", "default": "邮箱密码 / 授权码"},
            "required": True,
            "secret": True,
            "ui": {"widget": "password", "group": "basic", "order": 2},
        },
    )
    imap_server: Optional[str] = field(
        default=None,
        metadata={
            "description": {"i18n": "email.account.imap_server", "default": "IMAP 服务器地址（留空使用全局默认）"},
            "ui": {"widget": "text", "group": "imap", "order": 3},
        },
    )
    imap_port: Optional[int] = field(
        default=None,
        metadata={
            "description": {"i18n": "email.account.imap_port", "default": "IMAP 端口（留空使用全局默认）"},
            "ui": {"widget": "number", "group": "imap", "order": 4},
        },
    )
    smtp_server: Optional[str] = field(
        default=None,
        metadata={
            "description": {"i18n": "email.account.smtp_server", "default": "SMTP 服务器地址（留空使用全局默认）"},
            "ui": {"widget": "text", "group": "smtp", "order": 5},
        },
    )
    smtp_port: Optional[int] = field(
        default=None,
        metadata={
            "description": {"i18n": "email.account.smtp_port", "default": "SMTP 端口（留空使用全局默认）"},
            "ui": {"widget": "number", "group": "smtp", "order": 6},
        },
    )
    ssl: bool = field(
        default=True,
        metadata={
            "description": {"i18n": "email.account.ssl", "default": "启用 SSL"},
            "ui": {"widget": "switch", "group": "basic", "order": 7},
        },
    )
    timeout: int = field(
        default=30,
        metadata={
            "description": {"i18n": "email.account.timeout", "default": "连接超时（秒）"},
            "ui": {"widget": "number", "group": "basic", "order": 8},
        },
    )


EmailAccountConfig._schema_meta = {
    "group_labels": {
        "basic": {"i18n": "email.group.basic", "default": "基本设置"},
        "imap": {"i18n": "email.group.imap", "default": "IMAP 设置"},
        "smtp": {"i18n": "email.group.smtp", "default": "SMTP 设置"},
    }
}  # type: ignore[attr-defined]


class EmailAdapter(BaseAdapter):
    """Email 适配器（多账户），基于 stdlib smtplib/imaplib 实现"""

    _platform = "email"
    AccountConfigClass = EmailAccountConfig
    ConfigClass = EmailGlobalConfig

    class Send(BaseAdapter.Send):
        """邮件发送 DSL

        NOTE: At / AtAll / Reply 由 SendDSL 基类内置，此处不再自定义。
        本类只保留邮件特有方法（Subject / Html / Cc / Bcc / ReplyTo / Attachment 等）。
        """

        def __init__(self, adapter, target_type=None, target_id=None, account_id=None):
            super().__init__(adapter, target_type, target_id, account_id)
            self._subject = ""
            self._html = ""
            self._text = ""
            self._attachments = []
            self._cc = []
            self._bcc = []
            self._reply_to = None
            self._in_reply_to = None  # 用于回复原始邮件的 Message-ID

        def Subject(self, subject: str):
            """设置邮件主题"""
            self._subject = subject
            return self

        def Html(self, html: str):
            """设置 HTML 内容并发送邮件"""
            self._html = html
            return asyncio.create_task(self._send())

        def Text(self, text: str):
            """设置纯文本内容并发送邮件"""
            self._text = text
            return asyncio.create_task(self._send())

        def Raw_ob12(self, message, **kwargs):
            """
            发送原始 OneBot12 格式的消息

            :param message: OneBot12 格式的消息段或消息段数组
            :param kwargs: 额外参数（如 subject, reply_to, in_reply_to 等）
            :return: asyncio.Task 对象
            """
            return asyncio.create_task(self._process_raw_ob12(message, **kwargs))

        async def _process_raw_ob12(self, message, **kwargs):
            """
            处理 OneBot12 格式消息并转换为邮件发送

            :param message: OneBot12 格式的消息段或消息段数组
            :param kwargs: 额外参数
            :return: 发送结果
            """
            # 处理额外参数
            if "subject" in kwargs:
                self._subject = kwargs["subject"]
            if "reply_to" in kwargs:
                self._reply_to = kwargs["reply_to"]
            if "in_reply_to" in kwargs:
                self._in_reply_to = kwargs["in_reply_to"]

            # 应用修饰符（@/回复等），由基类内置 At/AtAll/Reply 写入
            if isinstance(message, list):
                message = self._apply_modifiers(message)

            # 统一处理为消息段数组
            if isinstance(message, dict) and message.get("type") in [
                "text",
                "image",
                "video",
                "file",
                "audio",
            ]:
                segments = [message]
            elif isinstance(message, list):
                segments = message
            else:
                raise ValueError(
                    "Invalid message format, expected OneBot12 message segment or array"
                )

            # 解析消息段
            for segment in segments:
                seg_type = segment.get("type")
                data = segment.get("data", {})

                if seg_type == "text":
                    self._text += data.get("text", "")
                elif seg_type == "image":
                    self._add_attachment_from_segment(data, "image")
                elif seg_type == "video":
                    self._add_attachment_from_segment(data, "video")
                elif seg_type == "file":
                    self._add_attachment_from_segment(data, "file")
                elif seg_type == "audio":
                    self._add_attachment_from_segment(data, "audio")
                elif seg_type == "markdown":
                    self._html = self._markdown_to_html(data.get("markdown", ""))
                else:
                    # 不支持的类型，转换为文本
                    self._text += f"\n[Unsupported segment type: {seg_type}]"

            return await self._send()

        def _add_attachment_from_segment(self, data: Dict, content_type: str):
            """从消息段数据添加附件，支持本地路径"""
            url = data.get("url")
            file_id = data.get("file_id")
            path = data.get("path")

            if url:
                self._attachments.append(
                    (
                        url,
                        f"{content_type}_{path or file_id}",
                        f"application/{content_type}",
                    )
                )
            elif path:
                # 本地路径，检查文件是否存在
                file_path = Path(path)
                if not file_path.exists():
                    raise FileNotFoundError(f"文件不存在: {path}")
                filename = f"{content_type}_{file_id}" if file_id else file_path.name
                self._attachments.append(
                    (path, filename, f"application/{content_type}")
                )
            elif file_id:
                self._attachments.append(
                    (
                        file_id,
                        f"{content_type}_{file_id}",
                        f"application/{content_type}",
                    )
                )

        def _markdown_to_html(self, markdown: str) -> str:
            """简单的 Markdown 到 HTML 转换"""
            html = markdown
            # 简单的转换规则
            html = html.replace("**", "<strong>").replace("*", "<em>")
            html = html.replace("# ", "<h1>").replace("\n", "<br>")
            return html

        def Attachment(
            self,
            file: Union[str, Path, BinaryIO],
            filename: str = None,
            mime_type: str = "application/octet-stream",
        ):
            """添加附件"""
            # 如果是字符串或Path，检查是否为本地文件路径（排除URL）
            if isinstance(file, (str, Path)):
                # 如果是URL，直接使用，不检查文件存在性
                if isinstance(file, str) and file.startswith(("http://", "https://")):
                    pass
                else:
                    # 本地文件路径，检查文件是否存在
                    file_path = Path(file)
                    if not file_path.exists():
                        raise FileNotFoundError(f"文件不存在: {file_path}")

            self._attachments.append((file, filename, mime_type))
            return self

        def Cc(self, emails: Union[str, List[str]]):
            """设置抄送"""
            if isinstance(emails, str):
                emails = [emails]
            self._cc.extend(emails)
            return self

        def Bcc(self, emails: Union[str, List[str]]):
            """设置密送"""
            if isinstance(emails, str):
                emails = [emails]
            self._bcc.extend(emails)
            return self

        def ReplyTo(self, email: str):
            """设置 Reply-To 回复地址（邮件特有）"""
            self._reply_to = email
            return self

        async def _send(self):
            """内部发送方法"""
            adapter = self._adapter
            ctx = self.send_context
            target_id = ctx.get("target_id")
            account_name = ctx.get("account_id")

            if not adapter.accounts:
                raise ValueError("No email account configured")

            # 多账户解析：未指定时使用第一个账户
            account_name, account = adapter._resolve_account(account_name)

            # 构建邮件
            msg = MIMEMultipart()
            msg["From"] = account.email
            msg["To"] = target_id if target_id else account.email
            msg["Subject"] = self._subject

            # 处理抄送（包含 At 方法添加的邮件 —— At 由基类内置，映射到 _at_user_ids）
            all_cc = list(self._cc)
            for at_id in getattr(self, "_at_user_ids", []) or []:
                all_cc.append(str(at_id))
            if getattr(self, "_at_all", False):
                # @全体成员：在主题中添加 [Broadcast] 标记
                if not msg["Subject"].startswith("[Broadcast]"):
                    msg["Subject"] = f"[Broadcast] {msg['Subject']}"

            if all_cc:
                msg["Cc"] = ", ".join(all_cc)
            if self._bcc:
                msg["Bcc"] = ", ".join(self._bcc)
            if self._reply_to:
                msg["Reply-To"] = self._reply_to
            in_reply_to = self._in_reply_to or getattr(self, "_reply_message_id", None)
            if in_reply_to:
                msg["In-Reply-To"] = str(in_reply_to)
                msg["References"] = str(in_reply_to)

            # 添加正文
            if self._text:
                msg.attach(MIMEText(self._text, "plain"))
            if self._html:
                msg.attach(MIMEText(self._html, "html"))

            # 添加附件
            for attachment in self._attachments:
                file, filename, mime_type = attachment

                if isinstance(file, (str, Path)):
                    # 检查是否为 URL
                    if isinstance(file, str) and file.startswith(
                        ("http://", "https://")
                    ):
                        # 通过 sdk.client.get 下载 URL 内容
                        resp = await client.get(file, timeout=30)
                        if hasattr(resp, "status") and resp.status >= 400:
                            raise RuntimeError(f"下载附件失败: HTTP {resp.status}")
                        file_data = await resp.read()
                        file_name = filename or file.split("/")[-1]
                    else:
                        # 本地文件路径
                        with open(file, "rb") as f:
                            file_data = f.read()
                        file_name = filename or Path(file).name
                else:
                    # 二进制数据
                    file_data = file.read()
                    file_name = filename

                part = MIMEApplication(file_data, Name=file_name)
                part["Content-Disposition"] = f'attachment; filename="{file_name}"'
                msg.attach(part)

            # 发送邮件
            message_id = uuid.uuid4().hex
            msg["Message-ID"] = message_id

            try:
                raw_response = await adapter._send_email(account_name, msg)
                response = adapter.make_response(
                    status="ok",
                    retcode=0,
                    data={
                        "message_id": message_id,
                        "time": time.time(),
                    },
                    message_id=message_id,
                    message="",
                    raw=raw_response,
                )
                response["email_raw"] = raw_response
                return response
            except Exception as e:
                adapter.logger.error(i18n.t("email.send_failed", error=e, default="发送邮件失败: {error}"))
                err = adapter.make_error(retcode=34000, message=str(e), raw=None)
                err["email_raw"] = None
                return err

    def __init__(self, sdk_ref=None):
        super().__init__(sdk_ref)
        # 连接池
        self.smtp_connections: Dict[str, smtplib.SMTP] = {}
        self.imap_connections: Dict[str, "imaplib.IMAP4_SSL"] = {}
        # 轮询任务
        self.poll_tasks: Dict[str, asyncio.Task] = {}
        # 运行状态
        self._is_running = False
        self._register_i18n()

    def _register_i18n(self):
        """注册配置字段与日志消息的 i18n 翻译"""
        try:
            from ErisPulse.runtime.config_schema import register_config_i18n
            register_config_i18n(EmailGlobalConfig, "zh-CN", domain="email")
            register_config_i18n(EmailAccountConfig, "zh-CN", domain="email")
            register_config_i18n(EmailGlobalConfig, "en", {
                "email.imap_server": "Default IMAP server address",
                "email.imap_port": "Default IMAP port",
                "email.smtp_server": "Default SMTP server address",
                "email.smtp_port": "Default SMTP port",
                "email.ssl": "Whether to enable SSL by default",
                "email.timeout": "Default connection timeout (seconds)",
                "email.poll_interval": "IMAP polling interval (seconds)",
                "email.max_retries": "Max retries for failed connections",
                "email.account.email": "Email address",
                "email.account.password": "Email password / authorization code",
                "email.account.imap_server": "IMAP server address (leave empty to use global default)",
                "email.account.imap_port": "IMAP port (leave empty to use global default)",
                "email.account.smtp_server": "SMTP server address (leave empty to use global default)",
                "email.account.smtp_port": "SMTP port (leave empty to use global default)",
                "email.account.ssl": "Enable SSL",
                "email.account.timeout": "Connection timeout (seconds)",
                "email.group.basic": "Basic",
                "email.group.imap": "IMAP",
                "email.group.smtp": "SMTP",
                "email.group.polling": "Polling",
            }, domain="email")
            register_config_i18n(EmailAccountConfig, "en", {
                "email.account.email": "Email address",
                "email.account.password": "Email password / authorization code",
                "email.account.imap_server": "IMAP server address (leave empty to use global default)",
                "email.account.imap_port": "IMAP port (leave empty to use global default)",
                "email.account.smtp_server": "SMTP server address (leave empty to use global default)",
                "email.account.smtp_port": "SMTP port (leave empty to use global default)",
                "email.account.ssl": "Enable SSL",
                "email.account.timeout": "Connection timeout (seconds)",
                "email.group.basic": "Basic",
                "email.group.imap": "IMAP",
                "email.group.smtp": "SMTP",
            }, domain="email")
        except Exception:
            pass

        zh_CN = {
            "email.config_migrated": "已迁移旧版 [EmailAdapter.global] 配置到 [EmailAdapter]",
            "email.old_config_detected": "检测到旧格式配置，建议迁移到 EmailAdapter.accounts 下",
            "email.no_config_found": "未找到配置文件，创建默认账户配置",
            "email.save_default_failed": "保存默认账户配置失败: {error}",
            "email.account_missing_credentials": "账户 {name} 缺少 email 或 password 配置，已跳过",
            "email.accounts_loaded": "Email 适配器初始化完成，共加载 {count} 个账户",
            "email.no_enabled_accounts": "没有找到任何启用的 Email 账户配置",
            "email.adapter_started": "Email 适配器启动完成，共 {count} 个账户",
            "email.adapter_shutdown": "Email 适配器已关闭",
            "email.smtp_error": "SMTP 错误: {error}",
            "email.polling_error": "轮询 {name} 出错: {error}",
            "email.reconnect_failed": "重连 {max} 次后仍失败",
            "email.smtp_connect_failed": "SMTP 连接失败 {name}: {error}",
            "email.send_failed": "发送邮件失败: {error}",
            "email.unsupported_endpoint": "不支持的端点: {endpoint}",
            "email.smtp_not_configured": "SMTP 服务器或端口未配置（账户 {name}），请检查全局配置或账户配置",
            "email.imap_not_configured": "IMAP 服务器或端口未配置（账户 {name}），请检查全局配置或账户配置",
        }
        en = {
            "email.config_migrated": "Migrated legacy [EmailAdapter.global] config to [EmailAdapter]",
            "email.old_config_detected": "Old config format detected, please migrate to EmailAdapter.accounts",
            "email.no_config_found": "No config found, creating default account config",
            "email.save_default_failed": "Failed to save default account config: {error}",
            "email.account_missing_credentials": "Account {name} missing email or password, skipped",
            "email.accounts_loaded": "Email adapter initialized, loaded {count} account(s)",
            "email.no_enabled_accounts": "No enabled Email account config found",
            "email.adapter_started": "Email adapter started, {count} account(s) total",
            "email.adapter_shutdown": "Email adapter shut down",
            "email.smtp_error": "SMTP error: {error}",
            "email.polling_error": "Polling error for {name}: {error}",
            "email.reconnect_failed": "Failed to reconnect after {max} attempts",
            "email.smtp_connect_failed": "Failed to connect SMTP for {name}: {error}",
            "email.send_failed": "Failed to send email: {error}",
            "email.unsupported_endpoint": "Unsupported endpoint: {endpoint}",
            "email.smtp_not_configured": "SMTP server or port not configured (account {name}), please check global or account config",
            "email.imap_not_configured": "IMAP server or port not configured (account {name}), please check global or account config",
        }
        try:
            i18n.register("zh-CN", zh_CN, domain="email")
            i18n.register("en", en, domain="email")
        except Exception:
            pass

    def _get_config_key(self) -> str:
        return "EmailAdapter"

    def _load_config(self):
        """加载全局配置，兼容旧版 [EmailAdapter.global] 迁移"""
        key = self._get_config_key()
        data = config_mgr.getConfig(key)
        if isinstance(data, dict) and isinstance(data.get("global"), dict):
            old_global = data.pop("global")
            for k, v in old_global.items():
                data.setdefault(k, v)
            config_mgr.setConfig(key, data, immediate=True)
            self.logger.info(i18n.t("email.config_migrated", default="已迁移旧版 [EmailAdapter.global] 配置到 [EmailAdapter]"))
        return super()._load_config()

    def _load_accounts(self) -> dict:
        """多账户：返回 {name: EmailAccountConfig}，将全局默认值合并到每个账户"""
        key = "EmailAdapter.accounts"
        data = config_mgr.getConfig(key)

        if not data:
            # 兼容旧格式：直接放在 EmailAdapter 下的 email/password
            old_config = config_mgr.getConfig("EmailAdapter")
            if old_config and ("email" in old_config or "accounts" not in old_config):
                self.logger.warning(
                    i18n.t("email.old_config_detected", default="检测到旧格式配置，建议迁移到 EmailAdapter.accounts 下")
                )
                data = {
                    "default": {
                        "email": old_config.get("email", "user@example.com"),
                        "password": old_config.get("password", "password"),
                        "enabled": True,
                    }
                }
            else:
                self.logger.info(i18n.t("email.no_config_found", default="未找到配置文件，创建默认账户配置"))
                data = {
                    "default": {
                        "email": "user@example.com",
                        "password": "password",
                        "enabled": True,
                    }
                }
                try:
                    config_mgr.setConfig(key, data)
                except Exception as e:
                    self.logger.error(i18n.t("email.save_default_failed", error=e, default="保存默认账户配置失败: {error}"))

        # 全局默认值（来自 ConfigClass 实例，实时读取）
        global_defaults = {}
        try:
            cfg = self.cfg
            if cfg is not None:
                for k in (
                    "imap_server",
                    "imap_port",
                    "smtp_server",
                    "smtp_port",
                    "ssl",
                    "timeout",
                ):
                    global_defaults[k] = getattr(cfg, k, None)
        except Exception:
            pass

        accounts = {}
        for name, account_data in data.items():
            if not isinstance(account_data, dict):
                continue

            # 合并全局默认值（账户级配置优先，但 None 值不覆盖全局默认）
            merged = dict(global_defaults)
            # 兼容旧版嵌套 server 子结构
            server_block = account_data.get("server", {})
            if isinstance(server_block, dict):
                merged.update({k: v for k, v in server_block.items() if v is not None})
            merged.update({k: v for k, v in account_data.items() if k != "server" and v is not None and v != ""})

            if not merged.get("email") or not merged.get("password"):
                self.logger.error(i18n.t("email.account_missing_credentials", name=name, default="账户 {name} 缺少 email 或 password 配置，已跳过"))
                continue

            instance = dict_to_dataclass(EmailAccountConfig, merged)
            instance.name = name
            accounts[name] = instance

        self.logger.info(i18n.t("email.accounts_loaded", count=len(accounts), default="Email 适配器初始化完成，共加载 {count} 个账户"))
        return accounts

    async def _send_email(self, account_id: str, msg: MIMEMultipart) -> Dict:
        account = self.accounts[account_id]
        response = {
            "success": False,
            "message_id": msg.get("Message-ID", ""),
            "account": account.email,
        }

        try:
            if account_id not in self.smtp_connections:
                await self._connect_smtp(account_id)

            smtp = self.smtp_connections[account_id]
            smtp.send_message(msg)
            response["success"] = True
            response["message"] = "Email sent successfully"
        except Exception as e:
            self.logger.error(i18n.t("email.smtp_error", error=e, default="SMTP 错误: {error}"))
            # 尝试重新连接
            try:
                await self._connect_smtp(account_id)
                smtp = self.smtp_connections[account_id]
                smtp.send_message(msg)
                response["success"] = True
                response["message"] = "Email sent successfully after reconnect"
            except Exception as retry_error:
                response["error"] = str(retry_error)
                response["message"] = str(retry_error)
                raise

        return response

    async def _connect_smtp(self, account_id: str):
        account = self.accounts[account_id]

        # 账户级配置优先，缺失时回退到全局配置
        try:
            cfg = self.cfg
        except Exception:
            cfg = None

        smtp_server = account.smtp_server or (cfg.smtp_server if cfg else None)
        smtp_port = account.smtp_port or (cfg.smtp_port if cfg else None)
        use_ssl = account.ssl if account.ssl is not None else (cfg.ssl if cfg else True)
        timeout = account.timeout or (cfg.timeout if cfg else 30)

        if not smtp_server or not smtp_port:
            raise ValueError(
                i18n.t("email.smtp_not_configured", name=account_id, default="SMTP 服务器或端口未配置（账户 {name}），请检查全局配置或账户配置")
            )

        if account_id in self.smtp_connections:
            try:
                self.smtp_connections[account_id].quit()
            except Exception:
                pass

        context = ssl.create_default_context()

        if use_ssl:
            smtp = smtplib.SMTP_SSL(
                host=smtp_server,
                port=smtp_port,
                timeout=timeout,
                context=context,
            )
        else:
            smtp = smtplib.SMTP(
                host=smtp_server,
                port=smtp_port,
                timeout=timeout,
            )

        smtp.login(account.email, account.password)
        self.smtp_connections[account_id] = smtp

    async def _connect_imap(self, account_id: str):
        """连接 IMAP 服务器"""
        account = self.accounts[account_id]

        # 账户级配置优先，缺失时回退到全局配置
        try:
            cfg = self.cfg
        except Exception:
            cfg = None

        imap_server = account.imap_server or (cfg.imap_server if cfg else None)
        imap_port = account.imap_port or (cfg.imap_port if cfg else None)

        if not imap_server or not imap_port:
            raise ValueError(
                i18n.t("email.imap_not_configured", name=account_id, default="IMAP 服务器或端口未配置（账户 {name}），请检查全局配置或账户配置")
            )

        if account_id in self.imap_connections:
            try:
                self.imap_connections[account_id].logout()
            except Exception:
                pass

        context = ssl.create_default_context()

        imap = imaplib.IMAP4_SSL(
            host=imap_server, port=imap_port, ssl_context=context
        )

        imap.login(account.email, account.password)
        imap.select("INBOX")
        self.imap_connections[account_id] = imap

    async def _poll_emails(self, account_id: str):
        poll_interval = 60
        max_retries = 3
        try:
            cfg = self.cfg
            poll_interval = (
                getattr(cfg, "poll_interval", poll_interval) or poll_interval
            )
            max_retries = getattr(cfg, "max_retries", max_retries) or max_retries
        except Exception:
            pass

        while self._is_running:
            try:
                if account_id not in self.imap_connections:
                    await self._connect_imap(account_id)

                imap = self.imap_connections[account_id]
                imap.noop()  # 保持连接活跃

                # 搜索未读邮件
                status, messages = imap.search(None, "UNSEEN")
                if status == "OK" and messages[0]:
                    for num in messages[0].split():
                        status, data = imap.fetch(num, "(RFC822)")
                        if status == "OK":
                            raw_email = data[0][1]
                            email_message = email.message_from_bytes(raw_email)

                            # 转换为标准事件并提交
                            event = self._convert_email_to_event(
                                email_message, account_id
                            )
                            await adapter_mgr.emit(event)

                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(i18n.t("email.polling_error", name=account_id, error=e, default="轮询 {name} 出错: {error}"))
                retries = 0
                while retries < max_retries:
                    try:
                        await self._connect_imap(account_id)
                        break
                    except Exception:
                        retries += 1
                        if retries >= max_retries:
                            self.logger.error(
                                i18n.t("email.reconnect_failed", max=max_retries, default="重连 {max} 次后仍失败")
                            )
                            raise
                        await asyncio.sleep(5)

    def _convert_email_to_event(
        self, email_message: email.message.Message, account_id: str
    ) -> Dict:
        """
        将邮件转换为 OneBot12 标准事件

        遵循 ErisPulse 适配器标准化转换规范：
        - user_id 为纯邮箱地址，user_nickname 为发件人显示名
        - message 为标准 OB12 消息段（text + file）
        - email_raw 保留完整原始数据（向后兼容）
        """
        from email.utils import parseaddr

        # 确定原始事件类型
        references = email_message.get("References", "")
        in_reply_to = email_message.get("In-Reply-To", "")

        if references or in_reply_to:
            raw_event_type = "email_reply"
        else:
            raw_event_type = "email_new"

        # 解析邮件头
        def decode_header(header):
            from email.header import decode_header

            decoded = decode_header(header)
            parts = []
            for part, encoding in decoded:
                if isinstance(part, bytes):
                    try:
                        part = part.decode(encoding or "utf-8")
                    except Exception:
                        part = part.decode("utf-8", errors="replace")
                parts.append(part)
            return "".join(parts)

        subject = decode_header(email_message.get("Subject", ""))
        from_ = decode_header(email_message.get("From", ""))
        to = decode_header(email_message.get("To", ""))
        date = email_message.get("Date", "")

        # 从 From 头提取纯邮箱地址和显示名
        # "Saber" <wsu2059@qq.com> -> ("Saber", "wsu2059@qq.com")
        display_name, clean_email = parseaddr(from_)
        if not display_name:
            display_name = clean_email

        # 解析正文和附件
        text_content = ""
        html_content = ""
        attachments = []

        for part in email_message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    filename = decode_header(filename)
                    attachments.append(
                        {
                            "filename": filename,
                            "content_type": content_type,
                            "size": len(part.get_payload(decode=True)),
                            "data": part.get_payload(decode=True),
                        }
                    )
            elif content_type == "text/plain":
                payload = part.get_payload(decode=True)
                try:
                    text_content = payload.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        text_content = payload.decode("gbk")
                    except UnicodeDecodeError:
                        text_content = payload.decode("utf-8", errors="replace")
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                try:
                    html_content = payload.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        html_content = payload.decode("gbk")
                    except UnicodeDecodeError:
                        html_content = payload.decode("utf-8", errors="replace")

        account = self.accounts.get(account_id)
        self_email = account.email if account else account_id

        # 构建 OB12 标准消息段
        message_segments = []

        # 正文文本段
        if text_content:
            message_segments.append(
                {"type": "text", "data": {"text": text_content}}
            )
        elif html_content and not text_content:
            # 无纯文本时，从 HTML 提取简单文本
            import re
            simple_text = re.sub(r"<[^>]+>", "", html_content).strip()
            if simple_text:
                message_segments.append(
                    {"type": "text", "data": {"text": simple_text}}
                )

        # 附件转为 OB12 file 消息段
        for att in attachments:
            message_segments.append(
                {
                    "type": "file",
                    "data": {
                        "file_id": att["filename"],
                        "file_name": att["filename"],
                        "size": att["size"],
                    },
                }
            )

        # 确保至少有一个消息段
        if not message_segments:
            message_segments.append({"type": "text", "data": {"text": subject or ""}})

        # 构建标准事件
        return {
            "id": email_message.get("Message-ID", ""),
            "time": self._parse_email_date(date),
            "type": "message",
            "detail_type": "private",
            "platform": "email",
            "self": {"platform": "email", "user_id": self_email},
            "message": message_segments,
            "alt_message": subject or text_content[:50] if text_content else "",
            "user_id": clean_email or from_,
            "user_nickname": display_name,
            # 邮件扩展字段
            "email_subject": subject,
            "email_from": clean_email or from_,
            # 平台原始数据（向后兼容）
            "email_raw": {
                "subject": subject,
                "from": from_,
                "to": to,
                "date": date,
                "message_id": email_message.get("Message-ID", ""),
                "references": email_message.get("References", ""),
                "in_reply_to": email_message.get("In-Reply-To", ""),
                "cc": decode_header(email_message.get("Cc", "")),
                "bcc": decode_header(email_message.get("Bcc", "")),
                "text_content": text_content,
                "html_content": html_content,
                "attachments": [att["filename"] for att in attachments],
            },
            "email_raw_type": raw_event_type,
            # 向后兼容：保留顶层 attachments
            "attachments": attachments,
        }

    def _parse_email_date(self, date_str: str) -> int:
        from email.utils import parsedate_to_datetime

        try:
            dt = parsedate_to_datetime(date_str)
            return int(dt.timestamp())
        except ValueError:
            return int(time.time())

    async def call_api(self, endpoint: str, _account_id: str = None, **params):
        # 多账户解析（确保账户存在，未指定时使用默认账户）
        account_name, account = self._resolve_account(_account_id)

        if endpoint == "send":
            send_instance = self.Send(
                self,
                target_type=params.get("target_type"),
                target_id=params.get("recvId") or params.get("target_id"),
                account_id=account_name,
            )
            return await send_instance.Text(params.get("content", ""))
        elif endpoint == "send_html":
            send_instance = self.Send(
                self,
                target_type=params.get("target_type"),
                target_id=params.get("recvId") or params.get("target_id"),
                account_id=account_name,
            )
            return await send_instance.Html(params.get("html", ""))
        elif endpoint == "send_raw":
            # 支持 Raw_ob12 方法调用
            send_instance = self.Send(
                self,
                target_type=params.get("target_type"),
                target_id=params.get("target_id"),
                account_id=account_name,
            )
            task = send_instance.Raw_ob12(
                params.get("message"),
                **{
                    k: v
                    for k, v in params.items()
                    if k not in ["message", "target_type", "target_id", "account_id"]
                },
            )
            return await task
        else:
            return self.make_error(
                retcode=10002,
                message=i18n.t("email.unsupported_endpoint", endpoint=endpoint, default="不支持的端点: {endpoint}"),
                raw=None,
            )

    async def start(self):
        if not self.enabled_accounts:
            self.logger.warning(i18n.t("email.no_enabled_accounts", default="没有找到任何启用的 Email 账户配置"))
            return

        self._is_running = True

        # 连接所有 SMTP 服务器并对每个账户 emit connect
        for account_name, account in self.enabled_accounts.items():
            try:
                await self._connect_smtp(account_name)
            except Exception as e:
                self.logger.error(
                    i18n.t("email.smtp_connect_failed", name=account_name, error=e, default="SMTP 连接失败 {name}: {error}")
                )
            try:
                await self.emit_meta("connect", account.email)
            except Exception:
                pass

        # 启动轮询任务（仅对配置了 IMAP 的账户）
        for account_name, account in self.enabled_accounts.items():
            if account.imap_server:
                self.poll_tasks[account_name] = asyncio.create_task(
                    self._poll_emails(account_name)
                )

        self.logger.info(
            i18n.t("email.adapter_started", count=len(self.enabled_accounts), default="Email 适配器启动完成，共 {count} 个账户")
        )

    async def shutdown(self):
        self._is_running = False

        # 取消所有轮询任务
        for task in self.poll_tasks.values():
            if not task.done():
                task.cancel()
        if self.poll_tasks:
            await asyncio.gather(*self.poll_tasks.values(), return_exceptions=True)
        self.poll_tasks.clear()

        # 关闭所有 SMTP 连接
        for account_id, smtp in self.smtp_connections.items():
            try:
                smtp.quit()
            except Exception:
                pass
        self.smtp_connections.clear()

        # 关闭所有 IMAP 连接
        for account_id, imap in self.imap_connections.items():
            try:
                imap.logout()
            except Exception:
                pass
        self.imap_connections.clear()

        # 对每个账户 emit disconnect
        for account_name, account in self.enabled_accounts.items():
            try:
                await self.emit_meta("disconnect", account.email)
            except Exception:
                pass

        try:
            unregister_platform_event_methods("email")
        except Exception:
            pass

        self.logger.info(i18n.t("email.adapter_shutdown", default="Email 适配器已关闭"))
