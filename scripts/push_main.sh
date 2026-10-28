#!/usr/bin/env bash
# 把当前作业的提交推送到 main：被拒时先变基到远端最新 main 再重试，最多三次。
#
# sync.yml、review.yml、publish.yml 的提交步骤都调用本脚本，不再直接 git push。
#
# 现象：sync 一次分发多个审核作业，它们与发布作业各自推送 main，后推者因 non-fast-forward 被拒，
#       该作业的审核结论或索引更新随作业失败而丢失（审核评论已发出，状态却没有入库）。
# 原因：审核按 Issue 分并发组，以便多个版本并行调用模型；不能并入 plugin-index-writes 组，
#       GitHub 每个并发组只保留一个排队作业，新排队者会取消旧的排队者，审核会被静默丢弃。
# 后果：推送前必须变基；各作业只写自己插件与 Issue 的状态文件，正常不会冲突，
#       真有冲突时变基失败、作业报错，不得改成强制推送。
set -euo pipefail

for attempt in 1 2 3; do
  git pull --rebase --quiet origin main
  if git push origin HEAD:main; then
    exit 0
  fi
  sleep $((attempt * 3))
done
echo '推送 main 连续三次被拒' >&2
exit 1
