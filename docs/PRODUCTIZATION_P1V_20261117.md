# P1V 模型资产与畅联云交付工作台

基线10737e3b0ef78aeb520b4b8c9bffb39876c6c06a；唯一feature/external-algorithm-publishing。VERSION.txt 42.24.592保持。此记录随业务提交，准确提交CI及CI离线制品在推送后另行核验，不能预先称通过。

## 已实现 / Owner

新增ModelDelivery.vue与严格展示DTO，ModelAssets每个已选版本的“模型交付”进入原NavigationStability算法页，再交ExternalAlgorithmPublishRuntime.publishVersion；opt-in vue_model_delivery=1，原默认不变。当前/历史成果、Version登记、Weight交付、OSS状态、SHA、远端身份、元数据/冻结/准备/请求/确认/读回类别分别展示；缺字段显示未提供，不推断远端验证。当前模式仅展示原externalAlgorithmPlatformConfig已有事实。展示最多100当前/100历史、100类别并明确截断，完整原界面仍可用。

仍用原v64版本GET与原publish POST、原预检、映射和ExternalPublication/ModelArtifact Owner。转换产物仍是同一Version的追加Weight。没有新API/Repository/上传器/调度/发布状态机。平台总模式与存储配置通过关闭自己拥有的层后进入原可信页面：原v63 /mode明示切换控制两个自动开关，原SecretStore/存储测试/映射Owner保留；本阶段没有把完整配置表单重新开发一份。配置继续委托旧正式页面，不能宣称所有配置均已Vue迁移。

## 写入与UNKNOWN

首次仅GET，只有原preflight通过及明确confirm才执行原POST。原Owner补持久发布恢复键cl_external_delivery_pending_v1:p:a:v，仅身份+UNKNOWN，不存密钥、模型路径或payload。POST前写后回读失败则不发请求。POST未知、HTTP成功后尚未状态读回、刷新重进均禁止重复POST；仅原GET publication=PUBLISHED且requires_sync=false后清除。该版本接口没有by-request回执，本轮不虚构request_id回执端点。原Version/Weight/单资产UNKNOWN消息分别保留。

关闭/项目退出清理Vue订阅及状态GET，POST生命周期不被界面取消而误当服务端取消；迟到响应仍核验原项目/页面/层。动态加载与挂载前增加abort检查，防止已退出的挂载触碰旧host。安全白名单DTO屏蔽绝对路径、URL与凭据内容；原模型文件路径不等于下载授权。只清理页面，不取消正式后台任务。

## 定向证据

相关Node首次52/52通过；新增GET transport abort与迟到delivery import检查后，两个直接文件36/36（含此前重叠，不相加）。缓存4文件准确618期望已随入口合同更新，不放宽断言。TypeScript/Vite构建通过，最终字节/hash见仓库外build回执；入口styles/app/main统一42.25.618，只有本次变动publisher/catalog桥及上一callback修复的material-batches调用缓存更新，无关模块缓存不动。

frontend/tests/real-model-delivery.acceptance.mjs复用原index/真实登录及原算法存储隔离新建LOCAL与独立EXTERNAL/CHANG_LIAN身份。原始provider常量实际CHANG_LIAN，不改为猜测拼写。平台/存储/远端状态HTTP全部明确合成。验证LOCAL被阻断、原模式显式PUT合成回执同时两个开关、Version=PUBLISHED/Weight=PARTIAL分别展示、发布1POST在Chrome发往服务器前abort、UNKNOWN跨刷新仅GET读回且没有第二POST、原交付界面回退。无真实OSS/外部发布/SDK/GT/训练。

六宽1920/1600/1440/1366/1024/768、PARTIAL/UNKNOWN两场景12截图，1600/768实际查看；收据及截图保存在仓库外delivery-evidence/20261117/P1V-real-entry，避免Playwright输出清理。测试中缺discovered的合成响应原预检正确阻断；补齐原合同测试数据后通过，未放宽准入。另修缺失tags=null导致Vue渲染异常，仍显示未记录，未伪造空类别。

S/T/U此前test-results被一次默认Playwright输出清理，截图文件未恢复；不能继续把旧路径作为现存证据。准确e83a60c/ceb6e05/0913122的GitHub离线制品已在仓库外按head_sha/digest/JS/CSS SHA/CRC恢复，并以git archive原SHA追加其CI资源生成包含包；P1S-P1T-P1U-exact-sha-recovery-index.json记录来源及限制。未恢复原截图、未现场离线安装。此次恢复不等于重新执行功能验收。

## 未验 / 下一阶段

准确新SHA GitHub Actions、CI资源上传与离线包含待推送后核实。真实畅联/OSS/硬件/生产部署和现场完整离线安装未验证。本阶段仅隔离合同和UI验收，不将模拟回执当现场交付。未来linux/amd64/arm64及CUDA/Ascend扩展保持，无新硬件适配；无app.py机械拆分。下一P1W继续Uppy上传/ZIP/原治理Owner，再P1X/P1Y/P1Z，尚未完成的阶段不记为交付。

最终布局补取：仅GET与被拦截的原模式PUT，发布POST0；新增两个真实原配置入口及挂载abort检查后的六宽PARTIAL截图补验。UNKNOWN截图保留前次完整路径证据，未重复提交链。最终JS995565/CSS148399字节，以build-receipt实际记录为准。
