# 畅联云前端 13B-03：集中关闭的焦点恢复与轮询收尾

时间：2026-11-13；唯一长期分支：`feature/external-algorithm-publishing`。

## 基线与来源

前置 13B-02 提交 `1cd5136cc0ddbdbb8cab8520c8d0eccc53d2198d` 的 **41/41 GitHub Actions 全部成功**，包括 Frontend Runtime Stabilization 浏览器回归。本轮开始时远端 HEAD 等于该 SHA。

## 确认的缺口

`closeModalStackCore424()` 对单个顶层弹窗调用 `restoreModalFocus424(top)` 或 `restoreModalFocus424(baseModal)`；公开的 `closeAllModals424()` 却只执行关闭前清理及节点移除，遗漏恢复焦点，导致顶层焦点可能停留在已经移除的节点或落到 body。

此外 `closeModalCanonical420()` 会在正常关闭前调用 `beforeCloseStorageImport61()`，而 `closeAllModals424()` 旁路了这一存储导入轮询取消钩子。这是集中关闭路径的两个静态可复核差异，不等同于宣称已复现生产环境的全部滚动问题。

## 最小修复

- 不改变单个弹窗关闭函数、保存过程或 Modal Stack 的创建/层级；
- 集中关闭前调用一次 `beforeCloseStorageImport61?.()`，保持存储导入轮询的既有清理合同；
- 保留每层 `beforeCloseModal424()`，按旧顺序删除动态层，清理已经丢弃层的焦点引用；
- 集中关闭结束后仅恢复最外层弹窗入栈前保存的焦点，不向已销毁的子层依次恢复；
- 继续以一个 Modal/Navigation/Request Owner 工作，不新增锁、监听器、计时器或全局状态；
- 更新 `app.js`、`main.mjs`、`styles.css` 一致的纯数字缓存键为 `42.25.597`，并同步两处已有静态断言，正式 VERSION 不变；
- 在现有前端单元测试添加集中关闭清理/顺序守卫，在真实 Chrome 通过父子层＋聚焦按钮验证焦点恢复、无孤儿层、导入清理仅一次。

## 边界

本轮不得部署 A800/4070，不能将 CI 通过等同生产验收。此处 `closeAllModals424()` 是同步强制退场接口，**不替代正常标注弹窗的异步保存关闭协议**；脏标注保存仍必须走原 `closeModalCanonical420()`。

若本提交 CI 或浏览器测试失败，先看对应 job 日志再精准修复；不进行新的 20k/200k 压测。回滚为撤销本次单提交，无数据库/GT 迁移。
