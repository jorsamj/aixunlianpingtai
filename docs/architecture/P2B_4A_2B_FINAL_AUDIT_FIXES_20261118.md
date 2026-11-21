# Payload 连续交付最终审计整改

原 HEAD / fetch 确认的远端：`6f9260163442a16d163c316f7b56f793d3fa0604`。唯一分支 `feature/external-algorithm-publishing`。本轮仅处理用户确认的三类 CI 根因和任务删除身份查询异常边界，不重做 P2A–P4，不改变 Task / Assignment / Execution Lease 权威。

## 实际根因与最小改动

1. `tests/unit/test_training_duplicate_conflicts.py` 两个直接调用 `_freeze_request_contract()` 的夹具只有 task_id / project_id。新合同在查询不可变收据前需要 payload_ref / attempt。改用真实 `TaskRecord.new()`，并写入其指向的 legacy 初始 Payload。真实 ArtifactStore 在没有发布收据时返回 `PUBLICATION_RECEIPT_MISSING`，原方法进入原 GT 冲突 / Test 泄漏检查。没有修改 `_freeze_request_contract()`，没有为身份提供任意默认值，没有删除证据、issue_count、原始 GT 来源和冻结文件不生成等断言。
2. `tests/api/test_data_fetch_targeted.py` 的旧 Repository 替身缺少 `deleted_task_ids()`，触发宽泛异常并跳过 Durable 状态覆盖。替身实现项目作用域的批量墓碑查询；额外加入一个已删除旧索引行，证明它被过滤，同时 RUNNING 覆盖 queued、progress=37、算法身份保留、无 N+1 / 全历史扫描断言保留。
3. `tests/browser/training-duplicate-conflicts.spec.mjs` 新训练任务已引用不可变版本，测试仍读固定 `payload.json`，得到 null。仅修改这一个新任务读取点：Repository.get(task_id) → 实际 payload_ref → ArtifactStore.read_json 验证式读取。浏览器单项实际证明 duplicate_review.excluded_image_ids 仍为 `['duplicate-copy']`，无需修改业务写入。legacy 历史 / 暂存 / 素材导入测试的 payload.json 不改。
4. `app.py::_v53_fast_jobs_summary()` 将 Repository 获取和墓碑查询移出补全数据的宽泛回退范围。删除身份不可核验时明确抛 HTTP 503，错误码 `TRAINING_TASK_DELETE_STATE_UNAVAILABLE`；不能返回未核验旧索引。身份已核验后，其他补全失败仍可回退已过滤的索引，不改缓存体系。
5. `app.py::_v53_live_jobs()` 对正常投影和旧索引回退都批量检查墓碑；核验失败同样 503。回退仅允许已验证未删除的行。保留 read_only、不重建全概览、不写旧索引及原返回列表合同；不增加逐任务查询。额外批量查询用于保证调用者提供的历史 context / 失败回退也受最终删除身份校验。

删除安全的回归包括 Repository 获取失败、墓碑 SQL 失败、正常 live 行过滤、投影失败后的旧索引过滤，以及墓碑查询成功后其他补全失败。前四个错误用例和两个过滤用例在修复前实际失败；修复后通过。查询失败不通过空列表伪装“没有任务”，而是让调用方获得明确可重试错误。校验是本次读取时的身份事实，不承诺跨任意并发删除的全局线性化概览。

## 定向验证

Windows / Python 3.12.7；均使用隔离测试库和测试服务器，没有生产操作。原三处问题都先在本地复现了与 CI 一致的错误。

| 实际命令 | 实际结果 |
|---|---|
| `D:/python/python.exe -m pytest tests/unit/test_training_duplicate_conflicts.py -q -k 'prepare_conflicting_gt or prepare_records_leakage' --disable-warnings --tb=short`（修改前） | 2 failed，均为缺 payload_ref |
| `D:/python/python.exe -m pytest tests/api/test_data_fetch_targeted.py -q -k fast_jobs_summary --disable-warnings --tb=short`（修改前） | 1 failed，queued 未被 running 覆盖 |
| `D:/python/python.exe -m pytest tests/api/test_data_fetch_targeted.py -q -k 'fails_closed or verifies_deletion' --disable-warnings --tb=short`（业务修复前） | 6 failed，复现不抛 503 / 已删行被返回 |
| `D:/python/python.exe -m pytest tests/unit/test_training_duplicate_conflicts.py tests/api/test_data_fetch_targeted.py -q --disable-warnings --tb=short` | 65 passed（训练重复 / 准备合同 54 项，概览当时 11 项） |
| `D:/python/python.exe -m pytest tests/api/test_data_fetch_targeted.py -q --disable-warnings --tb=short`（增加“已核验后补全失败”用例后） | 12 passed；包含上述 11 项，不重复计入总覆盖 |
| `D:/python/python.exe -m pytest tests/integration/test_remote_training_prepare_task.py tests/api/test_training_unified_task_overlay.py tests/api/test_training_read_only_legacy_maintenance.py tests/api/test_training_success_counts.py -q --disable-warnings --tb=short` | 62 passed；训练准备 / 恢复、删除保留、只读维护、概览与成功统计 |
| `$env:MC_BROWSER_TEST_PORT='8023'; npx playwright test tests/browser/training-duplicate-conflicts.spec.mjs --grep 'explicit exclusion remains auditable' --reporter=line` | 修改前 1 failed，duplicate_review 读自 null；修改后 1 passed（20.4s），真实本地 Chrome |
| `D:/python/python.exe -m py_compile app.py tests/unit/test_training_duplicate_conflicts.py tests/api/test_data_fetch_targeted.py` | 通过 |
| `node --check tests/browser/training-duplicate-conflicts.spec.mjs` | 通过 |
| `git diff --check` / 暂存 Diff 审查 | 通过 |

Python 不同定向集合去重共 128 项通过，Chrome 指定单项 1/1。未执行全仓 pytest、全仓浏览器或无关工作流重跑。浏览器仍验证排除审计、标注完全不变、素材 / 标注 revision 变化后 409、历史 insufficient_no_input_freeze、Test 内容泄漏；不是仅将读取异常改为忽略。

## 交付边界

业务修改仅 app.py 上述两个投影；另三个测试文件和两份本轮文档（本文、功能保留台账）。未改 CI、VERSION、Scheduler、Payload 发布实现、前端业务或数据库 Schema。原三份未提交设计文档保留，不提交。

任务简单且范围明确，本轮未新增子 Agent；主模型完成实际 Diff 复核、定向验证和 Git 交付，避免重复上下文传递及全仓审计。

提交推送后按根 AGENTS 异步规则只查询准确最终 SHA 一次，不手动重跑工作流。最终 SHA 与该次 CI 快照在交付回复中列出；本文提交时不预先宣称 CI 通过。用户提供的旧 SHA 46 成功 / 6 失败不能作为新 SHA 结果。

本地确认的指定问题均已修正；最终 CI 尚需准确 SHA 的结果确认。历史版本空间 GC、掉电耐久性和真实 GPU / 生产验证仍不属于本轮，不改变前轮已明确的限制。本轮结束后停止扩展，等待 GPT 独立核对。
