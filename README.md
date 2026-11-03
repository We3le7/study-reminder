# 进度条 · 每日学习提醒机器人

每天北京时间 **09:00**，把「今天该学什么 + 对应资料」推送到飞书私聊。

- 内容层：`plan.json`（24 周课程表 + 5 天预备期）
- 通道层：飞书自建应用私聊
- 触发层：GitHub Actions（不依赖本机开机）

> 这是一个面向「数据平台开发者」的 24 周学习计划，配合每日推送把长期目标拆成「今天只做这一件」。

---

## 一、准备飞书自建应用（约 5 分钟）

1. 打开 [open.feishu.cn](https://open.feishu.cn/app) → **创建企业自建应用**
2. **凭证与基础信息** → 记下 `App ID` 和 `App Secret`
3. **添加应用能力** → 勾选 **机器人**
4. **权限管理** → 开通 `im:message:send_as_bot`（以应用身份发消息）
5. **版本管理与发布** → 创建版本并发布；**可用范围**必须包含你自己
6. 在飞书里**主动搜一次这个机器人并发条消息**，建立会话（否则可能收不到私聊）

### 如何拿到 union_id

私聊需要 `receive_id`。**用 `union_id`，不要用 `open_id`** —— open_id 是绑定应用的，换应用就失效。

拿到自己 union_id 的两种方式：

**方式 A：用 lark-cli（最简单）**

```bash
lark-cli contact +get-user --as user
# 返回体里的 union_id 字段即可
```

**方式 B：从事件回调里取**

把机器人加进任意群，在群里 @ 一次机器人，查看开放平台「事件与回调」的推送内容，`sender.sender_id.union_id` 就是。

---

## 二、本地先跑通（约 2 分钟）

```bash
cd study-reminder

# 1. 准备环境变量
cp .env.example .env
vi .env            # 填入 App ID / App Secret / union_id（.env 已被 .gitignore 忽略）
source .env

# 2. 看看今天会发什么（不发送）
python3 remind.py --dry-run

# 3. 指定日期试跑
python3 remind.py --dry-run --date 2026-11-11
python3 remind.py --dry-run --date 2026-11-14   # 周末任务

# 4. 真发一条（会在飞书私聊你）
python3 remind.py
```

收到卡片 = 通道打通。**这一步不通，别急着上 GitHub。**

---

## 三、部署到 GitHub Actions

### 1. 推到 GitHub

```bash
git init
git add .
git commit -m "init"
git remote add origin git@github.com:<你的用户名>/study-reminder.git
git push -u origin main
```

### 2. 配置 Secrets

仓库 **Settings** → **Secrets and variables** → **Actions** → **New repository secret**：

| Name | 说明 |
|---|---|
| `FEISHU_APP_ID` | 你的 App ID |
| `FEISHU_APP_SECRET` | 你的 App Secret |
| `FEISHU_RECEIVE_ID` | 你的 union_id |

> `FEISHU_RECEIVE_ID_TYPE` 已在 workflow 里固定为 `union_id`，无需配置。

### 3. 验证与补发

```bash
# 手动触发（今天）
gh workflow run "每日学习提醒"

# 指定日期补发或试跑
gh workflow run "每日学习提醒" -f date=2026-11-11

# 查看运行状态
gh run list --limit 5
gh run view --log
```

也可以在仓库 **Actions** 页点 **Run workflow**，可选填日期。

---

## 四、日常操作

| 想做什么 | 怎么做 |
|---|---|
| 改课程内容 | 编辑 `plan.json`，push 即可，次日生效 |
| 改推送时间 | 改 `remind.yml` 里的 `cron`（**UTC**，北京 9:00 写成 `0 1 * * *`） |
| 改机器人名字 | 改 `plan.json` → `meta.bot_name`，同步改飞书应用名 |
| 改计划起点 | 改 `plan.json` → `meta.start_date`，整条时间轴随之平移 |
| 临时补发 | Actions 页手动 Run workflow |
| 暂停提醒 | Actions 页「···」→ Disable workflow |

---

## 五、几个必须知道的坑

1. **GitHub Actions 的 cron 是 UTC**，写 `0 9 * * *` 会变成北京时间 17:00。
2. **定时触发有延迟**，常见 3–15 分钟。这来自 GitHub 侧调度策略，不是代码问题。要求精确到分钟需改用云函数。
3. **仓库 60 天无提交，定时任务会被自动停用**（会发邮件提醒）。改一次 `plan.json` 或手动运行一次即可恢复。
4. **`App Secret` 泄露等于应用被接管**。怀疑泄露时去开放平台「重置 App Secret」，并同步更新 GitHub Secret。
5. **报错 `230013`** = 应用可用范围不含你，去「版本管理与发布 → 可用范围」加上自己。
6. **报错 `99991663` / `receive_id invalid`** = 用错 open_id，改用 union_id。
7. **卡片内链接**打不开多半是原站需要登录，不是消息的问题。

---

## 六、文件说明

```
study-reminder/
├── plan.json                     # 课程表：5 天预备期 + 24 周内容
├── remind.py                     # 主程序：算日期 → 组卡片 → 发送
├── .github/workflows/remind.yml  # 每天 09:00(北京) 触发
├── .env.example                  # 环境变量模板
├── .gitignore
└── README.md
```

### `remind.py` 的逻辑

```
读 plan.json
  ↓
今天 < start_date  → 查预备期（按日期精确匹配）
今天 ≥ start_date  → 算周数 ceil((今天-start)/7) → 取对应周
  ↓
周一~周五 → 取 weekday[星期几]   （每天一件，不贪多）
周六/周日 → 取 weekend.sat/sun   （动手实验）
  ↓
组装飞书交互卡片 → 发送
```

零第三方依赖，只用 Python 标准库。支持两种通道，按环境变量自动选择：

```
有 APP_ID + APP_SECRET → 应用私聊
否则有 FEISHU_WEBHOOK  → 群机器人 Webhook
```

### 计划结构

| 阶段 | 周次 | 主题 |
|---|---|---|
| 预备期 | 5 天 | 搭环境（Docker + Iceberg + Kafka + Doris） |
| A | 1–6 | 存储格式、Iceberg、Spark 执行与调优 |
| B | 7–9 | CDC、Kafka、端到端一致性 |
| C | 10–13 | OLAP 引擎、表设计、维度建模落地 |
| D | 14–16 | Airflow、补数、dbt |
| E | 17–20 | 质量、元数据、血缘、权限与成本 |
| F | 21–24 | Flink、实时数仓、Capstone |

默认时间轴：`2026-11-09` 起共 24 周。改 `meta.start_date` 即可整体平移。

---

## License

MIT
