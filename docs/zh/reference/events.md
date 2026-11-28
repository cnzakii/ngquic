---
title: 事件
description: QUIC 连接报告的事件，按所涉及的对象分组。
source_commit: ab51bfa
---

# 事件

`BaseConnection.events()` 返回上次调用之后发生的事件。事件都是不可变对象，`repr()` 输出清晰易读；每个事件类都支持按主要字段做 `match` 匹配：

```python
for event in connection.events():
    match event:
        case ngquic.StreamDataReceived(stream_id, data, end_stream):
            ...
        case ngquic.ConnectionTerminated():
            ...
```

`H3Connection` 同样会报告下文的握手、路径、流状态和终止事件，`ngquic.h3` 也重新导出了它们；但请求数据通过 `ngquic.h3.DataReceived` 交付，DATAGRAM 帧通过 `ngquic.h3.DatagramReceived` 交付，详见 [HTTP/3](h3.md#events)。

::: ngquic.Event

## 握手与 TLS {#handshake-and-tls}

::: ngquic.HandshakeCompleted
    options:
      members: false

::: ngquic.HandshakeConfirmed

::: ngquic.ClientHelloReceived
    options:
      members: false

::: ngquic.PeerCertificateReceived
    options:
      members: false

::: ngquic.SessionTicketReceived
    options:
      members: false

::: ngquic.NewTokenReceived
    options:
      members: false

::: ngquic.EarlyDataRejected

## 流 {#streams}

::: ngquic.StreamDataReceived
    options:
      members: false

::: ngquic.StreamReset
    options:
      members: false

::: ngquic.StopSendingReceived
    options:
      members: false

::: ngquic.StreamClosed
    options:
      members: false

::: ngquic.StreamsAvailable
    options:
      members: false

::: ngquic.StreamWritable
    options:
      members: false

## DATAGRAM 帧 {#datagrams}

::: ngquic.DatagramReceived
    options:
      members: false

::: ngquic.DatagramAcknowledged
    options:
      members: false

::: ngquic.DatagramLost
    options:
      members: false

## 路径 {#paths}

::: ngquic.PathValidationStarted
    options:
      members: false

::: ngquic.PathValidated
    options:
      members: false

::: ngquic.PathDegrading

::: ngquic.PathRecovered

## 连接终止 {#termination}

::: ngquic.ConnectionTerminated
    options:
      members: false
