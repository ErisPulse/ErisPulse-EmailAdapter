import asyncio
import uuid
import email
import smtplib
import imaplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Dict, List, Optional, Union, BinaryIO
from pathlib import Path
import ssl
import time
from dataclasses import dataclass

from ErisPulse import sdk
from ErisPulse.Core import BaseAdapter

@dataclass
class EmailAccountConfig:
    email: str
    password: str
    imap_server: Optional[str] = None
    imap_port: Optional[int] = None
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    ssl: bool = True
    timeout: int = 30

class EmailAdapter(BaseAdapter):
    
    def __init__(self, sdk):
        super().__init__()
        self.sdk = sdk or sdk
        self.logger = self.sdk.logger
        self.env = self.sdk.env
        
        # 加载配置
        self.global_config = self._load_global_config()
        self.accounts: Dict[str, EmailAccountConfig] = self._load_account_configs()
        
        # 连接池
        self.smtp_connections: Dict[str, smtplib.SMTP] = {}
        self.imap_connections: Dict[str, imaplib.IMAP4_SSL] = {}
        
        # 轮询任务
        self.poll_tasks: Dict[str, asyncio.Task] = {}
        
        # 初始化状态
        self._is_running = False

    def _load_global_config(self) -> Dict:
        config = self.env.getConfig("EmailAdapter.global", {})
        
        if not config:
            # 设置默认全局配置
            defaults = {
                "imap_server": "imap.example.com",
                "imap_port": 993,
                "smtp_server": "smtp.example.com",
                "smtp_port": 465,
                "ssl": True,
                "timeout": 30,
                "poll_interval": 60,
                "max_retries": 3
            }
            self.env.setConfig("EmailAdapter.global", defaults)
            return defaults
        return config
    
    
    def _load_account_configs(self) -> Dict[str, EmailAccountConfig]:
        accounts = {}
        account_configs = self.env.getConfig("EmailAdapter.accounts", {})
        
        if not account_configs:
            self.logger.warning("未找到任何账号配置，创建默认账号配置")
            
            # 设置默认账号配置
            defaults = {
                "default": {
                    "email": "user@example.com",
                    "password": "password",
                    "server": {
                        "imap_server": self.global_config["imap_server"],
                        "imap_port": self.global_config["imap_port"],
                        "smtp_server": self.global_config["smtp_server"],
                        "smtp_port": self.global_config["smtp_port"],
                        "ssl": self.global_config["ssl"],
                        "timeout": self.global_config["timeout"]
                    }
                }
            }
            self.env.setConfig("EmailAdapter.accounts", defaults)
            account_configs = defaults

        for account_name, config in account_configs.items():
            # 合并全局配置和账号特定配置
            merged_config = {
                "email": config.get("email"),
                "password": config.get("password"),
                "imap_server": config.get("server", {}).get("imap_server", self.global_config["imap_server"]),
                "imap_port": config.get("server", {}).get("imap_port", self.global_config["imap_port"]),
                "smtp_server": config.get("server", {}).get("smtp_server", self.global_config["smtp_server"]),
                "smtp_port": config.get("server", {}).get("smtp_port", self.global_config["smtp_port"]),
                "ssl": config.get("server", {}).get("ssl", self.global_config["ssl"]),
                "timeout": config.get("server", {}).get("timeout", self.global_config["timeout"]),
            }
            
            accounts[account_name] = EmailAccountConfig(**merged_config)
        
        return accounts
    
    class Send(BaseAdapter.Send):
        """邮件发送DSL"""
        
        def __init__(self, adapter, target_type=None, target_id=None, _account_id=None):
            super().__init__(adapter, target_type, target_id, _account_id)
            self._subject = ""
            self._html = ""
            self._text = ""
            self._attachments = []
            self._cc = []
            self._bcc = []
            self._reply_to = None
            self._in_reply_to = None  # 用于回复原始邮件的 Message-ID
            self._at_emails = []  # @的用户（邮件中作为抄送）
            self._at_all = False  # @全体成员（邮件群发）
        
        def Subject(self, subject: str):
            """设置邮件主题"""
            self._subject = subject
            return self
        
        def Html(self, html: str):
            """设置HTML内容并发送邮件"""
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
            
            # 统一处理为消息段数组
            if isinstance(message, dict) and message.get("type") in ["text", "image", "video", "file", "audio"]:
                segments = [message]
            elif isinstance(message, list):
                segments = message
            else:
                raise ValueError("Invalid message format, expected OneBot12 message segment or array")
            
            # 解析消息段
            for segment in segments:
                seg_type = segment.get("type")
                data = segment.get("data", {})
                
                if seg_type == "text":
                    self._text = data.get("text", "")
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
                elif seg_type == "at":
                    # @用户，添加到抄送
                    user_id = data.get("user_id")
                    if user_id:
                        self._at_emails.append(user_id)
                elif seg_type == "atall":
                    self._at_all = True
                else:
                    # 不支持的类型，转换为文本
                    self._text += f"\n[Unsupported segment type: {seg_type}]"
            
            return await self._send()
        
        def _add_attachment_from_segment(self, data: Dict, content_type: str):
            """从消息段数据添加附件"""
            url = data.get("url")
            file_id = data.get("file_id")
            path = data.get("path")
            
            if url:
                self._attachments.append((url, f"{content_type}_{path or file_id}", f"application/{content_type}"))
            elif path:
                self._attachments.append((path, f"{content_type}_{file_id}", f"application/{content_type}"))
            elif file_id:
                self._attachments.append((file_id, f"{content_type}_{file_id}", f"application/{content_type}"))
        
        def _markdown_to_html(self, markdown: str) -> str:
            """简单的 Markdown 到 HTML 转换"""
            html = markdown
            # 简单的转换规则
            html = html.replace("**", "<strong>").replace("*", "<em>")
            html = html.replace("# ", "<h1>").replace("\n", "<br>")
            return html
        
        def Attachment(self, file: Union[str, Path, BinaryIO], filename: str = None, 
                      mime_type: str = "application/octet-stream"):
            """添加附件"""
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
            """设置回复地址"""
            self._reply_to = email
            return self
        
        def At(self, email: str) -> 'Send':
            """@用户（添加到抄送）"""
            self._at_emails.append(email)
            return self
        
        def AtAll(self) -> 'Send':
            """@全体成员（标记为群发邮件）"""
            self._at_all = True
            return self
        
        def Reply(self, message_id: str) -> 'Send':
            """回复消息（设置 In-Reply-To 头）"""
            self._in_reply_to = message_id
            return self
        
        async def _send(self):
            """内部发送方法"""
            if not self._account_id and not self._adapter.accounts:
                raise ValueError("No email account configured")
            
            account_id = self._account_id or next(iter(self._adapter.accounts.keys()))
            
            if account_id not in self._adapter.accounts:
                raise ValueError(f"Account {account_id} not found")
            
            account = self._adapter.accounts[account_id]
            
            # 构建邮件
            msg = MIMEMultipart()
            msg["From"] = account.email
            msg["To"] = self._target_id if self._target_id else account.email
            msg["Subject"] = self._subject
            
            # 处理抄送（包含 At 方法添加的邮件）
            all_cc = list(self._cc)
            all_cc.extend(self._at_emails)
            if self._at_all:
                # @全体成员：在主题中添加 [Broadcast] 标记
                if not msg["Subject"].startswith("[Broadcast]"):
                    msg["Subject"] = f"[Broadcast] {msg['Subject']}"
            
            if all_cc:
                msg["Cc"] = ", ".join(all_cc)
            if self._bcc:
                msg["Bcc"] = ", ".join(self._bcc)
            if self._reply_to:
                msg["Reply-To"] = self._reply_to
            if self._in_reply_to:
                msg["In-Reply-To"] = self._in_reply_to
                msg["References"] = self._in_reply_to
            
            # 添加正文
            if self._text:
                msg.attach(MIMEText(self._text, "plain"))
            if self._html:
                msg.attach(MIMEText(self._html, "html"))
            
            # 添加附件
            for attachment in self._attachments:
                file, filename, mime_type = attachment
                
                if isinstance(file, (str, Path)):
                    with open(file, "rb") as f:
                        part = MIMEApplication(f.read(), Name=filename or Path(file).name)
                else:
                    part = MIMEApplication(file.read(), Name=filename)
                
                part["Content-Disposition"] = f'attachment; filename="{filename}"'
                msg.attach(part)
            
            # 发送邮件
            message_id = uuid.uuid4().hex
            msg["Message-ID"] = message_id
            
            try:
                raw_response = await self._adapter._send_email(account_id, msg)
                return {
                    "status": "ok",
                    "retcode": 0,
                    "data": {
                        "message_id": message_id,
                        "time": time.time()
                    },
                    "message": "",
                    "message_id": message_id,
                    "email_raw": raw_response
                }
            except Exception as e:
                self._adapter.logger.error(f"Failed to send email: {str(e)}")
                return {
                    "status": "failed",
                    "retcode": 34000,
                    "data": None,
                    "message": str(e),
                    "message_id": "",
                    "email_raw": None
                }

    async def _send_email(self, account_id: str, msg: MIMEMultipart) -> Dict:
        account = self.accounts[account_id]
        response = {
            "success": False,
            "message_id": msg.get("Message-ID", ""),
            "account": account.email
        }
        
        try:
            if account_id not in self.smtp_connections:
                await self._connect_smtp(account_id)
            
            smtp = self.smtp_connections[account_id]
            smtp.send_message(msg)
            response["success"] = True
            response["message"] = "Email sent successfully"
        except Exception as e:
            self.logger.error(f"SMTP error: {str(e)}")
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
        
        if account_id in self.smtp_connections:
            try:
                self.smtp_connections[account_id].quit()
            except Exception:
                pass
        
        context = ssl.create_default_context()
        
        if account.ssl:
            smtp = smtplib.SMTP_SSL(
                host=account.smtp_server,
                port=account.smtp_port,
                timeout=account.timeout,
                context=context
            )
        else:
            smtp = smtplib.SMTP(
                host=account.smtp_server,
                port=account.smtp_port,
                timeout=account.timeout
            )
            if account.ssl:
                smtp.starttls(context=context)
        
        smtp.login(account.email, account.password)
        self.smtp_connections[account_id] = smtp
    
    async def _connect_imap(self, account_id: str):
        """连接IMAP服务器"""
        account = self.accounts[account_id]
        
        if account_id in self.imap_connections:
            try:
                self.imap_connections[account_id].logout()
            except Exception:
                pass
        
        context = ssl.create_default_context()
        
        imap = imaplib.IMAP4_SSL(
            host=account.imap_server,
            port=account.imap_port,
            ssl_context=context
        )
        
        imap.login(account.email, account.password)
        imap.select("INBOX")
        self.imap_connections[account_id] = imap
    
    async def _poll_emails(self, account_id: str):
        poll_interval = self.global_config.get("poll_interval", 60)
        max_retries = self.global_config.get("max_retries", 3)
        
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
                            event = self._convert_email_to_event(email_message, account_id)
                            await sdk.adapter.emit(event)

                await asyncio.sleep(poll_interval)
            except Exception as e:
                self.logger.error(f"Polling error for {account_id}: {str(e)}")
                retries = 0
                while retries < max_retries:
                    try:
                        await self._connect_imap(account_id)
                        break
                    except Exception as e:
                        retries += 1
                        if retries >= max_retries:
                            self.logger.error(f"Failed to reconnect after {max_retries} attempts")
                            raise
                        await asyncio.sleep(5)
    
    def _convert_email_to_event(self, email_message: email.message.Message, account_id: str) -> Dict:
        """
        将邮件转换为 OneBot12 标准事件
        
        根据事件转换规范：
        - 添加 email_raw_type 字段保存原始事件类型
        - 确保时间戳为10位秒级
        - 保留原始数据在 email_raw 字段
        """
        # 确定原始事件类型
        # 检查是否为回复邮件
        references = email_message.get("References", "")
        in_reply_to = email_message.get("In-Reply-To", "")
        
        if references or in_reply_to:
            raw_event_type = "email_reply"  # 回复邮件
        else:
            raw_event_type = "email_new"  # 新邮件
        
        # 解析邮件内容
        def decode_header(header):
            from email.header import decode_header
            decoded = decode_header(header)
            parts = []
            for part, encoding in decoded:
                if isinstance(part, bytes):
                    try:
                        part = part.decode(encoding or 'utf-8')
                    except Exception:
                        part = part.decode('utf-8', errors='replace')
                parts.append(part)
            return ''.join(parts)

        subject = decode_header(email_message.get("Subject", ""))
        from_ = decode_header(email_message.get("From", ""))
        to = decode_header(email_message.get("To", ""))
        date = email_message.get("Date", "")
        
        # 解析正文
        text_content = ""
        html_content = ""
        attachments = []
        
        for part in email_message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            
            if "attachment" in content_disposition:
                # 处理附件
                filename = part.get_filename()
                if filename:
                    attachments.append({
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(part.get_payload(decode=True)),
                        "data": part.get_payload(decode=True)
                    })
            elif content_type == "text/plain":
                # 纯文本内容
                payload = part.get_payload(decode=True)
                try:
                    text_content = payload.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        text_content = payload.decode('gbk')
                    except UnicodeDecodeError:
                        text_content = payload.decode('utf-8', errors='replace')
            elif content_type == "text/html":
                # HTML内容
                payload = part.get_payload(decode=True)
                try:
                    html_content = payload.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        html_content = payload.decode('gbk')
                    except UnicodeDecodeError:
                        html_content = payload.decode('utf-8', errors='replace')
        
        # 构建标准事件
        return {
            "id": email_message.get("Message-ID", ""),
            "time": self._parse_email_date(date),
            "type": "message",
            "detail_type": "private",  # 邮件默认为私聊
            "platform": "email",
            "self": {
                "platform": "email",
                "user_id": account_id
            },
            "message": [
                {
                    "type": "text",
                    "data": {
                        "text": f"Subject: {subject}\nFrom: {from_}\n\n{text_content}"
                    }
                }
            ],
            "alt_message": f"邮件: {subject}",
            "user_id": from_,
            # 平台原始数据（包含完整邮件信息）
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
                "attachments": [att["filename"] for att in attachments]
            },
            # 原始事件类型
            "email_raw_type": raw_event_type,
            "attachments": attachments
        }
    def _parse_email_date(self, date_str: str) -> int:
        from email.utils import parsedate_to_datetime
        try:
            dt = parsedate_to_datetime(date_str)
            return int(dt.timestamp())
        except ValueError:
            return int(time.time())
    
    async def call_api(self, endpoint: str, **params):
        if endpoint == "send":
            send_instance = self.Send(
                self,
                target_type=params.get("target_type"),
                target_id=params.get("recvId") or params.get("target_id"),
                _account_id=params.get("account_id")
            )
            return await send_instance.Text(params.get("content", ""))
        elif endpoint == "send_html":
            send_instance = self.Send(
                self,
                target_type=params.get("target_type"),
                target_id=params.get("recvId") or params.get("target_id"),
                _account_id=params.get("account_id")
            )
            return await send_instance.Html(params.get("html", ""))
        elif endpoint == "/send_raw":
            # 支持 Raw_ob12 方法调用
            send_instance = self.Send(
                self,
                target_type=params.get("target_type"),
                target_id=params.get("target_id"),
                _account_id=params.get("account_id")
            )
            task = send_instance.Raw_ob12(
                params.get("message"),
                **{k: v for k, v in params.items() 
                   if k not in ["message", "target_type", "target_id", "account_id"]}
            )
            return await task
        else:
            return {
                "status": "failed",
                "retcode": 10002,
                "data": None,
                "message": f"Unsupported endpoint: {endpoint}",
                "message_id": "",
                "email_raw": None
            }
    
    async def start(self):
        if not self.accounts:
            self.logger.warning("No email accounts configured")
            return
        
        self._is_running = True
        
        # 连接所有SMTP服务器
        for account_id in self.accounts:
            try:
                await self._connect_smtp(account_id)
            except Exception as e:
                self.logger.error(f"Failed to connect SMTP for {account_id}: {str(e)}")
        
        # 启动轮询任务
        for account_id in self.accounts:
            if self.accounts[account_id].imap_server:  # 只有配置了IMAP的账号才轮询
                self.poll_tasks[account_id] = asyncio.create_task(self._poll_emails(account_id))
    
    async def shutdown(self):
        self._is_running = False
        
        # 取消所有轮询任务
        for task in self.poll_tasks.values():
            task.cancel()
        self.poll_tasks.clear()
        
        # 关闭所有SMTP连接
        for account_id, smtp in self.smtp_connections.items():
            try:
                smtp.quit()
            except Exception:
                pass
        self.smtp_connections.clear()
        
        # 关闭所有IMAP连接
        for account_id, imap in self.imap_connections.items():
            try:
                imap.logout()
            except Exception:
                pass
        self.imap_connections.clear()
