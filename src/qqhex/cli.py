"""QQNT 本地聊天记录导出器 v0.2（仅限本人账号，仅供学习研究）。

v0.2 变化：
  - 私聊(C2C)改为**全量导出**：直接解析 nt_msg.db 的 c2c_msg_table，
    通过内置 msgdb（上游 GPL-3.0 解析层，见 NOTICE）还原文字/图片/回复/转发等，
    输出仍为按时间排序、可供 AI 检索的 Markdown；
  - 群聊沿用 v0.1 的 FTS 文本索引（文字类消息）。
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import re
import shutil
import sys

C2C_COLS = ["msg_id", "timestamp", "direction", "sender_uid", "sender_qq",
            "peer_uid", "peer_qq", "msg_type", "blob"]

C2C_SQL = """SELECT "40001" AS msg_id, "40050" AS timestamp, "40013" AS direction,
"40020" AS sender_uid, "40033" AS sender_qq, "40021" AS peer_uid, "40030" AS peer_qq,
"40011" AS msg_type, "40800" AS blob FROM c2c_msg_table"""


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


def safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)[:60]


def load_profile(stripped_dir: str, key: str, my_uin: str | int | None):
    """(uid2nick, my_uid)；profile_info_v6: 1000=uid, 1002=QQ号, 20002=昵称。"""
    uid2nick, my_uid = {}, None
    p = os.path.join(stripped_dir, "profile_info.db")
    if not os.path.exists(p):
        return uid2nick, my_uid
    con = open_keyed(p, key)
    cols = table_cols(con, "profile_info_v6")
    try:
        rows = con.execute("SELECT * FROM profile_info_v6").fetchall()
    finally:
        con.close()
    for r in rows:
        d = dict(zip(cols, r))
        uid = str(d.get("1000") or "")
        if not uid:
            continue
        nick = d.get("20002") or str(d.get("1002") or "") or uid
        if isinstance(nick, bytes):
            nick = nick.decode("utf-8", "ignore")
        uid2nick[uid] = str(nick)
        if my_uin is not None and str(d.get("1002")) == str(my_uin):
            my_uid = uid
    return uid2nick, my_uid


# ---------------------------------------------------------------------------
# 渲染单条消息（msgdb 解析后的 Message）
# ---------------------------------------------------------------------------
def render(m, has_sender: bool = True) -> str:
    if m.text:
        return m.text
    c = m.content
    if c is None:
        return ""
    tag = type(c).__name__.lower().replace("content", "")
    if tag == "text":
        return getattr(c, "text", "") or ""
    if tag == "image":
        fn = getattr(c, "filename", "") or ""
        loc = getattr(c, "local_path", None) or ""
        return "[图片 %s]%s" % (fn, (" 本地:%s" % loc) if loc else "")
    if tag == "video":
        return "[视频 %s]" % (getattr(c, "filename", "") or "")
    if tag == "file":
        return "[文件 %s]" % (getattr(c, "filename", "") or "")
    if tag == "sticker":
        fb = getattr(c, "text_fallback", None)
        return "[表情]" + (fb or "")
    if tag == "reply":
        s = ""
        if getattr(c, "ref_summary", None):
            s += "回复「%s」" % c.ref_summary
        if getattr(c, "text", None):
            s += c.text
        return s or "[回复消息]"
    if tag == "contact":
        return "[名片 %s]" % (getattr(c, "nickname", "") or getattr(c, "uid", ""))
    if tag == "call":
        return "[通话 %s %s秒]" % (getattr(c, "desc", "") or "", getattr(c, "duration", ""))
    if tag == "sys":
        return "[系统 %s]" % (getattr(c, "content", None) or "")
    if tag == "mixed":
        parts = []
        for seg in getattr(c, "segments", []) or []:
            if seg.get("type") == "text":
                parts.append(seg.get("text", ""))
            else:
                parts.append("[%s]" % seg.get("type"))
        return " ".join(parts)
    if tag in ("forward", "legacyforward"):
        xml = getattr(c, "xml", "") or json.dumps(getattr(c, "meta", {}), ensure_ascii=False)
        n = re.search(r'tSum="(\d+)"', xml)
        t = re.search(r"<title[^>]*>([^<]+)</title>", xml)
        return "[转发聊天记录 %s条]%s" % (n.group(1) if n else "?", (" 「" + t.group(1) + "」") if t else "")
    return "[%s]" % tag


# ---------------------------------------------------------------------------
# 私聊全量导出（C2C）
# ---------------------------------------------------------------------------
def export_c2c(nt_msg_clear: str, key: str, uid2nick: dict, my_uid: str | None,
               my_uin: str | int | None, out_dir: str, index: io.TextIOWrapper,
               peers_filter: list[str]):
    from msgdb.c2c.parser import parse_row  # 内置 msgdb（GPL-3.0）

    con = open_keyed(nt_msg_clear, key)
    try:
        rows = con.execute(C2C_SQL).fetchall()
    finally:
        con.close()

    peers = {}
    for tup in rows:
        rd = dict(zip(C2C_COLS, tup))
        try:
            m = parse_row(rd)
        except Exception:
            continue
        peer = str(m.peer_uid or "")
        if peer not in uid2nick:
            continue  # 只导通讯录里认识的人
        if peers_filter and not any(f in peer or f in uid2nick[peer] for f in peers_filter):
            continue
        peers.setdefault(peer, []).append(m)

    for peer, msgs in sorted(peers.items(), key=lambda kv: -len(kv[1])):
        msgs.sort(key=lambda m: (m.timestamp or 0, m.msg_id or 0))
        name = uid2nick.get(peer, peer)
        path = os.path.join(out_dir, "chats", "buddy_%s.md" % safe_name(name))
        out = []
        out.append("# 与「%s」的聊天记录\n" % name)
        out.append("- 对方标识: %s\n- 消息数: %d\n" % (peer, len(msgs)))
        if msgs:
            out.append("- 时间范围: %s ~ %s\n" % (fmt_ts(msgs[0].timestamp), fmt_ts(msgs[-1].timestamp)))
        out.append("\n")
        for m in msgs:
            is_me = (m.sender_qq == my_uin) or (m.sender_uid == my_uid) or m.direction in (1, 2)
            who = "我" if is_me else "对方"
            body = render(m)
            if not body:
                body = "[（无文本，msg_type=%s）]" % m.msg_type
            out.append("[%s] %s: %s\n" % (fmt_ts(m.timestamp), who, body.replace("\n", " ")))
        with io.open(path, "w", encoding="utf-8") as f:
            f.write("".join(out))
        index.write("- 单聊「%s」: %d 条 ｜ %s ~ %s ｜ 文件 buddy_%s.md\n" % (
            name, len(msgs), fmt_ts(msgs[0].timestamp) if msgs else "-",
            fmt_ts(msgs[-1].timestamp) if msgs else "-", safe_name(name)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="QQNT 本地聊天记录导出器 v0.2（本人数据）")
    ap.add_argument("--ntdb-dir", help="QQNT nt_db 文件夹（含 nt_msg.db 等原始加密库）")
    ap.add_argument("--key", help="数据库密钥（或环境变量 NTQQ_DB_KEY）")
    ap.add_argument("--uin", help="本机账号 QQ 号，如 2876859761")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument("--peers", nargs="*", default=[], help="可选过滤：昵称/uid 片段")
    args = ap.parse_args(argv)

    key = args.key or os.environ.get("NTQQ_DB_KEY", "")
    if not key:
        sys.exit("缺少密钥：--key 或环境变量 NTQQ_DB_KEY（可先用 qq-win-db-key 提取）")
    if not args.ntdb_dir or not os.path.isdir(args.ntdb_dir):
        sys.exit("请指定 --ntdb-dir（建议退出 QQ 后复制 nt_db 目录）")

    out_abs = os.path.abspath(args.out)
    stripped = os.path.join(out_abs, "_strip")
    os.makedirs(os.path.join(out_abs, "chats"), exist_ok=True)
    os.makedirs(stripped, exist_ok=True)
    try:
        for fn in os.listdir(args.ntdb_dir):
            if fn.endswith(".db"):
                strip_header(os.path.join(args.ntdb_dir, fn), os.path.join(stripped, fn))

        uid2nick, my_uid = load_profile(stripped, key, args.uin)
        with io.open(os.path.join(out_abs, "chats", "_index.md"), "w", encoding="utf-8") as idx:
            idx.write("# 聊天记录索引\n\n提问时请带上“网名/群名”与“时间范围”。\n\n")
            nmsg = os.path.join(stripped, "nt_msg.db")
            if os.path.exists(nmsg):
                export_c2c(nmsg, key, uid2nick, my_uid, args.uin, out_abs, idx, args.peers)
        print("导出完成 ->", os.path.join(out_abs, "chats"))
    finally:
        shutil.rmtree(stripped, ignore_errors=True)


if __name__ == "__main__":
    main()
