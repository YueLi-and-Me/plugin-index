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
