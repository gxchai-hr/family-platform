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
uvicorn main:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```
> 说明：本项目没有 `python main.py` 入口，请用 `uvicorn main:app` 启动（与 Docker 内一致）。
默认管理员：用户名 `admin` / 密码 `admin123`（在 docker-compose 或环境变量中修改）。

## 在 QNAP 上部署
> 代码已推到 GitHub：`https://github.com/gxchai-hr/family-platform`（私有仓库）。
> 部署的本质是：在 NAS 上用 Docker 把这个项目跑起来，并把 `data/` 挂到持久化卷上。

### 方式一：Container Station 图形界面（推荐新手）
1. QNAP 应用中心安装并打开 **Container Station**。
2. 把整个 `family-platform` 文件夹传到 NAS 共享目录，例如 `/share/Container/family-platform`
   （可用 File Station 上传，或 SSH 后用 `git clone` 拉取：
   `git clone https://github.com/gxchai-hr/family-platform.git /share/Container/family-platform`）。
3. 进 **Container Station → 创建 → 浏览**，定位到该目录的 `docker-compose.yml`，点击创建。
4. 创建前在「环境 / 高级设置」里修改：
   - 端口映射：左（容器）`8000` → 右（NAS 对外）`8080`（可改，访问地址即 `http://<NAS的IP>:8080`）。
   - `APP_SECRET`：改成一段随机长字符串（重要，关乎登录令牌安全）。
   - `ADMIN_PASS`：改成强密码。
5. 启动后浏览器访问 `http://<NAS的IP>:8080`，用管理员登录，在「用户管理」里创建家庭成员账号。

### 方式二：SSH 命令行
```bash
# 1) 登录 NAS（终端/PowerShell）：ssh admin@<NAS的IP>
# 2) 拉取代码
git clone https://github.com/gxchai-hr/family-platform.git /share/Container/family-platform
cd /share/Container/family-platform

# 3) 改密钥与密码（编辑 docker-compose.yml 的 environment 两项）
#    APP_SECRET / ADMIN_PASS

# 4) 构建并后台启动
docker compose up -d --build
# 查看日志：docker compose logs -f
# 停止：     docker compose down
```
访问 `http://<NAS的IP>:8080`。

### 注意事项
- 镜像基于 `python:3.12-slim`，首次 `up` 会在 NAS 上拉取并构建，取决于网速，请耐心等待。
- `data/` 已挂载为卷（`./data:/app/data`），数据库与上传图片都持久化在这里；**迁移 / 重装时备份此目录即可**。
- 若 NAS 已占用 8080，改 `docker-compose.yml` 左侧对外端口（如 `8090:8000`）。

## 安全建议（局域网外也要留意）
- 务必改写 `APP_SECRET` 与默认管理员密码。
- 同网段设备理论可嗅探，建议在内网加一层 HTTPS（反向代理 / 自签证书）。
- 可在 NAS 防火墙 / 路由器限制来源网段，仅允许家庭子网访问。
- `data/` 目录即全部数据，可定期备份该目录（rsync / 外接硬盘均可）。
