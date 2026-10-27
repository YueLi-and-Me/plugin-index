# 月璃插件索引

本仓库负责插件登记、固定规则检查、版本同步与归档索引。插件源码按 Git 对象读取，
检查与打包过程不执行插件入口。Release 附件是包的正本，商店分发地址是其副本。

作者通过「登记插件」Issue 表单填写插件 id、仓库地址、分类和说明。Tag 使用
`vX.Y.Z` 或 `X.Y.Z`，清单版本须与 Tag 一致；首次登记需要维护者批准。清单必须有
作者、许可证和完整主程序版本区间，不得提交 `config.toml`，仅从 `src.plugin_system`
门面导入宿主类型。

`entries/<id>.json` 保存 `repository`、`maintainers`、`tags` 和可选 `yanked` 列表；
`state/<id>.json` 以版本号为键，保存固定 commit、审核状态、Issue 编号和发布摘要。
`blocked_versions.json` 以插件 id 为键保存拒绝版本列表；同版本号永不重复收录。
`trusted_repositories.json` 初始为空，只能由维护者手动编辑。

每日 UTC 18:00 与 07:00 同步新 Tag，每个插件最多取最新五版，合成一个带「插件审核」
标签的 Issue，保存状态后显式分发审核工作流。已收录 Tag 发生移动时仅标记撤回并通知，
原提交与包保持不变。

脚本使用 Python 3.12。CI 检出主程序最新发布 Tag 并安装其依赖，直接导入清单解析器，
不在索引仓库维护第二份清单判定。开发时设置 `YUELI_SOURCE_ROOT` 指向已检出的宿主代码，
运行 `uv run pytest`；测试只加载宿主清单契约模块，并阻止真实 HTTP 请求。

正式运行的网络入口包括 Git 仓库、PyPI 和 GitHub API；测试通过内存客户端替代。
工作流在 main 上运行，发布与审核权限分离。仓库没有配置远端或实际部署资源，
上线所需的仓库、密钥与商店部署由维护者另外配置。

## 审核机器人

上线后先手动运行一次同步工作流，建立「插件审核」标签。登记表单自动附加该标签。
同步使用 `GITHUB_TOKEN` 创建的 Issue 不会触发新的 `issues` 工作流，因此同步作业
保存待审状态后通过 `gh workflow run review.yml -f issue_number=<编号>` 显式分发。
真人的 Issue、标签和评论事件仍使用原有入口。三个入口共用 Issue 编号并发键，
脚本重新读取 Issue，只处理未关闭且带审核标签的项。分发编号必须是无前导零的正整数。

确定性检查通过后，机器人将完整源码、差异、清单、README 与 Issue 资料作为待审证据
提交模型，禁止执行其中的指令。输出使用 JSON Schema 校验，只允许 `pass` 与
`manual_review`。首次请求格式不合规时最多重试三次；每个 Issue 最多八次模型调用，
包含失败。请求之前写入机器人评论账本和本地状态，工作流失败重跑也不会重置预算。
完整源码超过 200 KiB 时转人工，不截断送审。

首次登记无论模型结论如何，都需要有仓库写权限的维护者评论 `/approve`。
已登记插件的新版本只有固定检查通过、模型已审阅、结论通过且风险为空才自动批准。
二进制与新增或改动依赖强制转人工；授信仓库免模型审核，但不免固定检查或人工要求。
机器人评论中的命令斜杠会变成全角，不会被当作维护者指令。

维护者命令：

- `/approve [版本]`：批准此 Issue 的待审版本；省略版本时批准全部待审版本，仍会重新运行硬规则检查。
- `/reject 原因`：拒绝此 Issue 尚未批准的版本，并写入永久拒绝名单。
- `/review`：在本 Issue 剩余预算内重审；达到上限后只能人工处理。

维护者身份通过仓库权限 API 核实。批准状态推送成功后才关闭完成的 Issue，并显式分发
`publish.yml`。不同 Issue 同时更新仓库而发生非快进冲突时，推送会明确失败，不能静默覆盖
他人的审核状态；维护者可重跑失败作业，模型调用次数仍保留。

审核作业需要 `REVIEW_API_BASE`、`REVIEW_API_KEY`、`REVIEW_MODEL` 三个 Actions secrets。
审核接口采用通用兼容请求格式，代码不绑定服务商。模型审核不能保证安全，Python 依赖
库自身的源码不在审核范围内，安装者仍需阅读同进程权限提示。

## 商店网站

`scripts/build_site.py` 读取 `index.json` 与 `readme/<id>/<版本>.md`，用 `site-templates/`
里的 Jinja2 模板生成静态站点到 `site/`：插件列表 `/`、详情页 `/plugins/<id>/`、登记说明
`/submit/`、`/404.html`，以及与仓库逐字节相同的 `/index.json`。README 经 markdown-it-py
渲染后用 nh3 白名单清洗；页面不加载任何外部资源，等宽字体随站点发布（JetBrains Mono
拉丁子集，许可证见 `site-templates/static/fonts/OFL.txt`），中文使用系统字体。
插件包 `/packages/<id>/<版本>.zip` 是 Release 附件的副本，生成时逐个核对大小与摘要，
缺包或不符直接失败。

本地生成与预览（没有 Release 附件时加 `--allow-missing-packages`，下载链接会是 404）：

```bash
uv sync
uv run python -m scripts.build_site --allow-missing-packages
python -m http.server 8000 --directory site
```

用样例数据预览时把 `--root` 指向 `tests/fixtures/storefront`。下载次数来自 Worker 的
`/stats.json`，静态预览没有这个接口，页面显示「—」。一键安装按钮跳到部署者自己的管理面板
`<地址>/plugins?install=<id>&version=<版本>`，默认 `http://127.0.0.1:7999`，访客可在页面上修改，
保存在浏览器本地。

`worker/src/index.js` 是下载计数 Worker：`/packages/*` 先交给静态资源，只有 GET、无 Range
且资源返回 200 时才把 D1 表 `downloads` 对应行加一；`/stats.json` 汇总计数，缓存 300 秒。
不读取、不保存 IP、User-Agent 等请求方信息。Worker 用例用 Node 内置 `node:sqlite` 模拟 D1：

```bash
node --test 'worker/test/*.test.js' 'tests/js/*.test.cjs'
```

部署由 `publish.yml` 的 `deploy` 作业完成，只在手动与定时触发、打包作业成功后运行：
检出 main，从 Release 补齐 `site/packages/` 中缺少的包（已下载的用 Actions 缓存保存），
生成站点，执行 `worker/schema.sql` 建表（幂等），再 `wrangler deploy`。站点只走自定义域名
`plugins.yuelibot.org`，不启用 `workers.dev`，后者在中国大陆被 DNS 污染。

计数库 `yueli-plugins` 已建好，`database_id` 写在 `wrangler.toml`；换 Cloudflare 账号部署时
需重新执行 `wrangler d1 create yueli-plugins` 并替换。上线前维护者还需要：

- 建立 `production` 环境，配置 `CLOUDFLARE_API_TOKEN`（Workers 脚本、D1 编辑与自定义域名权限）
  与 `CLOUDFLARE_ACCOUNT_ID` 两个 secrets。

部署凭证只出现在 `deploy` 作业：审核作业要读第三方插件源码，凭证与之同处一个作业时，
插件里藏的代码就可能把凭证带出去，进而替换商店里的插件包。
