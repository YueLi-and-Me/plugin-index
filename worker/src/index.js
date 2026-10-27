/**
 * 月璃插件商店的下载计数 Worker，部署在 plugins.yuelibot.org。
 *
 * 职责：
 * - /packages/<id>/<版本>.zip：交给静态资源绑定 ASSETS 返回插件包，确认是一次真实的
 *   完整下载后在后台把 D1 表 downloads 里对应行加一。
 * - /stats.json：汇总 downloads 表，供商店页面显示下载次数。
 * - 其余进入 Worker 的请求原样交给 ASSETS。
 *
 * 依赖：wrangler.toml 声明的 ASSETS（站点目录 site/）与 DB（D1 库 yueli-plugins，
 * 表结构见 worker/schema.sql）；只有这两条路径配置了 run_worker_first，其余页面由
 * 静态资源层直接返回，不经过本文件。被 worker/test/index.test.js 离线测试。
 *
 * 隐私：不读取、不保存 IP、User-Agent、Referer 或任何请求方信息，只存聚合次数。
 */

/**
 * 插件包路径：插件 id 规则与 scripts/common.py 的 ID_PATTERN 一致，版本号与 TAG_PATTERN
 * 去掉 v 前缀后一致。只有完全匹配的路径才可能计数，避免任意路径往表里写行。
 */
const PACKAGE_PATH = /^\/packages\/([A-Za-z0-9][A-Za-z0-9._-]*)\/((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\.zip$/;

/** 统计接口的缓存秒数：300 秒内的重复请求由浏览器与边缘缓存回答，减轻 D1 读压力。 */
const STATS_MAX_AGE_SECONDS = 300;

const INCREMENT_SQL = 'INSERT INTO downloads (plugin_id, version, count) VALUES (?, ?, 1) ON CONFLICT(plugin_id, version) DO UPDATE SET count = count + 1';
const STATS_SQL = 'SELECT plugin_id, version, count FROM downloads ORDER BY plugin_id, version';

/**
 * 把一次下载记入 D1；失败只记日志，不向下载者暴露。
 *
 * 现象 / 原因 / 后果：计数在 ctx.waitUntil 里执行，此时响应已经发出，抛出的异常没有
 * 调用方可以接住，只会变成未处理的 rejection；这里捕获后写 console.error，
 * 让 Workers 日志里能看到失败，而下载本身不受影响。
 *
 * @param {Object} db D1 绑定。
 * @param {string} pluginId 已通过 PACKAGE_PATH 校验的插件 id。
 * @param {string} version 已通过 PACKAGE_PATH 校验的版本号。
 * @returns {Promise<void>} 永不拒绝。
 */
async function recordDownload(db, pluginId, version) {
  try {
    await db.prepare(INCREMENT_SQL).bind(pluginId, version).run();
  } catch (error) {
    console.error('下载计数写入失败', pluginId, version, error);
  }
}

/**
 * 处理插件包请求：先取静态资源，再决定是否计数。
 *
 * 只数 GET、无 Range 头且资源返回 200 的请求：HEAD 不传输内容；带 Range 的是续传或
 * 分段下载，同一次下载会产生多个请求；非 200 说明包不存在，计数会让任何人通过请求
 * 不存在的路径往表里塞垃圾行。
 *
 * @param {Request} request 原始请求，原样转交 ASSETS。
 * @param {Object} env 含 ASSETS 与 DB 绑定。
 * @param {Object} ctx 执行上下文，提供 waitUntil。
 * @param {string} pluginId 插件 id。
 * @param {string} version 版本号。
 * @returns {Promise<Response>} ASSETS 的原始响应。
 */
async function servePackage(request, env, ctx, pluginId, version) {
  const response = await env.ASSETS.fetch(request);
  if (request.method === 'GET' && !request.headers.has('Range') && response.status === 200) {
    ctx.waitUntil(recordDownload(env.DB, pluginId, version));
  }
  return response;
}

/**
 * 汇总全部下载计数。
 *
 * @param {Object} db D1 绑定；查询失败直接抛出，由运行时返回 500，页面显示「—」。
 * @returns {Promise<Response>} JSON：{ generated_at, plugins: { <id>: { total, versions: { <版本>: 次数 } } } }。
 */
async function serveStats(db) {
  const { results } = await db.prepare(STATS_SQL).all();
  const plugins = {};
  for (const row of results) {
    const entry = plugins[row.plugin_id] ?? (plugins[row.plugin_id] = { total: 0, versions: {} });
    const count = Number(row.count);
    entry.versions[row.version] = count;
    entry.total += count;
  }
  const body = JSON.stringify({ generated_at: new Date().toISOString(), plugins });
  return new Response(body, {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': `public, max-age=${STATS_MAX_AGE_SECONDS}`,
    },
  });
}

export default {
  /**
   * Worker 入口。
   *
   * @param {Request} request 进入 Worker 的请求（wrangler.toml 中 run_worker_first 列出的路径）。
   * @param {Object} env 绑定：ASSETS 静态资源、DB 计数库。
   * @param {Object} ctx 执行上下文。
   * @returns {Promise<Response>}
   */
  async fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);
    if (pathname === '/stats.json') {
      return serveStats(env.DB);
    }
    const match = PACKAGE_PATH.exec(pathname);
    if (match) {
      return servePackage(request, env, ctx, match[1], match[2]);
    }
    return env.ASSETS.fetch(request);
  },
};
