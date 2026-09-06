"""QQNT 本地聊天记录导出器（仅限本人账号，仅供学习研究）。

设计目标：
  1. 输入：本机 QQNT 数据目录（nt_db 文件夹，内含 nt_msg.db 等原始加密库）与解密密钥。
  2. 输出：chats/<对话>/ 下按时间排序的 Markdown + chats/_index.md 总索引，
     让任何 AI 工作区（如 DeepSeek Harness / Claude / 本地 agent）能直接检索分析。
"""
from __future__ import annotations

import argparse
import datetime
import io
import os
import re
import sys
import tempfile


def strip_header(src: str, dst: str, header: int = 1024) -> None:
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fin.seek(header)
        while True:
            chunk = fin.read(64 << 20)
            if not chunk:
                break
            fout.write(chunk)


def open_keyed(path: str, key: str):
    import sqlcipher3.dbapi2 as sc

    con = sc.connect(path, isolation_level=None)
    con.execute("PRAGMA cipher_page_size = 4096;")
    con.execute("PRAGMA key = '%s';" % key.replace("'", "''"))
    con.execute("PRAGMA kdf_iter = 4000;")
    con.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
    con.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
    return con


def table_cols(con, table: str):
    return [c[1] for c in con.execute('PRAGMA table_info("%s")' % table)]


def fmt_ts(v):
    try:
        return datetime.datetime.fromtimestamp(int(v)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(v)


# ---------------------------------------------------------------------------
# 通讯录：uid -> 昵称 / 本人 uid
# ---------------------------------------------------------------------------
def load_profile(stripped_dir: str, key: str, my_uin: str | int | None):
    """返回 (uid2nick, my_uid)。profile_info_v6: 1000=uid 1002=QQ号 20002=昵称。"""
    import sqlcipher3.dbapi2 as sc

    path = os.path.join(stripped_dir, "profile_info.db")
    uid2nick, my_uid = {}, None
    if not os.path.exists(path):
        return uid2nick, my_uid
    con = open_keyed(path, key)
    cols = table_cols(con, "profile_info_v6")
    try:
        rows = con.execute("SELECT * FROM profile_info_v6").fetchall()
    finally:
        con.close()
    for r in rows:
        d = dict(zip(cols, r))
        uid = d.get("1000")
        if not uid:
            continue
        nick = d.get("20002") or str(d.get("1002") or "") or str(uid)
        if isinstance(nick, bytes):
            nick = nick.decode("utf-8", "ignore")
        uid2nick[str(uid)] = str(nick)
        if my_uin is not None and str(d.get("1002")) == str(my_uin):
            my_uid = str(uid)
    return uid2nick, my_uid


# ---------------------------------------------------------------------------
# FTS 内容表：文本消息（无需 protobuf 解析，v0.1 的主力来源）
# ---------------------------------------------------------------------------
def export_fts(dbfile: str, label: str, key: str, uid2nick: dict, my_uid: str | None,
               out_dir: str, index: io.TextIOWrapper, peers_filter: list[str]):
    con = open_keyed(dbfile, key)
    try:
        base = "buddy_msg_fts" if "buddy" in label else "group_msg_fts"
        cols = table_cols(con, base)
        rows = con.execute('SELECT * FROM "%s"' % base).fetchall()
    finally:
        con.close()

    peers = {}
    for r in rows:
        d = dict(zip(cols, r))
        text = d.get("41701")
        if not text:
            continue
        if isinstance(text, bytes):
            text = text.decode("utf-8", "ignore")
        ts = d.get("40050")
        # 单聊：40020=发送方 uid，40021=会话对方 uid；群聊：40021=群号
        sender = str(d.get("40020") or "")
        peer = str(d.get("40021") or "")
        if label == "buddy":
            if peer not in uid2nick and sender not in uid2nick:
                continue
            key_peer = peer if peer in uid2nick else sender
        else:
            key_peer = peer or str(d.get("40027") or "")
            if not key_peer:
                continue
        if peers_filter and not any(f in key_peer or f in uid2nick.get(key_peer, "") for f in peers_filter):
            continue
        peers.setdefault(key_peer, []).append((ts, sender, text))

    for peer, msgs in sorted(peers.items(), key=lambda kv: -len(kv[1])):
        msgs.sort(key=lambda x: (int(x[0]) if x[0] else 0))
        name = uid2nick.get(peer, peer if label == "group" else ("好友" + peer[:8]))
        safe = re.sub(r'[\\/:*?"<>|]', "_", name)[:60]
        od = os.path.join(out_dir, "chats")
        os.makedirs(od, exist_ok=True)
        path = os.path.join(od, "%s_%s.md" % (label, safe))
        lines = []
        lines.append("# 与「%s」的聊天记录（%s）\n" % (name, label))
        lines.append("- 对方标识: %s\n- 消息数: %d\n" % (peer, len(msgs)))
        t0 = msgs[0][0] if msgs else 0
        t1 = msgs[-1][0] if msgs else 0
        lines.append("- 时间范围: %s ~ %s\n" % (fmt_ts(t0), fmt_ts(t1)))
        lines.append("\n")
        for ts, sender, text in msgs:
            who = "我" if my_uid and sender == my_uid else "对方"
            lines.append("[%s] %s: %s\n" % (fmt_ts(ts), who, str(text).replace("\n", " ")))
        with io.open(path, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        index.write("- [%s](%s) ｜ %d 条 ｜ %s ~ %s\n" % (
            name, os.path.basename(path), len(msgs), fmt_ts(t0), fmt_ts(t1)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="QQNT 本地聊天记录导出器（本人数据）")
    ap.add_argument("--ntdb-dir", help="QQNT nt_db 文件夹（含 nt_msg.db 等原始加密库）")
    ap.add_argument("--key", help="数据库密钥（也可用环境变量 NTQQ_DB_KEY）")
    ap.add_argument("--uin", help="本机账号 QQ 号（用于识别'我'），如 2876859761")
    ap.add_argument("--out", default=".", help="输出目录（默认当前目录）")
    ap.add_argument("--peers", nargs="*", default=[], help="可选过滤：昵称/群号片段")
    args = ap.parse_args(argv)

    key = args.key or os.environ.get("NTQQ_DB_KEY", "")
    if not key:
        sys.exit("缺少密钥：--key 或环境变量 NTQQ_DB_KEY（可先用 qq-win-db-key 提取）")
    if not args.ntdb_dir or not os.path.isdir(args.ntdb_dir):
        sys.exit("请指定 --ntdb-dir（QQ 未运行时复制 nt_db 文件夹，或用工具自带拷贝）")

    out_abs = os.path.abspath(args.out)
    os.makedirs(os.path.join(out_abs, "chats"), exist_ok=True)
    stripped = os.path.join(out_abs, "_strip")
    os.makedirs(stripped, exist_ok=True)
    try:
        for fn in os.listdir(args.ntdb_dir):
            if fn.endswith(".db"):
                strip_header(os.path.join(args.ntdb_dir, fn), os.path.join(stripped, fn))

        uid2nick, my_uid = load_profile(stripped, key, args.uin)
        with io.open(os.path.join(out_abs, "chats", "_index.md"), "w", encoding="utf-8") as idx:
            idx.write("# 聊天记录索引\n\n你可以在下面文件中检索对话；提问时带上时间范围与网名。\n\n")
            for db, label in [("buddy_msg_fts.db", "buddy"), ("group_msg_fts.db", "group")]:
                p = os.path.join(stripped, db)
                if os.path.exists(p):
                    export_fts(p, label, key, uid2nick, my_uid, out_abs, idx, args.peers)
        print("导出完成 ->", os.path.join(out_abs, "chats"))
    finally:
        import shutil

        shutil.rmtree(stripped, ignore_errors=True)


if __name__ == "__main__":
    main()
