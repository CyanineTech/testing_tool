# 历史案例：主机重启后恢复，但重启前 backend / supervisor 链路已断

## 适用范围

- RCS 主机出现“死机”“卡死”“重启后恢复正常”，但需要追溯重启前到底是什么链路先坏了。
- 适用于飞书、现场或事后复盘中，用户描述偏向“当时死机了，重启后表面恢复，但要查根因”的场景。

## 历史复盘优先

- 这类问题如果已经恢复，优先固定故障时间、重启时间或请求失败时间，再回看对应历史日志。
- 不要直接拿当前端口、当前容器或当前进程状态替代历史主机故障证据。
- 当前状态只适合作为补充，历史时间窗口内的调用链、服务链和依赖链证据更关键。

## 典型现象

- 主机重启后表面恢复，当前 `docker ps`、端口、容器状态可能看起来都还行。
- 如果只看当前状态，会误判成“暂时没问题”或者把重启后的状态当成故障证据。
- 真正有价值的证据通常在上一个 `boot` 的 `supervisor`、`backend`、`kernel`、`docker` 日志里。

## 这类问题的正确查法

1. 先确认当前开机时间和最近 boot 历史，不要直接拿当前状态下结论。
2. 再看上一个 `boot` 的：
   - `journalctl -u supervisor -b -1`
   - `journalctl -u docker -b -1`
   - `journalctl -k -b -1`
   - `backend` 相关日志
3. 如果 `3737` 在重启前未监听，同时 `supervisor` 出现 `master_backend` / `cbs_master_server` 异常退出、等待结束、反复拉起失败，更应优先判断为 backend / supervisor 拉起链路异常。

## 本次确认到的高价值线索

- 重启前 `3737` 端口未监听，说明主业务 backend 当时没有正常提供服务。
- `supervisor` 历史日志出现 `master_backend`、`cbs_master_server` 相关退出或等待结束记录。
- `MySQL` 容器可能仍在运行，但探活账号 / 鉴权方式不匹配，这不应直接等价成“数据库宕机”。
- 如果上一个 `boot` 的 `kernel` / `docker` 日志没有明显异常，更应优先聚焦应用层和守护进程拉起链路，而不是先怀疑系统级崩溃。

## 判定口径

- 如果重启前 `3737` 未监听，同时 `supervisor` 里有 `master_backend` / `cbs_master_server` 异常线索：
  - 优先判定为 backend / supervisor 拉起链路异常。
- 如果 `MySQL` 容器运行，但探活报 `Access denied`：
  - 优先判定为探活鉴权不匹配，不能直接等价成数据库已挂。
- 如果 `kernel` / `docker` 历史日志没有明显系统级报错：
  - 更像应用层服务链路问题，而不是整机内核级故障。

## 常见检索词

- 主机死机重启后恢复
- 主机重启后好了但要查根因
- 3737 未监听
- master_backend 异常退出
- cbs_master_server waiting for
- supervisor waiting for master_backend to die
- backend 拉起失败
- 历史重启问题

## 处理建议

1. 先固定重启前的 boot 时间窗口，再做复盘，不要直接引用当前状态。
2. 优先把 `supervisor` 中 `master_backend` / `cbs_master_server` 的异常行提取出来，作为主线证据。
3. 再确认 `3737` 在重启前是否未监听，验证 backend 是否真正掉了服务。
4. 把 `MySQL` 容器状态和探活鉴权问题分开看，避免误判。
5. 修复后要复测同类任务链路，确认不是“重启掩盖了问题”。

## 参考文档

- [rcs-backend-service-failure.md](rcs-backend-service-failure.md)
- [history-case-master-service-healthy-but-call-chain-broken.md](history-case-master-service-healthy-but-call-chain-broken.md)
- [http-or-grpc-call-chain-timeout.md](http-or-grpc-call-chain-timeout.md)
