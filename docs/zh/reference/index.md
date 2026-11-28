---
title: 概览
description: ngquic 的公开 Python API，按任务组织。
source_commit: ab51bfa
---

# API 参考

QUIC 接口在 `ngquic` 包中；HTTP/3 在构建于其上的 `ngquic.h3` 中；批量 UDP 系统调用在可选模块 `ngquic.udp` 中。所有方法都只处理内存中的状态：数据报和当前时间由你传入，返回的数据报由你发送。

| 要做的事 | 入口 |
| --- | --- |
| 监听或发起连接 | [`Endpoint`](connections.md#ngquic.Endpoint)、[`Endpoint.connect()`](connections.md#ngquic.Endpoint.connect) |
| 决定是否接受客户端的连接 | [`Incoming`](connections.md#ngquic.Incoming)：`accept()`、`retry()`、`refuse()`、`ignore()` |
| 交付收到的数据报 | [`Endpoint.receive_datagram()`](connections.md#ngquic.Endpoint.receive_datagram) |
| 取出待发送的数据报 | [`BaseConnection.datagrams_to_send()`](connections.md#ngquic.BaseConnection.datagrams_to_send)、[`Endpoint.datagrams_to_send()`](connections.md#ngquic.Endpoint.datagrams_to_send) |
| 驱动定时器 | [`get_timer()`](connections.md#ngquic.BaseConnection.get_timer)、[`handle_timer()`](connections.md#ngquic.BaseConnection.handle_timer) |
| 处理连接上发生的事件 | [`events()`](connections.md#ngquic.BaseConnection.events) 和[事件类](events.md) |
| 使用流和 DATAGRAM 帧 | [`Connection`](connections.md#ngquic.Connection) |
| 使用 HTTP/3 | [`H3Connection`](h3.md#ngquic.h3.H3Connection) |
| 配置 TLS | [`TLSContext`](tls.md#ngquic.TLSContext) |
| 调整传输层限制 | [`TransportConfig`](config.md#ngquic.TransportConfig)、[`EndpointConfig`](config.md#ngquic.EndpointConfig) |
| 处理错误 | [异常](errors.md)和 [`ConnectionTerminated`](events.md#ngquic.ConnectionTerminated) |
| 用 GSO 批量发送、用 GRO 批量接收 | [`ngquic.udp`](udp.md) |
