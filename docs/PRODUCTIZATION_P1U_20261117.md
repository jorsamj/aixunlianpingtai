# P1U 完整模型转换工作台

基于P1T业务7865d08294e82488c81f0864f4ec29a57ef5edf3及观测测试收尾ceb6e05f5ce5b5b9bc64668b2564150f4c315928接续。唯一长期分支不变，VERSION42.24.592不改。当前提交前记录，准确新SHA CI及下载制品仍须推送后核实。

## 实际实现 / Owner / 回退

新增ConversionCreate.vue/types与conversion-create-vue-runtime薄展示。复用原openNewConvert428最终入口及openNewConvertCore416的独立source/catalog/resources loaders，原动态模板、目标/精度/厂商芯片/ONNX/TensorRT/Sophon/Ascend/RKNN参数、校准和颜色配置全部为原唯一DOM/事件/提交Owner。适配器先同步完成旧decorator，再移交原main/footer节点；旧decorator在activeVue只停止外层重包，原loader/合同重绘继续操作其控件。Vue不持有第二配置草稿、兼容白名单、执行器或轮询。原源引用被读到不等于文件完整性；当前资源列表不等于SDK检测或可运行。数值/硬件/产物/发布证据缺失明确未提供。

ConversionHistory新增“创建版本转换”和原任务日志、操作/验证入口，仍原分页/筛选/上下文。新入口通过原NavigationStability回算法页，再交原公开Owner；不直接取消/重试/修改任务。flag vue_conversion_create=1启用Vue容器，旧默认和“使用原转换界面”保留同原控件/参数。关闭释放本页view/监听/读取，不取消后台正式任务。

## 原API及安全写边界

原v42选中版本deployments取源/历史，原v39目录、资源、resolve合同/检测状态继续由原Owner读取；只在用户明确动作时调用原POST deploy/jobs，source_id为原version::algorithm::version，产物按原Version追加，不新增训练Version。本轮不修改ModelArtifact/Runner/Worker/Agent/lease/数据库。Vue没有新增HTTP写接口或任务状态机。实际SDK检测只由原显式检测按钮，mounted不主动扫描。

原创建在POST前持久完整payload/request_id，UNKNOWN按by-request核验，明确重试保持同一冻结body。本轮真实入口发现found后直接开history遗留旧create，导致下一次新建多root/模态拦截：仅原verifyPendingConversion428/retryPending相邻区补捕获modal/project/source Owner；notfound优先原Warn就地显示原核验/同ID重试按钮，无form才原pendingmodal；found先关闭自己拥有的旧层，再核对没有新modal替换，清原回执后开history。迟到回执不关闭新窗口，不改创建/幂等/Worker合同。

## 验证证据与未验证

TypeScript/Vite1711模块通过，最终布局build JS982.68kB/CSS143.39kB。原转换/SDK/幂等/新适配器定向44通过；生命周期新增原Owner行为测试4通过（含前述重叠，不叠加计数），最新桥接/入口/适配器/幂等44通过。原字典能力、SDK过期/失败/切资源、旧请求迟到、复用runID而非新检测等合同保持。

frontend/tests/real-conversion-create.acceptance.mjs复用原8035临时库/lifespanoff原登录/源版本历史；目录、资源、resolve和任务核验HTTP明确为合成，绝不称真实SDK能力。原五种目标控件/动态芯片合同、ONNX opset13/dynamic payload、原packet持久/UNKNOWN两GET恢复、仅1POST且在浏览器abort、检测POST0、单create根/单可见modal及原界面真实点击回退均通过。两场景六宽1920/1600/1440/1366/1024/768截图12张，receipt在test-results/p1u-conversion-create。布局发现stickyfooter漏正文后改为正文单滚动与footer独立占位；最终截图补验以最新layout回执为准。8035按各轮结束停止。

未执行真实转换/SDK编译、模型数值/硬件/场景验收、生产训练/GT/OSS/外部发布。真实GPU/NPU/Ascend等节点及目标离线安装未验证。任务取消和失败执行重试继续原正式工作台（未发现独立安全的失败重跑Owner，不伪造）。源码+Vue离线包含与准确SHA CI待最终核验，不能将本地mock合同或旧SHA绿色写作本轮生产验收。

## 后续

P1V交付与畅联云工作台继续使用原ExternalPublication/ModelArtifact/Storage Owner。无需为本阶段抽app.py或新Repository；异构linux/amd64/arm64/CUDA/Ascend等沿后端实际能力，不实施新硬件适配。

最终布局补验：MC_CONVERSION_SCREENSHOT_ONLY=1，仅原登录/源GET与合成只读合同，创建POST0/检测POST0；六宽×两场景12图，layout-receipt逐项记录layoutBottom<=footerTop+1及footerBottom<=viewportHeight，无横向溢出，1366/768实际查看确认不漏正文。未重复已通过的UNKNOWN提交链。
