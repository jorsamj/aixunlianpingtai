# 权重元数据完整性精准修复

目标：按用户最新纠偏，六扩展字段尽力提供，未知省略而不阻断交付；复用原 ExternalPublicationRepository / ModelArtifactRepository / 发布 Owner，旧ID安全补齐、未知结果不盲写。

- [x] fetch/pull 干净长期分支93c56659；阅读已有发现、转换唤醒、DTO、同步/恢复/前端链路。
- [x] 原代码RED：旧SYNCED补齐、元数据变化、edit未知及矩形尺寸。初始字段强制齐全用例按用户纠偏撤回；纠偏前未交付代码另有5项非阻断合同RED，现已全部GREEN。
- [x] 原发布记录增加确认 payload 回执，成功 add/edit 或完整远端证据才写入；旧 Weight 用 edit，未知 edit 只读恢复；首次只读查询失败不冒充已发写请求。
- [x] 保留可信提取、矩形尺寸、冻结标签及真实文件身份校验；六字段未知省略、tags未知不发送[]。复用原ModelArtifact，Worker转换状态不变。
- [x] 原状态API和版本行展示事实、同步成功/可补充/未知，缺失仅提示，真实部分失败仍提示部分成功。
- [x] 聚焦两份Python发布/平台+转换Worker三文件194通过、相关Node41通过、一份Chrome3通过；末次schema/存量19通过，不扩展无关测试。
- [ ] 更新现有handoff，普通推送唯一长期分支，按最终SHA验收所有实际触发CI/Checks。

验证命令：python -m pytest -q tests/unit/test_external_algorithm_publish.py tests/unit/test_external_algorithm_platform.py；node --test tests/frontend/external-algorithm-publish.test.mjs；npx playwright test tests/browser/external-algorithm-publish.spec.mjs。
