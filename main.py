"""家庭日常管理平台后端

技术栈: FastAPI + SQLite + 标准库(密码哈希/签名 token)
部署: 容器化，数据落在 DATA_DIR 持久化卷（SQLite + uploads）
"""
import os
import json
import sqlite3
import hashlib
import hmac
import base64
import time
import secrets
import socket
import ipaddress
import urllib.request
from datetime import datetime, date

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Body, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "app.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SECRET = os.environ.get("APP_SECRET", "change-me-dev-secret").encode()
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
TOKEN_TTL = 60 * 60 * 24 * 30  # 30 天


class PwResetReq(BaseModel):
    new_password: str


class PwChangeReq(BaseModel):
    old_password: str
    new_password: str

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="家庭日常管理平台")


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '家庭事务',
            pinned INTEGER NOT NULL DEFAULT 0,
            author_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            priority TEXT NOT NULL DEFAULT '中',
            status TEXT NOT NULL DEFAULT '想要',
            link TEXT,
            price TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT,
            participants TEXT,
            type TEXT NOT NULL DEFAULT 'event',
            subtype TEXT,
            note TEXT,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shopping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            quantity TEXT,
            category TEXT NOT NULL DEFAULT '其他',
            done INTEGER NOT NULL DEFAULT 0,
            added_by INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '其他',
            ingredients TEXT,
            steps TEXT,
            cover TEXT,
            author_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            event TEXT,
            date TEXT,
            uploader_id INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS luckymoney (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            receiver TEXT NOT NULL,
            giver TEXT,
            amount REAL NOT NULL,
            channel TEXT,
            note TEXT,
            user_id INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(kind, name)
        );
        CREATE TABLE IF NOT EXISTS diaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            date TEXT NOT NULL,
            author_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    cnt = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if cnt == 0:
        create_user(ADMIN_USER, "管理员", "admin", ADMIN_PASS)
    conn.close()


def migrate():
    """增量迁移：为已存在的库补充新列，并种子默认类别。"""
    conn = db_conn()
    c = conn.cursor()
    ncols = [r[1] for r in c.execute("PRAGMA table_info(notices)").fetchall()]
    if "expired_at" not in ncols:
        c.execute("ALTER TABLE notices ADD COLUMN expired_at TEXT")
    if "archived" not in ncols:
        c.execute("ALTER TABLE notices ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    ecols = [r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()]
    for col, d in (("repeat_type", "TEXT NOT NULL DEFAULT 'none'"),
                   ("repeat_until", "TEXT"),
                   ("repeat_count", "INTEGER"),
                   ("exceptions", "TEXT"),
                   ("private", "INTEGER NOT NULL DEFAULT 0")):
        if col not in ecols:
            c.execute("ALTER TABLE events ADD COLUMN {} {}".format(col, d))
    scols = [r[1] for r in c.execute("PRAGMA table_info(shopping)").fetchall()]
    if "private" not in scols:
        c.execute("ALTER TABLE shopping ADD COLUMN private INTEGER NOT NULL DEFAULT 0")
    lcols = [r[1] for r in c.execute("PRAGMA table_info(luckymoney)").fetchall()]
    if "kind" not in lcols:
        c.execute("ALTER TABLE luckymoney ADD COLUMN kind TEXT NOT NULL DEFAULT 'income'")
    rcols = [r[1] for r in c.execute("PRAGMA table_info(recipes)").fetchall()]
    if "content" not in rcols:
        c.execute("ALTER TABLE recipes ADD COLUMN content TEXT")
    dcols = [r[1] for r in c.execute("PRAGMA table_info(diaries)").fetchall()]
    if "private" not in dcols:
        c.execute("ALTER TABLE diaries ADD COLUMN private INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        defaults = [
            ("shopping", "生鲜"), ("shopping", "日用"), ("shopping", "其他"),
            ("anniversary", "生日"), ("anniversary", "结婚纪念日"), ("anniversary", "其他"),
            ("recipe", "荤菜"), ("recipe", "素菜"), ("recipe", "汤"), ("recipe", "甜点"), ("recipe", "其他"),
        ]
        c.executemany("INSERT OR IGNORE INTO categories (kind, name) VALUES (?, ?)", defaults)
        conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 用户 / 密码 / Token
# ---------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}:{dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 100000)
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False


def create_user(username, display_name, role, password):
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO users (username, display_name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
        (username, display_name, role, hash_password(password), now()),
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid


def make_token(uid: int, role: str) -> str:
    payload = json.dumps({"uid": uid, "role": role, "exp": int(time.time()) + TOKEN_TTL}).encode()
    sig = hmac.new(SECRET, payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode() + "." + sig


def verify_token(token: str):
    try:
        raw, sig = token.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(raw)
        expected = hmac.new(SECRET, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(payload)
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth[7:]
    data = verify_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="登录已失效")
    conn = db_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (data["uid"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="用户不存在")
    return dict(row)


def require_role(roles):
    def checker(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="无权限")
        return user

    return checker


# ---------------------------------------------------------------------------
# 启动初始化
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    init_db()
    migrate()


# ---------------------------------------------------------------------------
# 认证接口（登录用 query 参数，与前端一致）
# ---------------------------------------------------------------------------
@app.post("/api/login")
def login(username: str, password: str):
    conn = db_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    u = dict(row)
    return {"token": make_token(u["id"], u["role"]), "user": public_user(u)}


@app.get("/api/me")
def me(user=Depends(get_current_user)):
    return public_user(user)


def public_user(u):
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"],
        "role": u["role"],
    }


# ---------------------------------------------------------------------------
# 用户管理（仅管理员）
# ---------------------------------------------------------------------------
@app.get("/api/users")
def list_users(user=Depends(require_role(["admin"]))):
    conn = db_conn()
    rows = conn.execute("SELECT id, username, display_name, role, created_at FROM users ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/users")
def add_user(username: str = Body(...), display_name: str = Body(...), role: str = Body(...),
             password: str = Body(...), user=Depends(require_role(["admin"]))):
    if role not in ("admin", "member", "guest"):
        raise HTTPException(status_code=400, detail="角色非法")
    conn = db_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, display_name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
            (username, display_name, role, hash_password(password), now()),
        )
        conn.commit()
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="用户名已存在")
    conn.close()
    return {"id": uid, "msg": "创建成功"}


@app.delete("/api/users/{uid}")
def delete_user(uid: int, user=Depends(require_role(["admin"]))):
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    conn = db_conn()
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# 管理员重置某用户密码
@app.post("/api/users/{uid}/reset_password")
def reset_password(uid: int, req: PwResetReq, user=Depends(require_role(["admin"]))):
    new_password = (req.new_password or "").strip()
    if not new_password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    conn = db_conn()
    row = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="用户不存在")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), uid))
    conn.commit()
    conn.close()
    return {"msg": "密码已重置"}


# 用户自己修改密码
@app.post("/api/me/change_password")
def change_password(req: PwChangeReq, user=Depends(get_current_user)):
    new_password = (req.new_password or "").strip()
    if not new_password:
        raise HTTPException(status_code=400, detail="新密码不能为空")
    conn = db_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
    if not verify_password(req.old_password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=400, detail="当前密码错误")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user["id"]))
    conn.commit()
    conn.close()
    return {"msg": "密码已修改"}


# ---------------------------------------------------------------------------
# 公告板（含到期自动归档 + 手工归档）
# ---------------------------------------------------------------------------
@app.get("/api/notices")
def list_notices(user=Depends(get_current_user)):
    conn = db_conn()
    today = date.today().isoformat()
    conn.execute(
        "UPDATE notices SET archived=1 WHERE archived=0 AND expired_at IS NOT NULL AND expired_at < ?",
        (today,),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT n.*, u.display_name AS author FROM notices n LEFT JOIN users u ON n.author_id=u.id "
        "WHERE n.archived=0 ORDER BY pinned DESC, created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/notices/archived")
def list_archived(user=Depends(get_current_user)):
    conn = db_conn()
    rows = conn.execute(
        "SELECT n.*, u.display_name AS author FROM notices n LEFT JOIN users u ON n.author_id=u.id "
        "WHERE n.archived=1 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/notices")
def create_notice(title: str = Body(...), body: str = Body(""), category: str = Body("家庭事务"),
                  pinned: int = Body(0), expired_at: str = Body(None),
                  user=Depends(require_role(["admin", "member"]))):
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO notices (title, body, category, pinned, author_id, created_at, expired_at) VALUES (?,?,?,?,?,?,?)",
        (title, body, category, pinned, user["id"], now(), expired_at),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "msg": "已发布"}


@app.put("/api/notices/{nid}")
def update_notice(nid: int, title: str = Body(None), body: str = Body(None), category: str = Body(None),
                  pinned: int = Body(None), expired_at: str = Body(None),
                  user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["author_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    title = title if title is not None else row["title"]
    body = body if body is not None else row["body"]
    category = category if category is not None else row["category"]
    pinned = pinned if pinned is not None else row["pinned"]
    expired_at = expired_at if expired_at is not None else row["expired_at"]
    conn.execute(
        "UPDATE notices SET title=?, body=?, category=?, pinned=?, expired_at=? WHERE id=?",
        (title, body, category, pinned, expired_at, nid),
    )
    conn.commit()
    conn.close()
    return {"msg": "已更新"}


@app.post("/api/notices/{nid}/archive")
def archive_notice(nid: int, user=Depends(get_current_user)):
    conn = db_conn()
    conn.execute("UPDATE notices SET archived=1 WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    return {"msg": "已归档"}


@app.post("/api/notices/{nid}/unarchive")
def unarchive_notice(nid: int, user=Depends(get_current_user)):
    conn = db_conn()
    conn.execute("UPDATE notices SET archived=0 WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    return {"msg": "已恢复"}


@app.delete("/api/notices/{nid}")
def delete_notice(nid: int, user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["author_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    conn.execute("DELETE FROM notices WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 心愿单
# ---------------------------------------------------------------------------
@app.get("/api/wishes")
def list_wishes(user=Depends(get_current_user)):
    conn = db_conn()
    rows = conn.execute(
        "SELECT w.*, u.display_name AS proposer FROM wishes w LEFT JOIN users u ON w.user_id=u.id ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/wishes")
def create_wish(content: str = Body(...), priority: str = Body("中"), status: str = Body("想要"),
                link: str = Body(None), price: str = Body(None),
                user=Depends(require_role(["admin", "member"]))):
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO wishes (content, user_id, priority, status, link, price, created_at) VALUES (?,?,?,?,?,?,?)",
        (content, user["id"], priority, status, link, price, now()),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "msg": "已添加"}


@app.put("/api/wishes/{wid}")
def update_wish(wid: int, content: str = Body(None), priority: str = Body(None), status: str = Body(None),
                link: str = Body(None), price: str = Body(None), user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    content = content if content is not None else row["content"]
    priority = priority if priority is not None else row["priority"]
    status = status if status is not None else row["status"]
    link = link if link is not None else row["link"]
    price = price if price is not None else row["price"]
    conn.execute(
        "UPDATE wishes SET content=?, priority=?, status=?, link=?, price=? WHERE id=?",
        (content, priority, status, link, price, wid),
    )
    conn.commit()
    conn.close()
    return {"msg": "已更新"}


@app.delete("/api/wishes/{wid}")
def delete_wish(wid: int, user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    conn.execute("DELETE FROM wishes WHERE id=?", (wid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 共享日历（日程） + 纪念日（独立，默认列表只返日程）
# ---------------------------------------------------------------------------
@app.get("/api/events")
def list_events(user=Depends(get_current_user), type: str = None, upcoming_days: int = None):
    conn = db_conn()
    if upcoming_days:
        rows = conn.execute(
            "SELECT * FROM events WHERE type='anniversary' AND date IS NOT NULL ORDER BY date"
        ).fetchall()
        result = []
        for r in rows:
            # 私有纪念日：非拥有者/管理员不可见
            if r["private"] and user["role"] != "admin" and r["user_id"] != user["id"]:
                continue
            d = dict(r)
            d["days_left"] = days_until_anniversary(d["date"])
            if 0 <= d["days_left"] <= upcoming_days:
                result.append(d)
        conn.close()
        return result
    q = "SELECT * FROM events"
    args = []
    if type:
        q += " WHERE type=?"
        args.append(type)
        # 私有纪念日：非拥有者/管理员不可见
        if type == "anniversary" and user["role"] != "admin":
            q += " AND (private=0 OR user_id=?)"
            args.append(user["id"])
    else:
        # 默认只返回普通日程，纪念日不在共享日历中显示
        q += " WHERE type='event'"
    q += " ORDER BY date"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def days_until_anniversary(date_str: str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return 9999
    today = date.today()
    next_occ = d.replace(year=today.year)
    if next_occ < today:
        next_occ = next_occ.replace(year=today.year + 1)
    return (next_occ - today).days


@app.post("/api/events")
def create_event(title: str = Body(...), date: str = Body(...), time: str = Body(None),
                 participants: str = Body(None), type: str = Body("event"), subtype: str = Body(None),
                 note: str = Body(None), repeat_type: str = Body("none"), repeat_until: str = Body(None),
                 repeat_count: int = Body(None), private: int = Body(0),
                 user=Depends(require_role(["admin", "member"]))):
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO events (title, date, time, participants, type, subtype, note, user_id, created_at, "
        "repeat_type, repeat_until, repeat_count, private) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (title, date, time, participants, type, subtype, note, user["id"], now(),
         repeat_type, repeat_until, repeat_count, private),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "msg": "已添加"}


@app.put("/api/events/{eid}")
def update_event(eid: int, title: str = Body(None), date: str = Body(None), time: str = Body(None),
                 participants: str = Body(None), type: str = Body(None), subtype: str = Body(None),
                 note: str = Body(None), repeat_type: str = Body(None), repeat_until: str = Body(None),
                 repeat_count: int = Body(None), user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    title = title if title is not None else row["title"]
    date = date if date is not None else row["date"]
    time = time if time is not None else row["time"]
    participants = participants if participants is not None else row["participants"]
    type = type if type is not None else row["type"]
    subtype = subtype if subtype is not None else row["subtype"]
    note = note if note is not None else row["note"]
    repeat_type = repeat_type if repeat_type is not None else row["repeat_type"]
    repeat_until = repeat_until if repeat_until is not None else row["repeat_until"]
    repeat_count = repeat_count if repeat_count is not None else row["repeat_count"]
    conn.execute(
        "UPDATE events SET title=?, date=?, time=?, participants=?, type=?, subtype=?, note=?, "
        "repeat_type=?, repeat_until=?, repeat_count=? WHERE id=?",
        (title, date, time, participants, type, subtype, note, repeat_type, repeat_until, repeat_count, eid),
    )
    conn.commit()
    conn.close()
    return {"msg": "已更新"}


@app.delete("/api/events/{eid}")
def delete_event(eid: int, user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    conn.execute("DELETE FROM events WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


@app.post("/api/events/{eid}/exclude")
def exclude_event(eid: int, date: str = Body(..., embed=True), user=Depends(get_current_user)):
    """单条删除：把某一天从该重复日程中排除（不影响其余日期）。"""
    conn = db_conn()
    row = conn.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    ex = (row["exceptions"] or "")
    dates = [x for x in ex.split(",") if x]
    if date not in dates:
        dates.append(date)
    conn.execute("UPDATE events SET exceptions=? WHERE id=?", (",".join(dates), eid))
    conn.commit()
    conn.close()
    return {"msg": "已删除该条", "exceptions": dates}


# ---------------------------------------------------------------------------
# 购物清单（全员协作）
# ---------------------------------------------------------------------------
@app.get("/api/shopping")
def list_shopping(user=Depends(get_current_user), done: int = None, category: str = None):
    conn = db_conn()
    q = "SELECT s.*, u.display_name AS added_by_name FROM shopping s LEFT JOIN users u ON s.added_by=u.id WHERE 1=1"
    args = []
    # 私有物品：仅拥有者与管理员可见
    if user["role"] != "admin":
        q += " AND (s.private=0 OR s.added_by=?)"
        args.append(user["id"])
    if done is not None:
        q += " AND done=?"
        args.append(done)
    if category:
        q += " AND category=?"
        args.append(category)
    q += " ORDER BY done ASC, created_at DESC"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/shopping")
def create_shopping(name: str = Body(...), quantity: str = Body(None), category: str = Body("其他"),
                    private: int = Body(0), user=Depends(require_role(["admin", "member"]))):
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO shopping (name, quantity, category, done, added_by, created_at, private) VALUES (?,?,?,0,?,?,?)",
        (name, quantity, category, user["id"], now(), private),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "msg": "已添加"}


@app.patch("/api/shopping/{sid}")
def toggle_shopping(sid: int, done: int = None, user=Depends(require_role(["admin", "member"]))):
    conn = db_conn()
    row = conn.execute("SELECT * FROM shopping WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    # 私有物品：仅拥有者与管理员可操作
    if row["private"] and user["role"] != "admin" and row["added_by"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    if done is None:
        done = 0 if row["done"] else 1
    conn.execute("UPDATE shopping SET done=? WHERE id=?", (done, sid))
    conn.commit()
    conn.close()
    return {"msg": "已更新", "done": done}


@app.delete("/api/shopping/{sid}")
def delete_shopping(sid: int, user=Depends(require_role(["admin", "member"]))):
    conn = db_conn()
    row = conn.execute("SELECT * FROM shopping WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if row["private"] and user["role"] != "admin" and row["added_by"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    conn.execute("DELETE FROM shopping WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 食谱文档（支持 Markdown 正文 + 图片自动上传）
# ---------------------------------------------------------------------------
@app.get("/api/recipes")
def list_recipes(user=Depends(get_current_user), category: str = None):
    conn = db_conn()
    q = "SELECT r.*, u.display_name AS author FROM recipes r LEFT JOIN users u ON r.author_id=u.id WHERE 1=1"
    args = []
    if category:
        q += " AND category=?"
        args.append(category)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/recipes")
def create_recipe(name: str = Body(...), category: str = Body("其他"), ingredients: str = Body(None),
                  steps: str = Body(None), cover: str = Body(None), content: str = Body(None),
                  user=Depends(require_role(["admin", "member"]))):
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO recipes (name, category, ingredients, steps, cover, author_id, created_at, content) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (name, category, ingredients, steps, cover, user["id"], now(), content),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "msg": "已添加"}


@app.put("/api/recipes/{rid}")
def update_recipe(rid: int, name: str = Body(None), category: str = Body(None), ingredients: str = Body(None),
                  steps: str = Body(None), cover: str = Body(None), content: str = Body(None),
                  user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["author_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    name = name if name is not None else row["name"]
    category = category if category is not None else row["category"]
    ingredients = ingredients if ingredients is not None else row["ingredients"]
    steps = steps if steps is not None else row["steps"]
    cover = cover if cover is not None else row["cover"]
    content = content if content is not None else row["content"]
    conn.execute(
        "UPDATE recipes SET name=?, category=?, ingredients=?, steps=?, cover=?, content=? WHERE id=?",
        (name, category, ingredients, steps, cover, content, rid),
    )
    conn.commit()
    conn.close()
    return {"msg": "已更新"}


@app.delete("/api/recipes/{rid}")
def delete_recipe(rid: int, user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["author_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    if row["cover"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(row["cover"])))
        except Exception:
            pass
    conn.execute("DELETE FROM recipes WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 日记本（Markdown 书写 / 查看）
# ---------------------------------------------------------------------------
@app.get("/api/diaries")
def list_diaries(user=Depends(get_current_user), date: str = None):
    conn = db_conn()
    # 私密日记仅作者本人可见（即使管理员也看不到）
    q = ("SELECT d.*, u.display_name AS author FROM diaries d "
         "LEFT JOIN users u ON d.author_id=u.id WHERE (d.private=0 OR d.author_id=?)")
    args = [user["id"]]
    if date:
        q += " AND date=?"
        args.append(date)
    q += " ORDER BY date DESC, created_at DESC"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/diaries")
def create_diary(title: str = Body(...), date: str = None, content: str = Body(None),
                 private: int = Body(0), user=Depends(require_role(["admin", "member"]))):
    if not date:
        date = datetime.now().date().isoformat()
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO diaries (title, content, date, author_id, created_at, private) VALUES (?,?,?,?,?,?)",
        (title, content, date, user["id"], now(), private),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "msg": "已保存"}


@app.put("/api/diaries/{did}")
def update_diary(did: int, title: str = Body(None), content: str = Body(None), date: str = Body(None),
                 private: int = Body(None), user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM diaries WHERE id=?", (did,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    # 日记仅作者可改（私密对管理员也不可见、不可改）
    if row["author_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    title = title if title is not None else row["title"]
    content = content if content is not None else row["content"]
    date = date if date is not None else row["date"]
    private = private if private is not None else row["private"]
    conn.execute(
        "UPDATE diaries SET title=?, content=?, date=?, private=? WHERE id=?",
        (title, content, date, private, did),
    )
    conn.commit()
    conn.close()
    return {"msg": "已更新"}


@app.delete("/api/diaries/{did}")
def delete_diary(did: int, user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM diaries WHERE id=?", (did,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if row["author_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    conn.execute("DELETE FROM diaries WHERE id=?", (did,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 类别管理（仅管理员）：购物类别 / 纪念日类别 / 食谱菜类
# ---------------------------------------------------------------------------
@app.get("/api/categories")
def list_categories(kind: str = None, user=Depends(get_current_user)):
    conn = db_conn()
    q = "SELECT * FROM categories"
    args = []
    if kind:
        q += " WHERE kind=?"
        args.append(kind)
    q += " ORDER BY id"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/categories")
def add_category(kind: str = Body(...), name: str = Body(...), user=Depends(require_role(["admin"]))):
    if kind not in ("shopping", "anniversary", "recipe"):
        raise HTTPException(status_code=400, detail="类型非法")
    conn = db_conn()
    try:
        cur = conn.execute("INSERT INTO categories (kind, name) VALUES (?, ?)", (kind, name))
        conn.commit()
        cid = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="该类别已存在")
    conn.close()
    return {"id": cid, "msg": "已添加"}


@app.delete("/api/categories/{cid}")
def delete_category(cid: int, user=Depends(require_role(["admin"]))):
    conn = db_conn()
    conn.execute("DELETE FROM categories WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 通用图片上传（食谱粘贴图片等），返回可访问 URL
# ---------------------------------------------------------------------------
@app.post("/api/upload_image")
def upload_image(file: UploadFile = File(...), user=Depends(require_role(["admin", "member"]))):
    ext = os.path.splitext(file.filename or "")[1][:20]
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        raise HTTPException(status_code=400, detail="仅支持图片")
    fname = f"{secrets.token_hex(12)}{ext}"
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        f.write(file.file.read())
    return {"url": "/api/uploads/" + fname, "msg": "已上传"}


@app.post("/api/upload_image_url")
def upload_image_url(url: str = Body(..., embed=True), user=Depends(require_role(["admin", "member"]))):
    """从外链地址下载图片并保存为本地资源（用于复制网页内容时内嵌的外链图片）。"""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="仅支持 http/https 图片地址")
    # 基础防护：拒绝指向内网/本机的地址，避免被当作 SSRF 工具
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        info = socket.getaddrinfo(host, None)
        for ip in (i[4][0] for i in info):
            addr = ipaddress.ip_address(ip.split("%")[0])
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise HTTPException(status_code=400, detail="不允许的内网地址")
    except HTTPException:
        raise
    except Exception:
        pass  # 解析失败时不阻断，交由实际请求判断
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (family-platform)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
        if not ctype.startswith("image/"):
            raise HTTPException(status_code=400, detail="该地址不是图片")
        ext = ".jpg"
        if "png" in ctype:
            ext = ".png"
        elif "gif" in ctype:
            ext = ".gif"
        elif "webp" in ctype:
            ext = ".webp"
        elif "bmp" in ctype:
            ext = ".bmp"
        fname = f"{secrets.token_hex(12)}{ext}"
        with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
            f.write(data)
        return {"url": "/api/uploads/" + fname, "msg": "已上传"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="图片获取失败：" + str(e))


# ---------------------------------------------------------------------------
# 家庭相册（图片上传）
# ---------------------------------------------------------------------------
@app.post("/api/photos")
def upload_photo(event: str = Form(""), date: str = Form(None), description: str = Form(""),
                 file: UploadFile = File(...), user=Depends(require_role(["admin", "member"]))):
    # 主题为必填项；日期缺省时默认当天
    if not event or not event.strip():
        raise HTTPException(status_code=400, detail="主题为必填项")
    if not date:
        date = datetime.now().date().isoformat()
    ext = os.path.splitext(file.filename or "")[1][:20]
    fname = f"{secrets.token_hex(12)}{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(file.file.read())
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO photos (path, event, date, uploader_id, description, created_at) VALUES (?,?,?,?,?,?)",
        (fname, event, date, user["id"], description, now()),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "path": fname, "msg": "已上传"}


@app.get("/api/photos")
def list_photos(user=Depends(get_current_user)):
    conn = db_conn()
    rows = conn.execute(
        "SELECT p.*, u.display_name AS uploader FROM photos p LEFT JOIN users u ON p.uploader_id=u.id ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/uploads/{fname}")
def get_photo(fname: str):
    # 图片为静态资源，允许公开读取（与 /static 一致），以便前端 <img> 直接加载
    return FileResponse(os.path.join(UPLOAD_DIR, fname))


@app.delete("/api/photos/{pid}")
def delete_photo(pid: int, user=Depends(get_current_user)):
    conn = db_conn()
    row = conn.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="不存在")
    if user["role"] != "admin" and row["uploader_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="无权限")
    try:
        os.remove(os.path.join(UPLOAD_DIR, os.path.basename(row["path"])))
    except Exception:
        pass
    conn.execute("DELETE FROM photos WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 压岁钱记账（收入 / 使用，去掉渠道）
# ---------------------------------------------------------------------------
@app.get("/api/luckymoney")
def list_luckymoney(user=Depends(get_current_user), year: int = None):
    conn = db_conn()
    q = "SELECT * FROM luckymoney WHERE 1=1"
    args = []
    if year:
        q += " AND year=?"
        args.append(year)
    q += " ORDER BY year DESC, created_at DESC"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/luckymoney/summary")
def luckymoney_summary(user=Depends(get_current_user), year: int = None):
    conn = db_conn()
    cond = "WHERE 1=1"
    args = []
    if year:
        cond += " AND year=?"
        args.append(year)
    income = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) FROM luckymoney {cond} AND kind='income'", args
    ).fetchone()[0]
    expense = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) FROM luckymoney {cond} AND kind='expense'", args
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT receiver, SUM(amount) AS total FROM luckymoney {cond} AND kind='income' GROUP BY receiver",
        args,
    ).fetchall()
    by_person = [dict(r) for r in rows]
    years = conn.execute("SELECT DISTINCT year FROM luckymoney ORDER BY year DESC").fetchall()
    conn.close()
    return {
        "by_person": by_person,
        "total_income": income,
        "total_expense": expense,
        "balance": income - expense,
        "years": [y["year"] for y in years],
    }


@app.post("/api/luckymoney")
def create_luckymoney(year: int = Body(...), receiver: str = Body(...), amount: float = Body(...),
                      giver: str = Body(None), kind: str = Body("income"), note: str = Body(None),
                      user=Depends(require_role(["admin", "member"]))):
    if kind not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="类型非法")
    conn = db_conn()
    cur = conn.execute(
        "INSERT INTO luckymoney (year, receiver, giver, amount, kind, note, user_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (year, receiver, giver, amount, kind, note, user["id"], now()),
    )
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid, "msg": "已记录"}


@app.delete("/api/luckymoney/{mid}")
def delete_luckymoney(mid: int, user=Depends(require_role(["admin"]))):
    conn = db_conn()
    conn.execute("DELETE FROM luckymoney WHERE id=?", (mid,))
    conn.commit()
    conn.close()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 静态前端
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
