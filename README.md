# 家庭日常管理平台（FamilyHub）

面向家庭、部署在 NAS（QNAP 等支持 Docker 的设备）上的轻量管理平台。全家人通过浏览器访问，每位成员有独立账号与权限。

## 功能
- **公告板**：发布/置顶/分类通知（家庭事务、缴费、提醒等）。
- **心愿单**：记录心愿，标记优先级与状态（想要 / 已购 / 已放弃）。
- **共享日历**：家庭日程；**纪念日**（生日 / 结婚 / 其他）自动算倒计时。
- **购物清单**：全家协作，勾选完成、按分类筛选。
- **食谱文档**：家庭菜谱库（分类、食材、步骤、封面）。
- **家庭相册**：上传照片，按事件/日期归类。
- **压岁钱记账**：按年份、按收款人汇总。
- **用户与权限**：管理员 / 家庭成员 / 访客 三级权限。

## 技术栈
后端 FastAPI + SQLite（仅标准库做密码哈希与签名），前端原生 HTML/JS 单页应用。单容器部署，数据落在持久化卷。

## 目录结构
```
family-platform/
├── main.py            # 后端（API + 静态托管）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── static/            # 前端（index.html / app.js / style.css）
└── data/             # 运行时生成：app.db + uploads/（挂载到持久化卷）
```

## 本地运行（开发）
```bash
pip install -r requirements.txt
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```
默认管理员：用户名 `admin` / 密码 `admin123`（在 docker-compose 或环境变量中修改）。

## 在 QNAP 上部署
1. QNAP 安装并打开 **Container Station**。
2. 把整个 `family-platform` 文件夹上传到 NAS 的某个共享目录（例如 `/share/Container/family-platform`）。
3. 在该目录创建 `docker-compose.yml`（已提供），按需修改：
   - `ports`：对外端口，例如 `8080:8000`，访问地址 `http://<NAS的IP>:8080`。
   - `environment.APP_SECRET`：改成一段随机长字符串（重要，关乎登录安全）。
   - `environment.ADMIN_PASS`：改成强密码。
4. Container Station 中「创建」→ 选择 docker-compose，或命令行：
   ```bash
   docker compose up -d
   ```
5. 浏览器访问 `http://<NAS的IP>:8080`，用管理员登录后在「用户管理」里创建家庭成员账号。

## 安全建议（局域网外也要留意）
- 务必改写 `APP_SECRET` 与默认管理员密码。
- 同网段设备理论可嗅探，建议在内网加一层 HTTPS（反向代理 / 自签证书）。
- 可在 NAS 防火墙限制来源网段，仅允许家庭子网访问。
- `data/` 目录即全部数据，可定期备份该目录。
