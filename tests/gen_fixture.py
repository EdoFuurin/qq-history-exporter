"""生成合成测试库（无任何真实数据）。

用法： python tests/gen_fixture.py
产物： tests/data/ntdb/{profile_info.db, nt_msg.db}
      —— 每个文件 = 1024 字节占位头 + SQLCipher(QQNT参数) 数据库。
固定密钥：FIXTUREKEY123456（仅测试用）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import sqlcipher3.dbapi2 as sc  # noqa: E402
from msgdb.proto import c2c_40800_pb2 as pb  # noqa: E402

KEY = "FIXTUREKEY123456"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "ntdb")
os.makedirs(DATA, exist_ok=True)

MY_UID = "u_ME00000000000000000000"
A_UID = "u_A0000000000000000000000"
B_UID = "u_B0000000000000000000000"


def new_conn(path: str):
    con = sc.connect(path, isolation_level=None)
    con.execute("PRAGMA cipher_page_size = 4096;")
    con.execute("PRAGMA key = '%s';" % KEY)
    con.execute("PRAGMA kdf_iter = 4000;")
    con.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
    con.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
    return con


def text_blob(content: str, content_type: int = 1) -> bytes:
    body = pb.MsgBody()
    c = body.content.add()
    c.content_type = content_type
    c.text = content
    return body.SerializeToString()


def build_db(fname: str, table: str, schema_sql: str, rows) -> str:
    raw = os.path.join(DATA, fname + ".raw")
    final = os.path.join(DATA, fname)
    if os.path.exists(raw):
        os.remove(raw)
    if os.path.exists(final):
        os.remove(final)
    con = new_conn(raw)
    con.execute(schema_sql)
    for r in rows:
        con.execute("INSERT INTO \"%s\" VALUES (%s)" % (table, ",".join(["?"] * len(r))), r)
    con.commit()
    con.close()
    # 加 1024 字节占位头，模拟 QQNT 原始文件
    with open(raw, "rb") as f:
        body = f.read()
    with open(final, "wb") as f:
        f.write(b"\x00" * 1024)
        f.write(body)
    os.remove(raw)
    return final


def main():
    profile_schema = (
        'CREATE TABLE "profile_info_v6" '
        '("1000" TEXT, "1002" TEXT, "20002" TEXT)'
    )
    profile_rows = [
        (MY_UID, "10001", "我自己"),
        (A_UID, "20001", "好友A"),
        (B_UID, "30001", "好友B"),
    ]
    build_db("profile_info.db", "profile_info_v6", profile_schema, profile_rows)

    c2c_schema = (
        'CREATE TABLE "c2c_msg_table" ('
        '"40001" INTEGER, "40050" INTEGER, "40013" INTEGER, "40020" TEXT, '
        '"40033" TEXT, "40021" TEXT, "40030" TEXT, "40011" INTEGER, "40800" BLOB)'
    )
    t = 1780000000
    rows = [
        # 我给 A：纯文本（40021=会话对象A 恒定）
        (1, t, 2, MY_UID, "10001", A_UID, "20001", 2, text_blob("你好，这是发给好友A的测试消息一")),
        # A 回我：纯文本
        (2, t + 60, 0, A_UID, "20001", A_UID, "20001", 2, text_blob("测试消息二：收到收到")),
        # 我给 B：纯文本
        (3, t + 120, 2, MY_UID, "10001", B_UID, "30001", 2, text_blob("发给好友B的测试")),
        # A 发图片（无正文 -> 占位）
        (4, t + 300, 0, A_UID, "20001", A_UID, "20001", 2, None),
    ]
    build_db("nt_msg.db", "c2c_msg_table", c2c_schema, rows)
    print("fixtures ready in", DATA)


if __name__ == "__main__":
    main()
