# LimeSlake-01 · 石灰熟化池作业板

厂区熟化池平面图作业基线（Flask + Jinja + Stimulus）。主界面是按厂区排布的池位瓦片，点选后在右侧抽屉登记峰值温度并改状态——不是侧栏双列表 CRUD。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web | Flask 3 · Blueprints · Flask-Login · Jinja2 · Stimulus CDN |
| 数据 | SQLAlchemy · PostgreSQL 15 |
| 部署 | Docker Compose · Gunicorn |

## 路径与端口

- **项目路径**：`d:\work\document\bytecode\claudeCodePro\LimeSlake\LimeSlake-01`
- **Web**：http://localhost:4730
- **PostgreSQL**：localhost:6130

## 演示账号

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `123456` | 管理员 |
| `worker` | `123456` | 操作工 |

登录页已预填 `admin` / `123456`。启动时 entrypoint 会建表并写入种子数据（示范厂区：**东湾石灰厂**）。

## 主界面

- **熟化池平面图**（`/board/`）：CSS 网格池位瓦片，按状态着色（注水中 / 熟化中 / 已出灰）
- 顶部厂区切换芯片（多厂时切换）
- 点击瓦片 → 右侧抽屉展示最近 `SlakeBatch`，可登记峰值温度并变更池状态
- 主导航不再挂「熟化池列表 / 批次列表」；旧 `/ponds/`、`/batches/` 路由仍保留但不作为作业入口

## 业务规则

熟化池状态不可设为「已出灰」（`drawn`），除非该池**最近一条** `SlakeBatch` 的 `peakTempC` 已记录且 **≥ 60℃**。

**厂区峰值上限**：在顶栏「峰值上限」专页（`/plants/peak-caps`）按厂区配置允许写入的最高峰值摄氏度并可启停。

- 启用后，抽屉登记/修正峰值、批次登记、批次编辑三条写入链路统一在服务端校验，超过上限即返回中文错误且**不入库**；停用（或上限留空）则不拦截。
- 该上限只管写入，**不替代**出灰须 ≥ 60℃ 的旧门槛；历史遗留的超限旧值也不阻塞只改状态/出灰。
- 同一熟化班几乎同时被两人改峰值时，凭 `slake_batches.version` 乐观锁只放一版入库；最终入库值再以 SQL 条件兜底，不可能超过提交时的现行上限。

规则实现：`app/services/rules.py`；旧库补列：`app/services/schema.py`（启动幂等 `ADD COLUMN`）。

## 快速启动

```bash
cd d:\work\document\bytecode\claudeCodePro\LimeSlake\LimeSlake-01
docker compose up --build
```

浏览器打开 http://localhost:4730

停止：

```bash
docker compose down
```

## 目录结构

```
LimeSlake-01/
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── wsgi.py
├── app/
│   ├── __init__.py          # 工厂 + seed
│   ├── models.py
│   ├── services/rules.py
│   └── blueprints/{auth,board,ponds,batches}
├── templates/
│   └── board/floor.html     # 平面图 + 抽屉
└── static/
```
