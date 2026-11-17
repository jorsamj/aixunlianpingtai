# P1W 素材上传与治理

接续P1V d9b3ff2b4f6488c198d2374e141fe79b0d15a329和旧Chrome确认适配7195f22ea6f3101c89ea411dfb37c9424e45ed7d；唯一开发分支，正式VERSION42.24.592保持。准确本阶段SHA与CI制品推送后核实，尚未称全绿。

## 实际功能与边界

新MaterialImportGovernance.vue/types/material-import-vue-runtime为真实上传及治理入口与原任务实时投影；flag vue_material_import=1，配vue_material_library=1从素材库“上传与治理”进入原NavigationStability注册页“素材上传与治理”。保留原“素材接入”素材源管理和原数据集、旧上传默认。普通图片由ImageUppyView.open、MaterialUploadRuntime.uploadFiles及原UploadConfirmation保存/回执；ZIP由原公开openUppyZipUpload和ZipImportRuntime multipart/幂等/SHA/CRC/限额执行。没有第二上传引擎，也没有重写ZIP路径/标签/回滚合同。

页面读取原UploadTaskCenterRuntime.list当前记录：文件、ID、状态、当前阶段进度、失败信息、时间；真实0与未知区分。当前仅100条展示且总数/截断明确，非通用历史分页服务，不假称全部远端历史。普通图片原任务操作交回数据集的完整任务中心；ZIP查看/暂停/重选恢复/原取消/UNKNOWN核验只调用原公开Owner，原取消确认保留，不用隐形点击旧DOM。恢复先打开原任务再由原Owner选择同文件。完成后可自主去素材库、清洗配置/历史、人工选图标注、AI创建、完整性/安全删除、负池和标签。复杂治理/引用预览/正式保存仍在原成熟Owner，本阶段不是把全部复杂表单重写为Vue。

原TaskCenter缺订阅，仅增加原render通知的subscribe/unsubscribe，destroy清理；Vue从原事实读取，没有第二缓存/轮询。新页仅opt-in时加入原PollRegistry ownerPages，旧原任务轮询唯一。离开页面只移除订阅/挂载，不调用cancelAllActive；项目变更后不读其他项目任务、不接收旧动作。受限Observer仅兼容缺原订阅的旧环境，当前使用正式订阅，不观察整个document。上传/ZIP引擎未改。

原清洗/删除仅可信入口，不新增执行写API；删除仍原estimate/preview计划凭证、引用保护及确认。500是已有显式ID批处理边界，未把它当所有ZIP的统一上限，也未擅自提高任何限额。人工标注仍Annotorious/AnnotationRepository，AI仍原Provider/CandidateStore，正式GT未动。

## 验证

定向原TaskCenter、新适配器及桥接共37/37 Node通过；入口缓存4文件17/17通过（两个集合有重叠时不汇总全平台数）。TypeScript/Vite1717模块通过。npm run verify:uppy原脚本验证固定6.0.5，87本地资源/notice、76依赖审计；真实浏览器加载原本地uppy.min.mjs/css/zh_CN，无CDN，无升级/重复完整运行时。styles/app/main入口缓存统一42.25.619，实际改动的catalog桥/UploadTaskCenter调用缓存更新，无关模块缓存不动。

frontend/tests/real-material-import.acceptance.mjs，8037全新临时DATA_DIR，原index/真实登录、实际Uppy多选组件及原图片POST上传1张隔离BMP，原确认页成功入库1、原任务中心已完成、Vue订阅实时显示；ZIP只打开真实离线Dashboard后关闭并确认卸载，没有ZIP上传/导入/清洗/AI/GT POST。返回素材与同项目任务、旧素材源管理和数据集仍可访问。最初最后一步用了不存在的旧选择器src422Search，截图证明旧页面正常；按真实src422Q修正断言，重置临时fixture后单条入口用例通过。没有放宽断言。

六宽1920/1600/1440/1366/1024/768截图6张及原任务/HTTP/布局收据保存在仓库外delivery-evidence/20261117/P1W-real-entry；768真实查看，文档宽度无溢出，紧凑四列表格正常，原任务dock仍唯一。真实上传仅上述隔离临时库文件，不操作生产。没有重复跑ZIP引擎、500/20万素材、训练、转换或清洗全链路。

## 未验证与交付

本轮未执行ZIP字节上传/解析/标签提交/取消回滚真实链路、正式清洗/删除、Provider推理、GT修改；这些保留原Owner和既有合同，不能宣称本轮现场验证。离线正式安装、目标生产/硬件未验证。准确新SHA GitHub Actions、其离线制品上传及源码包包含须后续核验；本地构建成功不代表离线部署完成。

后端没有新接口/Repository/schema。后续合理边界仍Material Router→原Upload/Zip/治理Service→MaterialRepository/原Worker，当前没有证据需要机械抽app.py。未来异构架构约束保持，无硬件适配。下一P1X原AI创建/任务操作；P1Y/P1Z未完成，继续授权开发。

补充CI实际失败核对：d9b3ff2的Frontend unit另有4个入口合同失败，前三处正则转义版本617期望未随618更新，第四处仍期望上一callback修改前material-batches缓存。仅更新精确期望到本批619和20261117callback1，保留三入口相等、单调及所有lazy/Owner断言。原CI跳过Vue构建且无Vue artifact，已记录UNAVAILABLE，不声称有该SHA离线资源。7195仅确认用例修复，不包含本次缓存期望修正，本批准确SHA再验。
