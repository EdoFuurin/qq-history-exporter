# qq-history-exporter

把 QQNT（Windows 新版 QQ）的**本地聊天记录**导出成**按时间排序、可检索的 Markdown**，
让任何 AI 工作区（DeepSeek Harness、Claude Desktop、本地 agent…）能直接读取并分析。

> ⚠️ 仅供**本人账号**学习研究使用。解密 QQ 本地库违反腾讯《QQ 软件许可及服务协议》，
> 请勿用于他人数据、勿公开传播真实聊天内容。本项目不内置任何攻击代码与真实数据。

## 它解决什么

你手里有一堆 `.bak` / 本地加密库，AI 读不了。这个工具把它们变成：

```
chats/
├── _index.md                      # 总索引：网名 | 条数 | 时间范围
├── buddy_六谷.md                  # 单聊（文本消息）
├── buddy_⭐一个普通的魔法使⭐.md
└── group_××群.md                  # 群聊
```

之后你只要在自己的 AI 工作区里问：

> “读取 chats/ 下与「六谷」的聊天记录，分析他说的有没有道理，时间范围 2026-09-02 ~ 09-03”

## 环境与依赖

- Windows（QQNT 数据目录）
- Python 3.10+
- `pip install sqlcipher3`（本项目唯一核心依赖）
- 密钥来源：先用 [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)
  （或其 forks）在 QQ 登录时提取；或读 `NTQQ_DB_KEY` 环境变量

## 快速开始

```bash
# 1. 先退出 QQ，复制其 nt_db 目录（防止写入不一致）
xcopy "C:\Users\<你>\Documents\Tencent Files\<QQ号>\nt_qq\nt_db" .\ntdb\ /E /I

# 2. 导出（密钥可通过环境变量传入，避免留在命令行历史）
set NTQQ_DB_KEY=<提取到的密钥>
pip install -e .
qq-history-export --ntdb-dir .\ntdb --uin <你的QQ号> --out .
```

可选过滤（只导出指定网名/群号，昵称支持片段匹配）：

```bash
qq-history-export --ntdb-dir .\ntdb --uin <QQ号> --peers 六谷 魔法使 --out .
```

## 目录结构

```
src/qqhex/cli.py      # 核心：剥 1024 字节头 → SQLCipher 解密 → FTS 文本导出 → 索引
pyproject.toml
```

## 说明与已知边界

- v0.1 导出**文字类消息**（来自 QQ 搜索索引表 buddy/group_msg_fts），
  图片/视频/文件等会缺失——请用 ——先复制再导，且最好在 QQ 退出时复制。
- 群聊/单聊均按“网名/群名”命名文件，文件名已做安全处理。
- 密钥不要写进仓库或提交；`--key` 与 `.gitignore` 已配合使用。

## 相关上游（参考实现，非本仓库代码）

- [QQBackup/QQDecrypt](https://github.com/QQBackup/QQDecrypt) — 格式与流程文档
- [QQBackup/nt_msg_db_util](https://github.com/QQBackup/nt_msg_db_util) — 消息解析
- [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key) — 密钥提取

## License

MIT
