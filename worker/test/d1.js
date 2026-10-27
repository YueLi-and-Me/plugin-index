/**
 * 用 Node 内置 node:sqlite 模拟 Cloudflare D1 绑定，供 Worker 离线用例使用。
 *
 * 只实现 Worker 用到的 prepare / bind / run / all 四个接口，语义与 D1 一致：
 * bind 返回新的语句对象，run 与 all 返回 Promise。建表直接执行仓库里的
 * worker/schema.sql，用例跑的是真实表结构而不是手写副本。
 * 被 index.test.js 导入，不参与部署。
 */
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

/** 仓库内的建表语句路径，相对本文件解析，避免依赖运行目录。 */
const SCHEMA_PATH = new URL('../schema.sql', import.meta.url);

/**
 * D1 预编译语句的最小兼容实现。
 */
class Statement {
  /**
   * @param {DatabaseSync} database 内存 SQLite 连接。
   * @param {string} sql 带 ? 占位符的语句。
   * @param {Array<unknown>} params 已绑定的参数，默认为空。
   */
  constructor(database, sql, params = []) {
    this.database = database;
    this.sql = sql;
    this.params = params;
  }

  /**
   * 绑定参数，返回新语句；与 D1 一样不修改原对象。
   * @param {...unknown} params 按顺序对应 ? 占位符。
   * @returns {Statement}
   */
  bind(...params) {
    return new Statement(this.database, this.sql, params);
  }

  /**
   * 执行写语句。
   * @returns {Promise<{success: boolean, meta: {changes: number}}>}
   */
  async run() {
    const result = this.database.prepare(this.sql).run(...this.params);
    return { success: true, meta: { changes: Number(result.changes) } };
  }

  /**
   * 执行查询，返回全部行。
   * @returns {Promise<{success: boolean, results: Array<Object>}>}
   */
  async all() {
    return { success: true, results: this.database.prepare(this.sql).all(...this.params) };
  }
}

/**
 * 新建内存库并执行 schema.sql，返回 D1 形态的绑定对象。
 * @returns {{prepare: (sql: string) => Statement, sqlite: DatabaseSync}}
 */
export function createD1() {
  const sqlite = new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(SCHEMA_PATH, 'utf8'));
  return { sqlite, prepare: (sql) => new Statement(sqlite, sql) };
}
