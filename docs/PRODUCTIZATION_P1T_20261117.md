# P1T 完整训练报告与模型评测（实施中）

前序P1S业务e83a60c807fdd09081c079245d1fd630c76e5c75已准确36/36 CI成功；新增报告区代码独立，不修改训练执行或P1S业务Owner。用户连续授权，无逐小步审批。

## 实施边界

增量扩TrainingReport.vue：保留摘要首屏；按需历史曲线分页、Test PR/混淆/类别、FP/FN及冻结图、版本指标对比。ECharts沿window.PlatformCore.reports挂载与dispose，本地6.1.0唯一加载，Vue不自行计算评测分数或重建图表库。

原v44 reader保持2MiB与DEFERRED，追加有界history页而非全历史读取。原v12 evaluation/report与samples/compare扩可选reader_view安全白名单，保持原Owner/身份/权限，旧无参合同不变。不扫描当前GT，不重算历史，不请求全部错误图，不发送评测POST。不新增Repository/评测执行Owner/数据库结构。

桥接限定当前报告job解析后的canonical project/algorithm/version；只对匹配identity放行GET，source已指定ID不得被迟到summary覆盖。版本对比严格沿原comparable和Test基准证据，缺失不能强行排名。

代码、定向API/Node/Chrome、六视口及准确SHA CI尚待实施完成；不能以本记录自称交付。原完整报告/评测入口继续保留，超出有界证据的历史仍明确DEFERRED/证据缺失。

## 实际交付与本地验收

TrainingReport增量Tab：训练过程有界history分页，原ECharts曲线；独立Test类别/PR阈值曲线/混淆矩阵分页及截断提示；类别FP/FN点击到原服务端过滤、TP/FP/FN样本分页；冻结eID/imageID/SHA URL严格核验，GT/预测box:[xyxy]只读叠加通过原MaterialPresentation/Panzoom；版本列表与指标/参数/类别对比分页，comparable=false明确不排名。零值和未提供分开，未执行任何评测/训练或重新构造历史GT。

后端仅扩原4个GET：v44 report reader增加history_offset/history_limit（1..200），默认保留最后200；v12 evaluation/report reader section=summary/classes/curves/confusion、offset/limit（<=100）；samples原offset/limit<=50及issue/class过滤增加reader；compare原端点增加reader及类别页。默认无reader行为保持。安全白名单字段、路径/凭据隐藏，曲线最多21点/类且显式truncated，矩阵cells页明确不完整；图片不合法历史身份不给URL、不擅自映射basename到另一图。原quality诊断固定最后200，与当前history页无关。2MiB与DEFERRED保留；原Repository、鉴权和版本归属保持。

原API/DTO定向Python7通过，Node桥接/入口缓存39通过；TypeScript/Vite1708模块通过，最终JS973.78kB/CSS139.25kB。新增3条Chrome均通过，布局分组后其中1条旧列标题断言更新为精确分组标题及map50真实值0.72再通过，未删除/放宽断言。真实离线ECharts加载和canvas已测，未引入第二图表运行时。新增测试接入既有Algorithm SQL Store作业，无新CI体系。入口三资源616，改变的桥接p1t1；未改变training-create/draft等未变模块缓存及VERSION。

真实入口脚本frontend/tests/real-report-detail.acceptance.mjs复用原8034临时fixture：原登录→任务第二页acceptance-train-00→真实v44 finalized摘要（Val Precision0/map50缺失、Test.72）→history offset1/limit5（5/14）→原ECharts→返回保留任务游标→原报告回退。JS/CSS/ECharts200、pageerrors=[]。六宽1920/1600/1440/1366/1024/768截图及receipt在test-results/p1t-real-entry；布局修正后摘要只在summary，history/classes四组列保留原值，六宽测量均无内部横向溢出，1920/768实际查看；8034停止。

证据限制：真实入口fixture没有正式独立evaluation与冻结错误样本，因此PR/混淆/FPFN/比较目前仅HTTP隔离数据+原真实ECharts+Python原Owner投影合同验证，不称生产评测验收。正式历史坏文件/超2MiB仍DEFERRED，现场报告/冻结图片权限和目标断网部署未验证。准确本提交CI及最终离线下载制品待推送后核验，不能以旧SHA绿色代替。本阶段无新写API、数据库结构、GT或执行Owner；不拆app.py，因变更只是4GET投影且无证明收益，不按行数机械分拆。下一阶段P1U转换创建工作台。

## 准确SHA首轮CI与信号观测修复

业务SHA7865d08294e82488c81f0864f4ec29a57ef5edf3的原前端job已成功，其Release Regression再次仅在未改生产代码的test_process_control.py:73挂起后立即观察running/stopped失败（与P1S同一位置）。SIGSTOP状态需异步送达；同用例resume/terminate已用原wait_until。仅将挂起也使用同一个既有5秒wait_until，最终条件仍严格STATUS_STOPPED；没有删除断言、跳过、延长既有helper截止或修改进程控制/Worker/Agent。单个失败用例定向1通过（既有8个FastAPI弃用告警）。本地Windows观测不代替LinuxCI；测试修复独立提交，准确新SHA CI继续核查，不把第一次失败描述成全绿。
