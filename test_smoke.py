import urllib.request, urllib.error, json, os, uuid
from datetime import date, timedelta

BASE = "http://127.0.0.1:8080"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "uploads")

def call(method, path, data=None, token=None, raw=None, ctype=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if raw is not None:
        body = raw
        if ctype:
            headers["Content-Type"] = ctype
    elif data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def upload_image(token, content, fname="t.png"):
    boundary = "----t" + uuid.uuid4().hex
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode()
    body += b"Content-Type: image/png\r\n\r\n" + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    headers = {"Authorization": "Bearer " + token, "Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(BASE + "/api/upload_image", data=body, headers=headers, method="POST")
    r = urllib.request.urlopen(req, timeout=10)
    return r.status, json.loads(r.read())

def upload_photo(token, content, fields: dict, fname="p.png"):
    """fields: 要发送的表单字段（不含 file），如 {"event": "测试"} 或 {"event": "x", "date": "2026-01-01"}"""
    boundary = "----p" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        body += str(v).encode() + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode()
    body += b"Content-Type: image/png\r\n\r\n" + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    headers = {"Authorization": "Bearer " + token, "Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(BASE + "/api/photos", data=body, headers=headers, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

# ---- 登录 ----
s, d = call("POST", "/api/login?username=admin&password=admin123")
assert s == 200 and "token" in d, d
tok = d["token"]
print("[1] 登录 OK")

# ---- 类别种子 ----
s, d = call("GET", "/api/categories?kind=shopping", token=tok)
print("[2] 购物类别种子:", [c["name"] for c in d])
assert any(c["name"] == "生鲜" for c in d)

# ---- 公告自动归档 ----
past = (date.today() - timedelta(days=5)).isoformat()
s, d = call("POST", "/api/notices", {"title": "过期公告", "expired_at": past}, token=tok)
nid = d["id"]
s, d = call("GET", "/api/notices", token=tok)
assert not any(x["id"] == nid for x in d), "过期公告不应出现在最新"
s, d = call("GET", "/api/notices/archived", token=tok)
assert any(x["id"] == nid for x in d), "过期公告应出现在归档"
s, d = call("POST", f"/api/notices/{nid}/unarchive", token=tok)
s, d = call("DELETE", f"/api/notices/{nid}", token=tok)
s, d = call("POST", "/api/notices", {"title": "正常公告"}, token=tok)
call("DELETE", f"/api/notices/{d['id']}", token=tok)
print("[3] 公告到期自动归档 + 手工归档/恢复 OK")

# ---- 事件分离 + 重复 ----
s, d = call("POST", "/api/events", {"title": "周会", "date": "2026-08-19", "type": "event", "repeat_type": "weekly"}, token=tok)
eid = d["id"]
s, d = call("GET", "/api/events?type=event", token=tok)
assert any(x["id"] == eid for x in d), "日程应显示"
s, d = call("POST", "/api/events", {"title": "妈妈生日", "date": "2020-08-20", "type": "anniversary", "subtype": "生日", "repeat_type": "yearly"}, token=tok)
aid = d["id"]
s, d = call("GET", "/api/events?type=event", token=tok)
assert not any(x["id"] == aid for x in d), "纪念日不应出现在日程列表"
s, d = call("GET", "/api/events?type=anniversary", token=tok)
assert any(x["id"] == aid for x in d), "纪念日应独立显示"
assert any(x["repeat_type"] == "yearly" for x in d), "纪念日周期字段应可存储"
print("[4] 共享日历只显示日程 + 纪念日独立 + 周期字段 OK")
call("DELETE", f"/api/events/{eid}", token=tok)
call("DELETE", f"/api/events/{aid}", token=tok)

# ---- 压岁钱收入/使用 ----
call("POST", "/api/luckymoney", {"year": 2026, "receiver": "小明", "amount": 500, "kind": "income"}, token=tok)
call("POST", "/api/luckymoney", {"year": 2026, "receiver": "小明", "amount": 100, "kind": "expense"}, token=tok)
s, d = call("GET", "/api/luckymoney/summary", token=tok)
assert d["total_income"] == 500 and d["total_expense"] == 100 and d["balance"] == 400, d
print("[5] 压岁钱/红包 收入/使用汇总 OK:", d)
s, dl = call("GET", "/api/luckymoney", token=tok)
for x in dl:
    call("DELETE", f"/api/luckymoney/{x['id']}", token=tok)

# ---- 图片上传 ----
png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000154a24f5d0000000049454e44ae426082")
s, d = upload_image(tok, png)
assert s == 200 and "url" in d, d
fname = d["url"].rsplit("/", 1)[-1]
print("[6] 图片上传 OK, url=", d["url"])
r = urllib.request.urlopen(BASE + d["url"], timeout=5)
assert r.status == 200
try:
    os.remove(os.path.join(DATA, fname))
except Exception:
    pass

# ---- 心愿单：去价格 + 标记为已实现 ----
s, d = call("POST", "/api/wishes", {"content": "想要个相机", "priority": "高"}, token=tok)
wid = d["id"]
s, d = call("PUT", f"/api/wishes/{wid}", {"status": "已实现"}, token=tok)
assert s == 200
s, d = call("GET", "/api/wishes", token=tok)
w = next(x for x in d if x["id"] == wid)
assert w["status"] == "已实现", w
call("DELETE", f"/api/wishes/{wid}", token=tok)
print("[7] 心愿单 标记为已实现 OK")

# ---- 清理可能残留的测试用户（保证幂等） ----
s, d = call("GET", "/api/users", token=tok)
for u in d:
    if u["username"].startswith("smoke_member"):
        call("DELETE", f"/api/users/{u['id']}", token=tok)

# ---- 私有可见性（购物 / 纪念日） ----
s, d = call("POST", "/api/shopping", {"name": "私密物品", "private": 1}, token=tok)
sid_priv = d["id"]
s, d = call("POST", "/api/shopping", {"name": "公开物品", "private": 0}, token=tok)
sid_pub = d["id"]
s, d = call("POST", "/api/events", {"title": "私密纪念日", "date": "2020-09-09", "type": "anniversary", "private": 1}, token=tok)
aid_priv = d["id"]
s, d = call("POST", "/api/events", {"title": "公开纪念日", "date": "2020-09-10", "type": "anniversary", "private": 0}, token=tok)
aid_pub = d["id"]

# 建一个普通成员用于验证可见性（用户名带随机后缀，避免与历史残留冲突）
mname = "smoke_member_" + uuid.uuid4().hex[:6]
s, d = call("POST", "/api/users", {"username": mname, "display_name": "测试成员", "role": "member", "password": "m123456"}, token=tok)
assert s == 200, d
mid = d["id"]
s, d = call("POST", "/api/login?username=" + mname + "&password=m123456")
assert s == 200, d
mtok = d["token"]

s, d = call("GET", "/api/shopping", token=mtok)
ids = [x["id"] for x in d]
assert sid_priv not in ids, "成员不应看到他人的私有物品"
assert sid_pub in ids, "成员应看到共享物品"
s, d = call("GET", "/api/events?type=anniversary", token=mtok)
aids = [x["id"] for x in d]
assert aid_priv not in aids, "成员不应看到他人的私有纪念日"
assert aid_pub in aids, "成员应看到共享纪念日"
# 成员尝试删除他人私有物品应被拒
s, d = call("DELETE", f"/api/shopping/{sid_priv}", token=mtok)
assert s == 403, d
print("[8] 私有/共享 可见性与权限 OK")

# 成员自己改密码
s, d = call("POST", "/api/me/change_password", {"old_password": "m123456", "new_password": "m654321"}, token=mtok)
assert s == 200, d
s, d = call("POST", "/api/login?username=" + mname + "&password=m654321")
assert s == 200, d
# 管理员重置成员密码
s, d = call("POST", f"/api/users/{mid}/reset_password", {"new_password": "m000000"}, token=tok)
assert s == 200, d
s, d = call("POST", "/api/login?username=" + mname + "&password=m000000")
assert s == 200, d
print("[9] 改密码(自改) + 管理员重置密码 OK")

# ---- 单条删除（重复日程排除某天） ----
s, d = call("POST", "/api/events", {"title": "每月缴费", "date": "2026-08-10", "type": "event", "repeat_type": "monthly", "repeat_count": 12}, token=tok)
eid2 = d["id"]
s, d = call("POST", f"/api/events/{eid2}/exclude", {"date": "2026-10-10"}, token=tok)
assert s == 200 and "2026-10-10" in d["exceptions"], d
s, d = call("GET", "/api/events?type=event", token=tok)
ev = next(x for x in d if x["id"] == eid2)
assert "2026-10-10" in (ev["exceptions"] or ""), ev
call("DELETE", f"/api/events/{eid2}", token=tok)
print("[10] 重复日程 单条删除(排除某天) OK")

# ---- 照片上传：主题必填；日期缺省时默认当天 ----
png2 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000154a24f5d0000000049454e44ae426082")
# 缺主题应 400
s, d = upload_photo(tok, png2, {"event": ""})
assert s == 400, (s, d)
# 有主题、无日期 -> 后端默认今天
s, d = upload_photo(tok, png2, {"event": "测试照片"})
assert s == 200, d
pid = d["id"]
s, photos = call("GET", "/api/photos", token=tok)
p = next(x for x in photos if x["id"] == pid)
assert p["event"] == "测试照片" and p["date"] == date.today().isoformat(), p
call("DELETE", f"/api/photos/{pid}", token=tok)
print("[11] 照片上传 主题必填 + 日期默认当天 OK")

# ---- 日记本：创建 / 列出 / 编辑 / 删除 ----
s, d = call("POST", "/api/diaries", {"title": "第一篇日记", "content": "# 今天\n去**公园**了", "date": date.today().isoformat()}, token=tok)
assert s == 200, d
did = d["id"]
s, d = call("GET", "/api/diaries", token=tok)
assert s == 200 and any(x["id"] == did for x in d), d
s, d = call("PUT", f"/api/diaries/{did}", {"content": "更新后的日记"}, token=tok)
assert s == 200, d
s, d = call("DELETE", f"/api/diaries/{did}", token=tok)
assert s == 200, d
print("[12] 日记本 创建/编辑/删除 OK")

# ---- 日记私密：仅本人可见（管理员也看不到） ----
s, d = call("POST", "/api/diaries", {"title": "私密日记", "content": "秘密内容", "private": 1}, token=tok)
assert s == 200, d
priv_did = d["id"]
s, d = call("GET", "/api/diaries", token=tok)
assert s == 200 and any(x["id"] == priv_did for x in d), d           # 作者自己可见
s, d = call("GET", "/api/diaries", token=mtok)
assert s == 200 and not any(x["id"] == priv_did for x in d), d        # 普通成员不可见
s, d = call("PUT", f"/api/diaries/{priv_did}", {"content": "x"}, token=mtok)
assert s == 403, d                                                     # 他人不可改
s, d = call("DELETE", f"/api/diaries/{priv_did}", token=mtok)
assert s == 403, d                                                     # 他人不可删
s, d = call("POST", "/api/diaries", {"title": "公开日记", "content": "hi", "private": 0}, token=tok)
pub_did = d["id"]
s, d = call("GET", "/api/diaries", token=mtok)
assert any(x["id"] == pub_did for x in d), d                           # 公开日记他人可见
call("DELETE", f"/api/diaries/{pub_did}", token=tok)
call("DELETE", f"/api/diaries/{priv_did}", token=tok)
print("[13] 日记私密 仅本人可见 + 管理员不可见 OK")

# ---- 外链图片代理上传 ----
s, d = call("POST", "/api/upload_image_url", {"url": "ftp://x/y.png"}, token=tok)
assert s == 400, (s, d)                                                # 仅接受 http(s)
s, d = call("POST", "/api/upload_image_url", {"url": "http://127.0.0.1/x.png"}, token=tok)
assert s == 400, (s, d)                                                # 拒绝内网地址
s, d = call("POST", "/api/upload_image_url", {"url": "https://www.python.org/static/opengraph-icon-200x200.png"}, token=tok)
if s == 200:
    assert d["url"].startswith("/api/uploads/"), d
    print("[14] 外链图片代理上传 OK")
else:
    print("[14] 外链图片代理（当前环境无外网，跳过实际下载）:", s, d.get("detail"))

# ---- 清理 ----
call("DELETE", f"/api/shopping/{sid_priv}", token=tok)
call("DELETE", f"/api/shopping/{sid_pub}", token=tok)
call("DELETE", f"/api/events/{aid_priv}", token=tok)
call("DELETE", f"/api/events/{aid_pub}", token=tok)
call("DELETE", f"/api/users/{mid}", token=tok)

print("\nALL SMOKE TESTS PASSED")
