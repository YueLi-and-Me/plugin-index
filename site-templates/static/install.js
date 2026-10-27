/**
 * 一键安装按钮：把「安装」链接指向部署者自己的管理面板，并允许原地修改面板地址。
 *
 * 商店网站碰不到部署者的月璃，按钮只是跳转到
 * <管理面板地址>/plugins?install=<id>&version=<版本>，由管理面板弹确认框完成安装。
 * 面板地址默认 http://127.0.0.1:7999，修改后存 localStorage；读写都可能抛错
 * （隐私模式、禁用站点数据），抛错时用默认地址，页面照常工作。
 * 不探测面板是否在线：商店是 https，向 http 本机地址发请求会被浏览器拦截，结果不可信。
 *
 * 对外接口：浏览器里挂到 window.YueliInstall 并自动绑定页面上的 [data-install] 区块；
 * Node 里通过 module.exports 导出纯函数，供 tests/js/install.test.cjs 使用。
 * 页面结构由 site-templates/_install.html 生成。
 */
(function (root) {
  'use strict';

  /** 管理面板默认地址：月璃后端默认监听本机 7999 端口。 */
  var DEFAULT_PANEL = 'http://127.0.0.1:7999';
  /** localStorage 键名，值为去掉末尾斜杠的 http(s) 地址。 */
  var STORAGE_KEY = 'yueli.panel-url';

  /**
   * 校验并规范化面板地址。
   * @param {unknown} value 用户输入或存储里读出的值。
   * @returns {string|null} 去掉首尾空白与末尾斜杠的地址；不是 http:// 或 https:// 开头、
   *   无法解析或没有主机名时返回 null。
   */
  function normalizePanel(value) {
    if (typeof value !== 'string') return null;
    var text = value.trim().replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(text)) return null;
    try {
      if (!new URL(text).hostname) return null;
    } catch (error) {
      return null;
    }
    return text;
  }

  /**
   * 读取已保存的面板地址。
   * @param {Storage|null} storage localStorage 或兼容对象；为 null 时直接用默认值。
   * @returns {string} 合法的已存地址，否则 DEFAULT_PANEL；读取抛错时同样返回默认值。
   */
  function readPanel(storage) {
    try {
      return (storage && normalizePanel(storage.getItem(STORAGE_KEY))) || DEFAULT_PANEL;
    } catch (error) {
      return DEFAULT_PANEL;
    }
  }

  /**
   * 校验并保存面板地址。
   * @param {Storage|null} storage localStorage 或兼容对象。
   * @param {string} value 用户输入。
   * @returns {string|null} 规范化后的地址；非法时返回 null 且不写入。写入抛错时仍返回
   *   地址，本页继续使用，只是刷新后回到默认值。
   */
  function savePanel(storage, value) {
    var panel = normalizePanel(value);
    if (panel === null) return null;
    try {
      if (storage) storage.setItem(STORAGE_KEY, panel);
    } catch (error) {
      // 存储不可用时不阻止本次使用，见函数说明。
    }
    return panel;
  }

  /**
   * 生成安装跳转地址。
   * @param {string} panel 规范化后的面板地址。
   * @param {string} pluginId 插件 id。
   * @param {string} version 要安装的版本号。
   * @returns {string} <panel>/plugins?install=<id>&version=<version>，参数做 URL 编码。
   */
  function installUrl(panel, pluginId, version) {
    return panel + '/plugins?install=' + encodeURIComponent(pluginId) + '&version=' + encodeURIComponent(version);
  }

  /**
   * 去掉协议前缀用于界面显示，与设计稿的「127.0.0.1:7999」写法一致。
   * @param {string} panel 规范化后的面板地址。
   * @returns {string}
   */
  function displayPanel(panel) {
    return panel.replace(/^https?:\/\//i, '');
  }

  /**
   * 取得 localStorage；访问 window.localStorage 本身就可能抛 SecurityError。
   * @returns {Storage|null}
   */
  function browserStorage() {
    try {
      return root.localStorage || null;
    } catch (error) {
      return null;
    }
  }

  /**
   * 绑定页面上的全部安装区块：刷新链接与地址显示，处理「修改」的展开、保存与取消。
   * 一个页面可有多个区块（列表页每个插件一个），保存后全部同步更新。
   * @param {Document} doc 页面文档。
   * @param {Storage|null} storage 存储对象。
   */
  function bind(doc, storage) {
    var panel = readPanel(storage);
    var blocks = Array.prototype.slice.call(doc.querySelectorAll('[data-install]'));

    function render() {
      blocks.forEach(function (block) {
        var link = block.querySelector('[data-install-link]');
        if (link) link.href = installUrl(panel, link.getAttribute('data-plugin'), link.getAttribute('data-version'));
        block.querySelectorAll('[data-panel-label]').forEach(function (label) {
          label.textContent = displayPanel(panel);
        });
      });
    }

    blocks.forEach(function (block) {
      var edit = block.querySelector('[data-panel-edit]');
      var form = block.querySelector('[data-panel-form]');
      if (!edit || !form) return;
      var input = form.querySelector('input');
      var error = form.querySelector('[data-panel-error]');
      function close() {
        form.hidden = true;
        error.hidden = true;
        edit.setAttribute('aria-expanded', 'false');
        edit.focus();
      }
      edit.addEventListener('click', function () {
        form.hidden = false;
        edit.setAttribute('aria-expanded', 'true');
        input.value = panel;
        input.focus();
        input.select();
      });
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var saved = savePanel(storage, input.value);
        if (saved === null) {
          error.hidden = false;
          input.focus();
          return;
        }
        panel = saved;
        render();
        close();
      });
      form.querySelector('[data-panel-cancel]').addEventListener('click', close);
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      });
    });
    render();
  }

  var api = {
    DEFAULT_PANEL: DEFAULT_PANEL,
    STORAGE_KEY: STORAGE_KEY,
    normalizePanel: normalizePanel,
    readPanel: readPanel,
    savePanel: savePanel,
    installUrl: installUrl,
    displayPanel: displayPanel,
    bind: bind,
  };

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.YueliInstall = api;
    bind(root.document, browserStorage());
  }
})(typeof window !== 'undefined' ? window : globalThis);
