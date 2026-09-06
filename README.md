# qq-history-exporter

把 QQNT（Windows 新版 QQ）的**本地私聊记录**导出成**按时间排序、可检索的 Markdown**，
让任何 AI 工作区（DeepSeek Harness、Claude Desktop、本地 agent…）能直接读取并分析。

> ⚠️ 仅供**本人账号**学习研究使用。解密 QQ 本地库违反腾讯《QQ 软件许可及服务协议》，
> 请勿用于他人数据、勿公开传播真实聊天内容。本项目不内置任何攻击代码与真实数据。
> 许可证：GPL-3.0（内置 `src/msgdb` 来自 GPL-3.0 上游，见 NOTICE）。

## 它解决什么

加密的本地库 AI 读不了。这个工具把它们变成：

```
chats/
├── _index.md                    # 总索引：网名 | 条数 | 时间范围
├── buddy_⭐一个普通的魔法使⭐.md # 私聊全文（文字/图片/回复/转发占位，按时间排序）
└── buddy_六谷.md
```

之后在你的 AI 工作区里问：

> “读取 chats/ 下与「六谷」的聊天记录，分析他说的有没有道理，时间范围 2026-09-02 ~ 09-03”

## 环境与依赖

- Windows（QQNT 数据目录）+ Python 3.10+
- `pip install sqlcipher3 protobuf`
- 密钥：先用 [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)（或其 fork）
  在 QQ 登录时提取；也可通过环境变量 `NTQQ_DB_KEY` 传入。

## 快速开始

```bash
# 1. 先退出 QQ，再复制其 nt_db 目录（保证文件一致）
xcopy "C:\Users\<你>\Documents\Tencent Files\<QQ号>\nt_qq\nt_db" .\ntdb\ /E /I

# 2. 导出
set NTQQ_DB_KEY=<提取到的密钥>
pip install -e .
qq-history-export --ntdb-dir .\ntdb --uin <你的QQ号> --out .
```

只导出部分人（昵称/uid 片段匹配）：

```bash
qq-history-export --ntdb-dir .\ntdb --uin <QQ号> --peers 六谷 魔法使 --out .
```

## 实现原理（简要）

1. 复制原始加密库 → 剥离 1024 字节 NTQQ 自定义头；
2. `sqlcipher3` 按 QQNT 参数解密（`kdf_iter=4000 / HMAC_SHA1 / PBKDF2_HMAC_SHA512 / page 4096`）；
3. 读 `nt_msg.db` 的 `c2c_msg_table`，用内置 msgdb（GPL-3.0 上游）解析 protobuf，
   还原文字 / 图片 / 回复 / 转发占位等消息体；
4. 按“会话 uid → 通讯录昵称”分文件，输出有序 Markdown 与 `_index.md`。

## 已知边界 / Roadmap

- v0.2：**私聊（C2C）全量**导出；**群聊导出计划在 v0.3**；
- 图片/视频只保留占位与本地缓存路径；合并转发正文在服务器端，本地仅占位；
- 库内消息受 QQ 本地保留窗口限制，更早历史请用手机 QQ 备份 / 漫游补齐。

## 相关上游（参考实现；仅 msgdb 为内置代码）

- [QQBackup/QQDecrypt](https://github.com/QQBackup/QQDecrypt) — 格式与流程文档
- [QQBackup/nt_msg_db_util](https://github.com/QQBackup/nt_msg_db_util) — 消息解析层（内置，GPL-3.0）
- [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key) — 密钥提取

## License

GPL-3.0-or-later（见 LICENSE / NOTICE / GPL-3.0-LICENSE.txt）
