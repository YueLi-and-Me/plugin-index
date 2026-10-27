/**
 * 商店页面交互：下载次数、列表页选择与筛选、状态栏快捷键、复制插件 ID。
 *
 * - 下载次数：从 body[data-stats]（index.json 的 stats_url 路径部分，即 /stats.json）读取，
 *   填入 [data-downloads] 占位；请求失败或格式不对时保持「—」，不打断页面。
 * - 列表页（body[data-page="list"]）：↑↓ 移动选中行并切换下方详情块，Enter 打开详情页，
 *   / 聚焦搜索；点行选中，点「查看 ↵」进入详情页；搜索匹配名称、说明与 id，分类按钮按 tags 筛选。
 * - 其他页面：Esc 回列表，/ 回列表并聚焦搜索（通过 /#search 传递）。
 * 焦点在输入框、按钮或链接上时不拦截按键，保证 / 与方向键照常输入、Enter 照常激活控件。
 *
 * 页面结构由 site-templates/index.html 与 plugin.html 生成；一键安装由 install.js 单独处理。
 */
(function () {
  'use strict';

  var body = document.body;
  var page = body.getAttribute('data-page');

  /** 数字按千分位显示，与设计稿「1,248」一致。 */
  var numberFormat = new Intl.NumberFormat('en-US');

  /**
   * 判断按键是否应交给当前焦点元素自己处理。
   * @param {KeyboardEvent} event 键盘事件。
   * @param {boolean} includeControls 为 true 时链接与按钮也算（用于 Enter）。
   * @returns {boolean}
   */
  function focusOwnsKey(event, includeControls) {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return true;
    var target = event.target;
    if (!(target instanceof Element)) return false;
    if (target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]')) return true;
    return includeControls && !!target.closest('a[href], button');
  }

  /** 读取 /stats.json 并填入全部下载次数占位。 */
  function loadStats() {
    var path = body.getAttribute('data-stats');
    var cells = document.querySelectorAll('[data-downloads]');
    if (!path || !cells.length || !window.fetch) return;
    fetch(path, { headers: { Accept: 'application/json' } })
      .then(function (response) {
        if (!response.ok) throw new Error('stats ' + response.status);
        return response.json();
      })
      .then(function (stats) {
        var plugins = stats && typeof stats.plugins === 'object' && stats.plugins ? stats.plugins : null;
        if (!plugins) return;
        Array.prototype.forEach.call(cells, function (cell) {
          var entry = plugins[cell.getAttribute('data-downloads')];
          var version = cell.getAttribute('data-version');
          var value = !entry ? 0 : version ? entry.versions && entry.versions[version] || 0 : entry.total;
          cell.textContent = numberFormat.format(Number(value) || 0);
        });
      })
      .catch(function () {
        // 统计服务不可用时保持「—」：下载次数只是参考信息，不应影响浏览与安装。
      });
  }

  /** 列表页：选择、筛选与快捷键。 */
  function setupList() {
    var input = document.getElementById('search');
    var empty = document.getElementById('empty');
    var rows = Array.prototype.slice.call(document.querySelectorAll('.plugin-row'));
    var summaries = {};
    Array.prototype.forEach.call(document.querySelectorAll('[data-summary]'), function (section) {
      summaries[section.getAttribute('data-summary')] = section;
    });
    var filters = Array.prototype.slice.call(document.querySelectorAll('.filter'));
    var activeTag = '';
    var selected = rows[0] || null;

    function visibleRows() {
      return rows.filter(function (row) { return !row.hidden; });
    }

    function select(row, scroll) {
      selected = row;
      rows.forEach(function (item) {
        var on = item === row;
        item.classList.toggle('selected', on);
        if (on) item.setAttribute('aria-current', 'true');
        else item.removeAttribute('aria-current');
      });
      Object.keys(summaries).forEach(function (id) {
        summaries[id].hidden = !row || row.getAttribute('data-id') !== id;
      });
      if (row && scroll) row.scrollIntoView({ block: 'nearest' });
    }

    function applyFilter() {
      var query = input.value.trim().toLowerCase();
      rows.forEach(function (row) {
        var tags = JSON.parse(row.getAttribute('data-tags'));
        var matchTag = !activeTag || tags.indexOf(activeTag) !== -1;
        var matchQuery = !query || row.getAttribute('data-search').indexOf(query) !== -1;
        row.hidden = !(matchTag && matchQuery);
      });
      var visible = visibleRows();
      empty.hidden = visible.length > 0;
      if (!selected || selected.hidden) select(visible[0] || null, false);
    }

    function move(step) {
      var visible = visibleRows();
      if (!visible.length) return;
      var index = visible.indexOf(selected);
      var next = index === -1 ? 0 : Math.min(Math.max(index + step, 0), visible.length - 1);
      select(visible[next], true);
    }

    function open() {
      if (!selected || selected.hidden) return;
      window.location.href = selected.querySelector('.view').getAttribute('href');
    }

    rows.forEach(function (row) {
      row.addEventListener('click', function (event) {
        // 点「查看 ↵」直接走链接进入详情页；点行的其他位置只选中。
        if (event.target instanceof Element && event.target.closest('a[href]')) return;
        select(row, false);
      });
    });

    filters.forEach(function (button) {
      button.addEventListener('click', function () {
        activeTag = button.getAttribute('data-tag');
        filters.forEach(function (item) {
          item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
        });
        applyFilter();
      });
    });

    input.addEventListener('input', applyFilter);

    document.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (focusOwnsKey(event, false)) return;
        event.preventDefault();
        move(event.key === 'ArrowDown' ? 1 : -1);
      } else if (event.key === 'Enter') {
        if (focusOwnsKey(event, true)) return;
        event.preventDefault();
        open();
      } else if (event.key === '/') {
        if (focusOwnsKey(event, false)) return;
        event.preventDefault();
        input.focus();
        input.select();
      }
    });

    // 浏览器后退恢复表单值时，按恢复后的搜索词与分类重新筛选。
    applyFilter();
    if (window.location.hash === '#search') {
      input.focus();
      if (window.history.replaceState) window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  }

  /** 详情页与其他页面：Esc 回列表，/ 回列表并聚焦搜索。 */
  function setupReturnKeys() {
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        if (focusOwnsKey(event, false)) return;
        event.preventDefault();
        window.location.href = '/';
      } else if (event.key === '/') {
        if (focusOwnsKey(event, false)) return;
        event.preventDefault();
        window.location.href = '/#search';
      }
    });
  }

  /** 复制插件 ID；剪贴板接口不可用时选中文字，方便手动复制。 */
  function setupCopy() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-copy]'), function (button) {
      var source = document.getElementById(button.getAttribute('data-copy'));
      button.addEventListener('click', function () {
        var text = source.textContent;
        var done = function () {
          button.setAttribute('data-copied', 'true');
          button.setAttribute('aria-label', '已复制插件 ID');
          window.setTimeout(function () {
            button.removeAttribute('data-copied');
            button.setAttribute('aria-label', '复制插件 ID');
          }, 1500);
        };
        var fallback = function () {
          var range = document.createRange();
          range.selectNodeContents(source);
          var selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, fallback);
        } else {
          fallback();
        }
      });
    });
  }

  loadStats();
  setupCopy();
  if (page === 'list') setupList();
  else setupReturnKeys();
})();
