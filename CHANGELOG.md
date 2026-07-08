# Changelog

## [4.1.0] - 2026-07-08

### Fixed

- 修复账户级配置中 `smtp_server`/`imap_server` 等为 `None` 时覆盖全局默认值导致 SMTP/IMAP 连接失败的问题
  - `_connect_smtp`/`_connect_imap`/`_poll_emails` 改为在连接时直接回退到 `self.cfg`（全局配置），不依赖 `_load_accounts` 合并
  - 修复 `self._config_instance`（始终为 None）→ `self.cfg`（实时读取配置存储）
  - 新增 SMTP/IMAP 未配置时的明确错误提示
- 修复配置字段 `description` 的 `default` 为英文导致 zh-CN 用户在 Dashboard 看到英文的问题（`default` 改为中文）

### Changed

- 邮件事件转换重构为标准 OB12 格式：
  - `user_id` 从原始 From 头改为纯邮箱地址（如 `wsu2059@qq.com`）
  - 新增 `user_nickname` 字段（发件人显示名）
  - `message` 消息段不再混合 Subject/From 前缀，正文为纯文本段
  - 附件转为标准 OB12 `file` 消息段
  - 新增 `email_subject`/`email_from` 便捷扩展字段
  - `email_raw`/`attachments` 保持不变（向后兼容）

- 配置 schema 迁移到新格式：
  - `webui` 字段重命名为 `ui`（`EmailGlobalConfig` 和 `EmailAccountConfig`）
  - 纯字符串 `description` 改为 `{"i18n": "...", "default": "..."}` 结构
  - 两个配置类均添加 `_schema_meta` 分组标签（group_labels）
- 所有日志消息和 `make_error` 消息支持国际化（i18n），通过 `ErisPulse.Core.i18n` 注册 zh-CN / en 翻译
- 配置字段描述注册 i18n 翻译（zh-CN / en）

### Added

- 新增 `_register_i18n()` 方法，注册配置字段和日志消息的多语言翻译
- 新增 `CHANGELOG.md`

### Migration Notes

从 4.0.x 升级时无需手动操作，适配器会自动迁移旧版 `[EmailAdapter.global]` 配置到 `[EmailAdapter]`。
