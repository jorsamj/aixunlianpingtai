# P2B-4A-1A CI 环境可靠性（2026-11-18）

基线73156bca9746232b5ca21cc43eb215bfabcc7ef3；唯一feature/external-algorithm-publishing，起点干净。仅修改本Workflow、CI字体脚本和本记录，不改业务代码/测试/版本/生产。最终SHA/运行结果在交付报告和准确SHA Actions核对，不预写成功。

## 问题和选择

旧run44238092655中每个runner独立apt下载同一61.2MB字体，Shard1/2/3字体约19秒/15分41秒/18分07秒；两分片因环境成本耗尽20分钟被取消。用户提供的旧耗时为审计依据，旧成功不作为新SHA结果。

采用prepare-browser-environment（Ubuntu24.04）+官方actions/cache@v4 +同Workflow字体Artifact：Cache仅跨运行复用，不能保证同次冷启动三个runner共享，因此增加prepare集中下载一次，在命中和未命中时都校验并上传。同次三个并行shard、Frontend及P1Z均从同SHA Artifact消费；消费者完全不运行apt。prepare失败则清楚阻断下游，不把缺字体截图视为通过。

字体固定fonts-noto-cjk=1:20230817+repack1-3；Cache key含Ubuntu24.04/架构/字体版本/脚本hash，不用跨版本restore-keys。Cache miss从原Ubuntu官方apt源更新索引并下载经apt验证的软件包，超时/重试参数只用于CI下载，不改源；dpkg-deb提取原完整Noto字体集和copyright。SHA256清单、版本及文件非空检查后安装用户字体目录、fc-cache、fc-match确认Noto Sans CJK SC可匹配。保留完整字体，不更换截图字体合同。字体包版本未来不可获取时会明确失败，需独立更新版本/key，不静默漂移。字体许可随Artifact保存。

Cache路径.ci-cache/noto-cjk；Artifact browser-fonts-${github.sha}，消费者同名下载到同路径，保留7天。只缓存字体文件，不上传整个runner环境。所有三个shard仅needs prepare，fail-fast:false/[1,2,3]保持并行；P1Z仍依赖frontend构建和原同SHA Vue产物，字体依赖显式添加。

Node24使用setup-node@v4的cache:npm，根/frontend两锁文件联合hash；共享下载缓存但每Job仍原npm ci，不缓存node_modules。Python3.12使用setup-python@v5的cache:pip，hash当前Workflow（依赖内联在此），只缓存pip下载/wheel。普通后端与CPU torch/torchvision/ultralytics安装命令/版本/索引保持原样。共享pip key不表示缓存一定包含全部包，任何缺失包仍正常下载；未固定的传递依赖仍按原安装规则解析，不以cache-hit充当安装成功。冷启动多个runner可能各自下载Python包，本轮不打包虚拟环境。

[setup-node官方缓存说明](https://github.com/actions/setup-node#caching-global-packages-data)、[setup-python官方缓存说明](https://github.com/actions/setup-python#caching-packages-dependencies)是配置依据。未引入第三方Action、镜像、缓存中心或Playwright浏览器整包缓存。

## 时限与保护

frontend保持20分钟，browser-navigation保持20分钟，P1Z保持10分钟；prepare单独20分钟，将下载波动从shard执行预算剥离。先按真实新CI结果评估，不仅提高timeout掩盖下载。若实际仍不足，后续按证据调整，必须新SHA重验。没有改默认轮询、服务端或生产。

结构核验逐项对比基线：三个原Job的测试/安装命令（除字体搬迁）、Node/Python版本、矩阵、现有Artifact名称/路径/if/保留时间及所有断言不变。新增字体Artifact不替代原测试制品。浏览器任务集合连重复历史条目也保持原样，本轮不整理。

## 本地验证与CI验收

本地YAML解析、对照旧Job步骤的结构断言、缓存锁文件存在、Artifact生产/消费路径匹配及needs矩阵验证通过；Git Bash bash -n tools/ci/browser-fonts.sh通过；git diff --check通过。不在Windows伪造Linux字体可用结果，不重跑本地浏览器或全仓测试；字体fc-match、pip/npm真实安装和三个shard耗时/结果由新SHA正常CI验收。

最终报告应分列prepare缓存命中/下载与字体验证、各shard环境步骤耗时、Chrome耗时、最终结果。冷缓存成功不等于已实测未来Cache hit；没有实际命中就明确记录miss。只关注该SHA正常触发CI，不手动启动其他已通过工作流。不借旧SHA成功宣布新SHA验收。出现失败只诊断该失败Job，修复产生新SHA重新验收。

回退普通git revert本专项提交，无Schema或数据迁移；不进P2B-4A-2。主模型设计/实现并审查实际Diff，gpt-6.1-sol只读辅助核对现有重复依赖与缓存路径；无子Agent修改或Git操作。
