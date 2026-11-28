# 删除完成回执与训练标签刷新交错修复

CI重复在training-admission-governance.spec.mjs:132失败：服务器project-clear临时任务已SUCCEEDED，results四十项均succeeded/logical_removed=true，原训练草稿仍保留40张。不能以重跑掩盖。

原终态poll先通用refresh，再交TrainingMaterialSummaryRuntime.onMaterialBatchCompleted。通用刷新读取删除后的正式正样本摘要，TrainingLabelRuntime正确把失去证据的smoke标签清为[]。当这一步发生在results GET后的签名复核之前，同一操作的签名因此变化，原第二guard拒绝移除草稿ID。不是用户换项目/表单/选择，也不是Worker未删。

隔离真实原用例+仅浏览器延迟results真实响应300ms确认分支：前guard owns=true/labels smoke/IDs40；原label update清标签但IDs仍40；后guard owns=true、expected smoke/actual[]，因此return。自然不延迟时先移除再清标签可通过。没有伪造结果或改生产GT。

最小修复仅material-batches.js的DELETE_INDEX终态处理顺序：先await原有guarded回执核验，再项目身份栅栏，然后原通用refresh/治理invalidate。原回执分页、logical_removed核验、两次项目/root/task/草稿签名保护全部不变，迟到响应仍不得附着新草稿。无训练/删除API、Worker或数据库更改。

直接Node行为测试先RED再GREEN，原单文件9/9；原隔离Chrome project-clear/partial/late replacement三条3/3，受控300ms同例修复后1/1，未跑全仓。证据记录见仓库外delivery-evidence/20261117/admission-callback.json。一次测试误用默认Playwright输出清理了临时test-results；原trace丢失已明确记录，工具输出重建的事实不冒充原trace。后续所有浏览器输出须显式子目录，交付证据另存仓库外。准确修复SHA的CI推送后单独核验，不称旧失败SHA全绿。

本修复为CI实际暴露的训练创建回执同步问题，不更改GT引用保护/删除准入/调度/Worker。静态调用方缓存将在同轮P1V收尾统一更新，本中间提交不是生产部署包。
