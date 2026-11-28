---
title: 批量 UDP
description: 在你自己的套接字上进行批量 UDP 系统调用，适用于 Linux 和 macOS。
source_commit: ab51bfa
---

# 批量 UDP

`ngquic.udp` 提供事件循环的数据报传输做不到的系统调用：分段发送（GSO，通用分段卸载）、合并接收与批量接收（GRO，通用接收合并；`recvmmsg`），以及 ECN（显式拥塞通知）和源地址控制消息。协议核心不依赖这个模块。

!!! note "支持的平台"

    本模块只在 Linux 和 macOS 上构建。在 Windows 上，`import ngquic.udp` 会抛出 `ImportError`，请改用事件循环自带的数据报传输。

::: ngquic.udp.UDPSocket

::: ngquic.udp.ReceivedDatagram
