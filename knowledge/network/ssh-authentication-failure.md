# SSH 认证失败但网络可达

## 适用范围
- 目标设备可以 ping 通，但 SSH 登录失败、脚本自动化执行失败或只卡在认证阶段。
- 适用于“手工 SSH 能输密码，自动化命令失败”这类场景。

## 历史复盘优先

- 网络问题大多发生在某个时间窗口或某段路线中，优先固定掉线时间、恢复时间和对应位置。
- 不要因为当前能 ping 或能 SSH，就直接排除当时的历史网络异常。
- 应优先回看对应时间段的 WiFi、VPN、SSH、系统日志和现场网络变化。

## 典型现象
- `ping` 正常，但 `ssh -o BatchMode=yes` 失败。
- 飞书远程取证失败，但用户手工 `ssh robot@<主机>` 能登录。
- 脚本提示认证失败、权限不足或 host key 问题。
- 网络看起来正常，但自动排障链路拿不到远程结果。

## 优先检查
1. 先区分是网络不可达还是仅 SSH 认证失败，不要把两者混为一谈。
2. 检查 `ping <主机>`、`ssh robot@<主机>`、`ssh -o BatchMode=yes robot@<主机>` 三者差异。
3. 检查本机是否可用 `sshpass`，以及目标主机是否需要密码认证。
4. 再检查 host key、用户权限和主机名解析是否异常。

## 关键日志
- `scripts/network_diag.sh` 输出
- `ssh -v robot@<主机>`
- `ping <主机>`
- `~/.ssh/known_hosts`

## 常见检索词
- ssh 认证失败
- ssh 密码不对
- BatchMode 失败
- 手工 ssh 可以自动不行
- 远程取证失败
- host key 变了

## 判定口径
- 如果 `ping` 正常而 `ssh` 失败，更像认证或 known_hosts 问题。
- 如果 `ping` 也不正常，更像基础网络问题，不应先处理认证。

## 常见根因
- 自动化场景禁用交互输入，导致密码认证无法进行。
- `sshpass` 缺失或脚本未正确带上密码。
- `known_hosts` 中记录过期，触发 host key 校验失败。
- 用户、密码或权限与现场设备不一致。

## 处理建议
1. 先确认目标网络可达，再继续排认证问题。
2. 如果手工 SSH 可用而自动化不可用，优先补 `sshpass` 或改认证方式。
3. 如果是 host key 冲突，确认目标主机无误后再处理 known_hosts。
4. 修复后重试脚本和飞书远程取证，确认自动链路也恢复。

## 参考文档
- [README.md](README.md)
- [network-connectivity-failure.md](network-connectivity-failure.md)
- [../system-architecture.md](../system-architecture.md)
