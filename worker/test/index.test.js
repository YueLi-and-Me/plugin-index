/**
 * 下载计数 Worker 的离线用例：计数条件、写入失败不影响下载、统计汇总与缓存头。
 *
 * 静态资源绑定 ASSETS 用桩函数按用例返回状态码，数据库用 d1.js 的 node:sqlite
 * 兼容层执行真实 schema.sql。ctx.waitUntil 收集的 Promise 在断言前统一等待，
 * 与线上「响应先返回、计数随后完成」的时序一致。运行：node --test worker/test/*.test.js
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createD1 } from './d1.js';
import worker from '../src/index.js';

/**
 * 组装一次请求所需的 env 与 ctx。
 * @param {number} status ASSETS 对任意请求返回的状态码。
 * @returns {{env: Object, ctx: Object, settle: () => Promise<void>, db: Object, assets: Array<Request>}}
 */
function harness(status = 200) {
  const pending = [];
  const assets = [];
  const db = createD1();
  const env = {
    DB: db,
    ASSETS: {
      fetch: async (request) => {
        assets.push(request);
        return new Response(status === 200 ? 'zip-bytes' : 'missing', { status });
      },
    },
  };
  const ctx = { waitUntil: (promise) => pending.push(promise) };
  return { env, ctx, db, assets, settle: () => Promise.all(pending).then(() => undefined) };
}

/** 读取指定插件版本的计数，没有行时返回 0。 */
function count(db, pluginId, version) {
  const row = db.sqlite.prepare('SELECT count FROM downloads WHERE plugin_id = ? AND version = ?').get(pluginId, version);
  return row ? Number(row.count) : 0;
}

const PACKAGE_URL = 'https://plugins.yuelibot.org/packages/yueli.web-search/0.2.5.zip';

test('GET 200 计数一次且响应原样返回', async () => {
  const { env, ctx, db, settle } = harness(200);
  const response = await worker.fetch(new Request(PACKAGE_URL), env, ctx);
  await settle();
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'zip-bytes');
  assert.equal(count(db, 'yueli.web-search', '0.2.5'), 1);
  await worker.fetch(new Request(PACKAGE_URL), env, ctx);
  await settle();
  assert.equal(count(db, 'yueli.web-search', '0.2.5'), 2);
});

test('HEAD、带 Range、404 都不计数', async () => {
  for (const [status, init] of [[200, { method: 'HEAD' }], [200, { headers: { Range: 'bytes=0-10' } }], [404, {}]]) {
    const { env, ctx, db, settle } = harness(status);
    const response = await worker.fetch(new Request(PACKAGE_URL, init), env, ctx);
    await settle();
    assert.equal(response.status, status);
    assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS rows FROM downloads').get().rows, 0);
  }
});

test('路径不符合包格式时不计数', async () => {
  const { env, ctx, db, settle, assets } = harness(200);
  for (const path of ['/packages/yueli.web-search/latest.zip', '/packages/../index.json', '/packages/a/b/1.0.0.zip']) {
    await worker.fetch(new Request('https://plugins.yuelibot.org' + path), env, ctx);
  }
  await settle();
  assert.equal(assets.length, 3);
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS rows FROM downloads').get().rows, 0);
});

test('D1 写入抛错时下载仍为 200，只记录错误', async (t) => {
  const { env, ctx, settle } = harness(200);
  env.DB = { prepare: () => ({ bind: () => ({ run: async () => { throw new Error('D1 unavailable'); } }) }) };
  const logged = t.mock.method(console, 'error', () => {});
  const response = await worker.fetch(new Request(PACKAGE_URL), env, ctx);
  await settle();
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'zip-bytes');
  assert.equal(logged.mock.callCount(), 1);
});

test('stats.json 按插件与版本汇总并带缓存头', async () => {
  const { env, ctx, settle } = harness(200);
  const hits = [['yueli.web-search', '0.2.5'], ['yueli.web-search', '0.2.5'], ['yueli.web-search', '0.2.3'], ['example.schedule', '1.0.2']];
  for (const [pluginId, version] of hits) {
    await worker.fetch(new Request(`https://plugins.yuelibot.org/packages/${pluginId}/${version}.zip`), env, ctx);
  }
  await settle();
  const response = await worker.fetch(new Request('https://plugins.yuelibot.org/stats.json'), env, ctx);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=300');
  assert.match(response.headers.get('Content-Type'), /^application\/json/);
  const body = await response.json();
  assert.ok(!Number.isNaN(Date.parse(body.generated_at)));
  assert.deepEqual(body.plugins, {
    'example.schedule': { total: 1, versions: { '1.0.2': 1 } },
    'yueli.web-search': { total: 3, versions: { '0.2.3': 1, '0.2.5': 2 } },
  });
});
