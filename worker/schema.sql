-- 插件包下载计数表，由 publish.yml 的 deploy 作业每次部署前执行，语句幂等。
-- plugin_id 与 version 对应 index.json 的插件 id 与版本号；count 为成功下载次数，非负整数。
-- 不保存任何请求方信息（IP、User-Agent、时间），只有聚合计数。
CREATE TABLE IF NOT EXISTS downloads(plugin_id TEXT NOT NULL, version TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (plugin_id, version));
