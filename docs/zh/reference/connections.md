---
title: 端点与连接
description: ngquic 中的 Endpoint、传入的连接尝试和 QUIC 连接。
source_commit: ab51bfa
---

# 端点与连接

一个 `Endpoint` 对应一个本地地址，负责把数据报分发给它的连接。客户端调用 `Endpoint.connect()` 得到连接；服务器每遇到一个新客户端都会得到一个 `Incoming`，再决定如何处理。各部分如何协作，见[协议模型](../learn/protocol-model.md)。

## Endpoint {#endpoint}

::: ngquic.Endpoint

::: ngquic.Incoming

::: ngquic.Transmit

## 连接 {#connections}

`Connection` 和 [`H3Connection`](h3.md#ngquic.h3.H3Connection) 都继承 `BaseConnection` 的全部功能。`Connection` 在此基础上提供流和 DATAGRAM 帧，供直接使用 QUIC 的应用调用。

::: ngquic.BaseConnection

::: ngquic.Connection

::: ngquic.ConnectionState
    options:
      members: false

## 地址与统计 {#addresses-and-statistics}

::: ngquic.Address

::: ngquic.ConnectionStats
    options:
      members: false

::: ngquic.TransportParameters
    options:
      members: false

::: ngquic.PreferredAddress
    options:
      members: false
