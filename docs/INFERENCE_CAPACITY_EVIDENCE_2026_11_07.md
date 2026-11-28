# 推理容量运维证据合同（隔离开发；4070 未访问）

现有模型弹窗“推理容量”显示服务器策略，检查按钮调用
`POST /api/v35/model-configs/{id}/capacity-check`，返回当前配置指纹。
连接测试和真实图片验证继续使用原入口；成功不构成容量证据。
API 不接收可信容量字段，浏览器提交 `capacity_evidence` 或策略被忽略。

部署运维可设置 `INFERENCE_CAPACITY_MANIFEST` 指向只允许可信运维写入的 JSON。
该文件是**运维证明**，不是平台完成了真实双实例自动探测。不要把用户上传目录或可由
Web 用户写入的文件用作该路径。运维核验完成后才填写以下结构：

```json
{
  "configs": {
    "SAVED_CONFIG_ID": {
      "config_fingerprint": "FROM_CAPACITY_CHECK_API",
      "expires_at": 0,
      "mode": "native_gateway",
      "quota_scope": "OPERATOR_ASSIGNED_SHARED_BACKEND_ACCOUNT_SCOPE",
      "concurrency": 2,
      "max_attempts": 1,
      "total_retry_seconds": 30,
      "execution_deadline_seconds": 120,
      "request_load_balancing_verified": true,
      "instances": [
        {"instance_id": "ACTUAL_INSTANCE_A", "model_revision": "ACTUAL_IMMUTABLE_REVISION", "native_route_verified": true},
        {"instance_id": "ACTUAL_INSTANCE_B", "model_revision": "ACTUAL_IMMUTABLE_REVISION", "native_route_verified": true}
      ]
    }
  }
}
```

示例 expires_at=0 故意无效，须填写核验有效期的 Unix 秒数。运维须确认原生检测路由
确实请求级分流至不同实例、完全等价模型修订、并发执行和实际服务端执行截止（1～600秒）；
客户端 read timeout 不证明 GPU 已停止。单纯两条 URL、/models、GPU 名字或模型名不足。
当前执行仍向原配置网关发请求，没有后台修改服务，也没有隐式跨模型/跨 URL 回退。

云账户可用 `mode=cloud_quota`（火山、阿里、OpenAI兼容自定义云），须提供服务端
`quota_scope` 与已确认 concurrency/RPM。Ollama/OpenAI兼容本地服务用
`mode=service_quota`，另须 `service_capacity_verified=true` 和实际服务端执行截止。
这两种模式明确是运维确认的配额，不是平台推断 GPU 数量。

并发最大8、总尝试最多3（缺省1）、总重试预算最多30秒。请求准备时冻结策略和配置修订；
执行器必须根据冻结证据有效期降级，历史无策略任务保持1。保存配置/更换凭据会使旧指纹失效。
同后台及同已知账户使用同一不透明域；旧未知账户保守共享后台域。
quota_scope 只有在可信配置指纹匹配且字段合法时才作为额外身份约束生效；容量证明到期不删除该身份约束，扩容仍须完整有效证明，别名后台/跨模型共享账户应由运维分配同一 scope。

本地验证：策略单测11项、原模型配置API25项通过，Python编译和JS语法通过。新增真实 Chrome 隔离用例1项通过（Node24、8037端口、test-results-inference 输出），验证原弹窗容量区域、新建不可检查、已保存检查容量未知/并发1、保持单层弹窗。
没有访问或修改4070、A800、模型服务或生产数据；真实实例并行及图片质量尚待现场证据。

配额域采用层级许可：基础 domain 永远由后台及真实凭据的不可逆账户身份确定，证据失效不改变基础域。接受的 quota_scope 另产生 shared_domain；执行器必须原子取得基础域和共享域两项许可，避免有效/过期策略并存绕开后台限制。跨地址别名使用相同运维共享域。旧凭据引用在配置 Owner 读取时按实际凭据投影身份，不把密钥写入输出。
