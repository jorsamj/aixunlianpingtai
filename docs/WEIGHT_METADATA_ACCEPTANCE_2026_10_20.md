# 新畅联权重补充元数据｜2026-10-20 接续验收

## 最终合同

以用户最后纠偏为准：imageWidth、imageHeight、yoloVersion、fileSize、fileSha256、tags 都是可选补充信息。可信则发送，未知则省略；tags未知绝不发送[]清空远端。缺失仅影响详情完整度，不影响上传、登记、同步成功或转换任务成功。真正文件身份不符、必要映射/上传/接口错误继续失败，转换Weight真正失败时Version显示部分成功。

本轮不调用真实新畅联业务接口、不操作生产OSS/S3、不执行真实转换/部署、不修改历史模型或训练数据。

## 基线与原有能力

完整fetch/pull feature/external-algorithm-publishing；实际基线93c56659698eeab639dc01d0d7bf0485a43e2bdd，工作树干净、远端一致。VERSION保持42.24.358。app/styles保持42.25.402；仅main入口变42.25.403，两个改动模块import缓存递增。

已有功能保留：官方add/edit接口、六扩展字段提取、真实产物大小/SHA、冻结标签与可信Snapshot恢复、best.pt版本血缘、原始权重先发布/转换稍后追加、芯片子分类映射、ModelArtifact上传与真实源文件校验、唯一发布Owner及转换完成唤醒。

## 已复现缺口与修复

1. 旧SYNCED直接返回且publication_requires_sync不比较补充字段。现有ExternalPublicationRepository映射增加synced_payload_json，记录成功add/edit的实际请求或完整远端证据；新事实出现触发原ID edit。比较本次已知字段子集，信息减少不触发清空或反复更新。远端列表省略字段时使用已确认回执，不把缺字段当失败。
2. edit超时仅按基础四字段确认，可能把未提交的补充字段记为SYNCED。现在核对本次实际发送字段，缺证据保持UNKNOWN；后续只读恢复，不盲目再次edit/add。新增前查询失败与已发写请求的未知结果分开，网络恢复不会永久阻止首次登记。
3. 无ID新增结果未知、列表暂时空时可能再次add。现在写请求发出前持久化UNKNOWN；重试等待唯一Weight ID，恢复后继续原链路，不重复建Version/Weight。
4. 原始训练矩形imgsz未提取、转换tuple维度顺序混用。现在按(height,width)及显式input_width/input_height解析，不截断非法浮点，不猜640。label_codes与class_id排序schema不一致时tags省略；不从当前项目标签补齐。
5. 状态缺少逐Weight事实且前端统一提示全部同步。现在在原版本行展示状态表，无新增按钮/弹窗/轮询Owner；每项显示真实尺寸、型号、目标、芯片、大小、SHA、标签，缺失只标“部分扩展信息未提供”。真实last_error单独展示，不被补充信息提示覆盖。已发布按钮仍可查看只读状态。

用户纠偏后，未交付阶段的强制元数据门禁、BLOCKED_METADATA及按缺字段产生PARTIAL的分支已全部移除。

## 聚焦测试与证据

本地Windows/Python3.12.7/Node20.12.2/系统真实Chrome。全部外部发布测试使用既有明确隔离客户端与本地文件Provider，不能当成生产API/OSS实测。

- Python：tests/unit/test_external_algorithm_publish.py、test_external_algorithm_platform.py、test_conversion_tasks.py，194 passed / 0 failed / 0 skipped；5项已有依赖弃用警告。
- 末次新旧schema/存量与可选合同聚焦：19 passed / 90 deselected，非跳过失败测试。
- Node：external-algorithm-publish、algorithm-list-runtime、version-marker-owner，41 passed / 0 failed / 0 skipped。
- Chrome：tests/browser/external-algorithm-publish.spec.mjs，3 passed；真实浏览器检查核心身份阻止POST、可选缺失允许POST、内联已知事实/缺失提示、成功反馈。UI接口fixture明确为隔离合同，不声称真实新畅联已写入。
- RED：基线旧SYNCED补齐、元数据变化、edit未知、矩形问题先失败；未知新增重复与重发现核对另有2项RED。用户纠偏前未交付实现的5项可选合同先RED后GREEN，最终不再要求字段齐全。
- 基线两文件175 passed / 1 failed：发布唤醒Event被真实后台Owner竞争消费。测试现在观察真实Event.set发出次数并保留原调用、持久标记与消费后无重复信号检查；不修改生产唤醒逻辑、不删除或放宽发布断言。中途其余失败为新增测试夹具补全和调用签名问题，均在最终范围内复验关闭，无跳过。

覆盖全字段键名、训练800/转换640及640×384、RK3568/RK3576、YOLO11n/s、best.pt多代、冻结标签与当前项目标签不同、Snapshot损坏/类别映射不一致、目标文件实际大小与SHA/同大小内容漂移、旧ID edit、零无意义重复写、超时/未知/唯一ID恢复、一次训练+稍后转换只建1Version/2Weights、核心字段与缺型号/类别/尺寸均可成功、未知tags不清空远端、芯片映射/存储/源文件错误等既有安全边界。

原始日志位于C:/Users/jorsam/.codex/tmp/：wp-base-1020.log、wp-red-1020.log、wp-boundary-red-1020.log、wp-optional-red-1020.log、wp-optional-green-1020.log、wp-python-final-1020.log、wp-last-schema-1020.log、wp-node-final-1020.log、wp-chrome-final-1020.log。

公开Apifox add/edit Markdown只读取得200，字段名与本地DTO核对；未调用真实业务接口。样本存于wp-openapi-add-1020.md和wp-openapi-edit-1020.md。必选策略以用户最后明确合同为准。

## 最终SHA与生产边界

提交后最终完整SHA、全部实际触发Actions/分页Checks与关键Job结果将记录在独立验收附件：C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/weight-metadata-acceptance-20261020.md，不能借用93c56659的绿色。

未运行无关本地全仓库测试，遵循用户“禁止测试发散”。真实新畅联对可选字段的业务响应、生产旧Weight/历史模型来源、OSS/S3长期地址与目标硬件加载仍待单独现场验证。现有成功转换/硬件待验证状态未改；发布登记成功不代表实机验证通过。

## 首次SHA CI修正

- 首次SHA 6f83076f的CI发现精简Job缺TestClient依赖、浏览器文本守卫未适配参数化；仅补httpx2及更新守卫匹配，保留核心身份零POST断言与全部实际测试。最终SHA重新验收。
External Publish实际Chrome 3 passed；失败发生在后置文本守卫。SQL发布合同108 passed/1依赖导入失败，Publish合同199 passed/1相同依赖导入失败；没有删除测试或降低断言。
