/**
 * 一键安装按钮逻辑（site-templates/static/install.js）的离线用例。
 *
 * install.js 在浏览器里是普通脚本，在 Node 里通过 module.exports 导出同一组纯函数；
 * localStorage 用内存对象或必定抛错的对象代替。运行：node --test tests/js/
 */
const assert = require('node:assert/strict');
const path = require('node:path');
const { test } = require('node:test');

const install = require(path.join(__dirname, '../../site-templates/static/install.js'));

/** 内存版 localStorage，只实现 getItem / setItem。 */
function memoryStorage(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value); },
  };
}

/** 任何读写都抛 SecurityError 的 localStorage，模拟隐私模式或禁用站点数据。 */
const brokenStorage = {
  getItem: () => { throw new Error('SecurityError'); },
  setItem: () => { throw new Error('SecurityError'); },
};

test('默认链接指向本机管理面板', () => {
  const panel = install.readPanel(memoryStorage());
  assert.equal(panel, 'http://127.0.0.1:7999');
  assert.equal(install.installUrl(panel, 'yueli.web-search', '0.2.5'), 'http://127.0.0.1:7999/plugins?install=yueli.web-search&version=0.2.5');
});

test('改过的地址从 localStorage 读回', () => {
  const storage = memoryStorage();
  assert.equal(install.savePanel(storage, 'https://panel.example:8443/yueli'), 'https://panel.example:8443/yueli');
  assert.equal(install.readPanel(storage), 'https://panel.example:8443/yueli');
  assert.equal(install.installUrl(install.readPanel(storage), 'a.b', '1.0.0'), 'https://panel.example:8443/yueli/plugins?install=a.b&version=1.0.0');
});

test('localStorage 抛错时回到默认地址', () => {
  assert.equal(install.readPanel(brokenStorage), 'http://127.0.0.1:7999');
  assert.equal(install.readPanel(null), 'http://127.0.0.1:7999');
  assert.equal(install.savePanel(brokenStorage, 'http://192.168.1.2:7999'), 'http://192.168.1.2:7999');
});

test('非 http(s) 地址被拒，存储里的非法值也不采用', () => {
  const storage = memoryStorage();
  for (const value of ['javascript:alert(1)', 'ftp://host', '127.0.0.1:7999', '', '  ', 'http://']) {
    assert.equal(install.normalizePanel(value), null);
    assert.equal(install.savePanel(storage, value), null);
  }
  assert.deepEqual(storage.data, {});
  assert.equal(install.readPanel(memoryStorage({ [install.STORAGE_KEY]: 'javascript:alert(1)' })), 'http://127.0.0.1:7999');
});

test('末尾斜杠被去掉', () => {
  const storage = memoryStorage();
  assert.equal(install.savePanel(storage, ' http://10.0.0.5:7999/// '), 'http://10.0.0.5:7999');
  assert.equal(storage.data[install.STORAGE_KEY], 'http://10.0.0.5:7999');
});
