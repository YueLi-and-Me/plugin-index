# 月璃插件索引

[月璃](https://github.com/YueLi-and-Me/YueLiBot)插件的登记与审核仓库。插件在这里登记、经过检查与审核后，
由流水线打包并发布到[月璃插件商店](https://plugins.yuelibot.org)，月璃管理面板的「插件市场」也从这里生成的索引读取插件列表。

- 插件商店：<https://plugins.yuelibot.org>
- 插件开发文档：<https://docs.yuelibot.org/dev/guide/plugins/>
- 登记表单：[登记插件](https://github.com/YueLi-and-Me/plugin-index/issues/new?template=register.yml)

## 提交插件

### 准备

插件仓库需要公开，审核与打包会直接克隆它。提交前确认以下几点：

| 项目 | 要求 |
| :--- | :--- |
| 清单 `_manifest.json` | `id`、`version`、`author`、`license` 必填；`host_application` 的 `min_version` 与 `max_version` 两端都要写 |
| 版本 Tag | 写成 `vX.Y.Z` 或 `X.Y.Z`，去掉 `v` 后与清单 `version` 一致 |
| 导入 | 只从 `src.plugin_system` 导入主程序提供的类型，不导入 `src.core` 等内部模块 |
| 运行配置 | 不要提交 `config.toml` |
| Python 库 | 在清单 `python_dependencies` 中声明，只接受 PyPI 上存在的包，不接受网址形式 |
| 大小 | 打包后不超过 20 MiB |

检查、审核与打包都只针对 `git archive` 实际打出的内容。测试等开发文件需要导入主程序内部模块时，
在仓库根目录的 `.gitattributes` 中排除，它们就不随包发布，也不参与检查：

```text
tests/ export-ignore
```

### 登记

打好 Tag 后，填写[登记表单](https://github.com/YueLi-and-Me/plugin-index/issues/new?template=register.yml)：
插件 id、仓库地址、分类（多个用逗号分隔）和说明。说明里写清楚插件的用途、会访问哪些外部服务、
读写哪些数据，审核会对照这段说明与源码。提交后不要再编辑这个 Issue，审核以第一次读到的登记内容为准。

首次登记只审仓库里最新的一个版本。机器人完成检查和审核后在 Issue 里回复结论，
随后由维护者批准。批准后自动打包、发布，几分钟内出现在商店里，Issue 自动关闭。

### 发布新版本

已收录的插件只需在自己的仓库里打新 Tag。索引每小时同步一次，发现新版本后自动开审核 Issue，
满足下列全部条件即自动收录，不需要等待维护者：

- 固定检查全部通过；
- 模型完整审阅，结论为通过，且没有列出风险；
- 没有新增或改动 Python 依赖，包内没有二进制文件。

不满足的版本转人工处理。已收录的 Tag 不要改指向其他提交：同步发现 Tag 被移动时只会把该版本标记为撤回，
已发布的包不变。需要修正时请发布新版本。被拒绝的版本号会被永久记录，不能再次提交。

## 审核做什么

审核分两步，都不运行插件代码。

**固定检查**按规则判定，任何一项不过，版本就停在这一步，维护者批准也不能绕过：
清单格式与必填字段、id 与 Tag 一致、导入边界、不含运行配置与符号链接、包大小、依赖在 PyPI 上存在。
包含 `.dll`、`.so`、`.exe` 等二进制文件，或源码总量超过 200 KiB 时，不送模型审核，直接转人工。

**模型审核**把完整源码、与上一版本的差异、清单、README 和 Issue 正文交给审核模型，
重点检查：外传凭据、聊天记录或用户身份；读写插件目录以外的文件、修改主程序数据库或配置；
执行命令或远程代码；访问回环、内网或云元数据地址；使用 README 没有说明的第三方服务；清单与实际行为不符。
模型只能给出「通过」或「转人工」，不能直接批准或拒绝。

审核降低风险，但不能保证插件没有问题，Python 依赖库本身的源码也不在审核范围内。
插件与月璃运行在同一进程，能读取配置、模型密钥与数据库，安装前请确认来源可信。

## 维护者

### 命令

在审核 Issue 下评论，只有对本仓库有写权限的账号生效：

| 命令 | 作用 |
| :--- | :--- |
| `/approve` 或 `/approve 版本号` | 批准待审版本；批准前固定检查会重新运行 |
| `/reject 原因` | 拒绝尚未批准的版本，版本号写入永久拒绝名单 |
| `/review` | 在剩余次数内让模型重审 |

自动触发对每个待审版本只审一次，之后的重审都靠 `/review`。每个 Issue 最多调用模型 8 次，
失败和超时也计入，单次请求最长等待 5 分钟；次数用完后只能人工处理。机器人发出的评论中，
命令开头的斜杠会被替换为全角，插件资料里写的命令不会被当作维护者指令。

### 工作流

| 工作流 | 触发 | 作用 |
| :--- | :--- | :--- |
| 同步插件版本 `sync.yml` | 每小时第 17 分钟、手动 | 发现已收录插件的新 Tag，开审核 Issue 并分发审核 |
| 审核插件 `review.yml` | 登记 Issue、维护者命令、同步分发 | 固定检查、模型审核、记录结论；批准后分发发布 |
| 发布插件索引 `publish.yml` | 批准后、每天 02:30 与 15:30（北京时间）、手动 | 打包并上传 Release 附件，生成索引与商店网站，部署到 Cloudflare |

工作流只在 `main` 上运行。审核作业读取第三方源码，拿不到部署凭证；Cloudflare 凭证只存在于
`production` 环境，只有发布工作流的部署作业能读取，插件里藏的代码无法借审核作业替换商店里的插件包。

### 密钥

| 名称 | 位置 | 用途 |
| :--- | :--- | :--- |
| `REVIEW_API_BASE`、`REVIEW_API_KEY`、`REVIEW_MODEL` | 仓库 Actions secrets | 审核模型，接口为通用的 Chat Completions 格式，需支持 JSON 输出 |
| `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID` | `production` 环境 | 部署 Worker、写下载计数库、绑定自定义域名 |

### 数据文件

| 路径 | 内容 |
| :--- | :--- |
| `entries/<id>.json` | 已登记插件的仓库地址、维护者、分类与撤回版本 |
| `state/<id>.json` | 每个版本的固定提交、审核状态、审核 Issue 与包摘要 |
| `readme/<id>/<版本>.md` | 发布时保存的插件 README，用于商店详情页 |
| `index.json` | 客户端读取的索引，由流水线生成，不要手改 |
| `blocked_versions.json` | 被拒绝的版本号 |
| `trusted_repositories.json` | 授信仓库，免模型审核但仍需固定检查；只由维护者手动编辑 |

## 商店网站

`scripts/build_site.py` 读取 `index.json` 与 `readme/`，用 `site-templates/` 中的模板生成静态站点到 `site/`。
插件 README 渲染后经过白名单清洗；页面不加载外部资源，等宽字体随站点发布
（JetBrains Mono 拉丁子集，许可证见 `site-templates/static/fonts/OFL.txt`）。
生成时逐个核对插件包的大小与 SHA-256，缺包或不符直接失败。

插件包有两个下载地址，商店（`plugins.yuelibot.org/packages/...`）优先，GitHub Release 附件为正本与备用，
两处都会校验 SHA-256。站点只通过自定义域名提供服务，不启用 `workers.dev`，后者在中国大陆无法稳定访问。

「一键安装」跳转到访客自己的管理面板 `<地址>/plugins?install=<id>&version=<版本>`，默认
`http://127.0.0.1:7999`，访客可在页面上修改，地址保存在浏览器本地。面板会弹出确认框，确认后才安装。

`worker/src/index.js` 统计下载次数：只有完整下载成功的 GET 请求才计数，`/stats.json` 汇总后缓存 300 秒，
不读取、不保存 IP、User-Agent 等访客信息。计数库是 Cloudflare D1 `yueli-plugins`，`database_id` 写在
`wrangler.toml`，换账号部署时需重新建库并替换。

本地预览（没有 Release 附件时加 `--allow-missing-packages`，下载链接会是 404；用样例数据时把 `--root` 指向
`tests/fixtures/storefront`）：

```bash
uv sync
uv run python -m scripts.build_site --allow-missing-packages
python -m http.server 8000 --directory site
```

## 开发

脚本使用 Python 3.12。清单解析直接复用月璃主程序的代码，不在本仓库另写一份：CI 检出主程序最新发布版本，
本地开发时把 `YUELI_SOURCE_ROOT` 指向主程序源码目录。测试不访问真实网络：

```bash
YUELI_SOURCE_ROOT=../YueLiBot uv run pytest
node --test worker/test/index.test.js tests/js/install.test.cjs
```
