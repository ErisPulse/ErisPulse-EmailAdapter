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
        
        def Subject(self, subject: str):
            """设置邮件主题"""
            self._subject = subject
            return self
        
        def Html(self, html: str):
            """设置HTML内容并发送邮件"""
            self._html = html
            return self._send()
        
        def Text(self, text: str):
            """设置纯文本内容并发送邮件"""
            self._text = text
            return self._send()
        
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
            
            if self._cc:
                msg["Cc"] = ", ".join(self._cc)
            if self._bcc:
                msg["Bcc"] = ", ".join(self._bcc)
            if self._reply_to:
                msg["Reply-To"] = self._reply_to
            
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
            try:
                await self._adapter._send_email(account_id, msg)
                return {
                    "status": "ok",
                    "retcode": 0,
                    "data": {"message": "Email sent successfully"},
                    "message": "Email sent successfully",
                    "message_id": uuid.uuid4().hex,
                }
            except Exception as e:
                self._adapter.logger.error(f"Failed to send email: {str(e)}")
                return {
                    "status": "failed",
                    "retcode": 34000,
                    "data": None,
                    "message": str(e),
                    "message_id": "",
                }

    async def _send_email(self, account_id: str, msg: MIMEMultipart):
        account = self.accounts[account_id]
        
        try:
            if account_id not in self.smtp_connections:
                await self._connect_smtp(account_id)
            
            smtp = self.smtp_connections[account_id]
            smtp.send_message(msg)
        except Exception as e:
            self.logger.error(f"SMTP error: {str(e)}")
            # 尝试重新连接
            await self._connect_smtp(account_id)
            smtp = self.smtp_connections[account_id]
            smtp.send_message(msg)
    
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
            "email_raw": {
                "subject": subject,
                "from": from_,
                "to": to,
                "date": date,
                "text_content": text_content,
                "html_content": html_content,
                "attachments": [att["filename"] for att in attachments]
            },
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
            return await self.Send(self).Text(params.get("content", "")).send()
        elif endpoint == "send_html":
            return await self.Send(self).Html(params.get("html", "")).send()
        else:
            return {
                "status": "failed",
                "retcode": 10002,
                "data": None,
                "message": f"Unsupported endpoint: {endpoint}",
                "message_id": ""
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