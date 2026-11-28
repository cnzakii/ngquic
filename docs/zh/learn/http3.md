---
title: 第一个 HTTP/3 请求
description: 用 ngquic.h3 在内存中完成第一次 HTTP/3 请求和响应。
source_commit: ab51bfa
---

# 发起 HTTP/3 请求

学完本教程，你会得到一个脚本：HTTP/3 客户端发送 `GET /hello`，服务器返回 `200` 和一段简短的主体，然后客户端关闭连接。与第一篇教程一样，整个过程在内存中运行：HTTP/3 沿用同样的 `Endpoint`、数据报、事件和定时器，变化的只有流相关的方法。

## 准备工作 {#before-you-start}

- 先完成[第一次握手](first-handshake.md)。本教程使用同一个 `quic-tour` 目录，并导入[获取测试证书](first-handshake.md#get-a-test-certificate)一节中的 `localhost_certs.py`。
- HTTP/3 模块 `ngquic.h3` 已随 ngquic 一并安装，无需额外添加。

## 运行示例 {#run-the-exchange}

把下面的程序保存到 `quic-tour` 中，命名为 `http3_request.py`，与 `localhost_certs.py` 放在一起：

```python title="http3_request.py"
--8<-- "examples/http3_request.py"
```

运行：

```console
python http3_request.py
```

输出如下：

```text
server received GET /hello
client received 200
client received body b'Hello over HTTP/3\n'
server saw the client close: APPLICATION_ERROR 0x100
```

接下来的五节分部分讲解这个程序。代码都摘自 `http3_request.py`，不需要再输入。

## 在 TLS 中选择 h3 {#select-h3-in-tls}

```python
--8<-- "examples/http3_request.py:tls"
```

TLS 配置与第一篇教程只有一处不同：双方提供的 ALPN（应用层协议协商）协议是代表 HTTP/3 的 `h3`（[RFC 9114 第 3.2 节](https://www.rfc-editor.org/rfc/rfc9114#section-3.2)）。

## 获取 H3Connection {#ask-for-an-h3connection}

```python
--8<-- "examples/http3_request.py:connect"
```

向 `Endpoint.connect()` 传入 `h3=H3Config()`，得到的就是 `H3Connection` 而不是 `Connection`；服务器则向 `Incoming.accept()` 传入同样的参数。`H3Config` 的默认值适合大多数程序，它的字段用于配置 QPACK 动态表、可接受的最大标头节（header section）、扩展 CONNECT 和 HTTP 数据报。

`H3Connection` 的驱动方式与 `Connection` 完全相同：在 `Endpoint` 上调用 `receive_datagram()`，再在连接上调用 `events()`、`datagrams_to_send()`、`get_timer()` 和 `handle_timer()`。`exchange()` 就是第一篇教程中的数据报循环。只有流相关的方法不同：你收发的是请求和响应，HTTP/3 控制流和 QPACK 流由 ngquic 管理。

## 在服务器上处理请求 {#answer-requests-on-the-server}

```python
--8<-- "examples/http3_request.py:server"
```

`RequestReceived` 带有请求的 `stream_id` 和 `headers`；`headers` 由 `(name, value)` 字节对组成，`:method`、`:path` 等伪标头字段排在最前面。`end_stream=True` 表示请求没有主体；有主体的请求先以 `RequestReceived` 到达，随后是若干 `DataReceived` 事件。

服务器在请求所在的流上作答：`send_response()` 发送以 `:status` 开头的标头节，`send_data()` 发送主体。在最后一次调用中传入 `end_stream=True`，响应就结束了。以尾部字段（trailer）结尾的响应改用 `send_trailers()` 结束；如果主体分块已经发完，则用 `end_stream()` 结束响应。

## 发送请求并读取响应 {#send-the-request-and-read-the-response}

```python
--8<-- "examples/http3_request.py:client"
```

客户端收到 `HandshakeCompleted` 后发送请求。`send_request()` 接受请求必需的四个伪标头字段（[RFC 9114 第 4.3.1 节](https://www.rfc-editor.org/rfc/rfc9114#section-4.3.1)），打开一个新的请求流并返回流 ID。`end_stream=True` 表示后面没有主体。

响应先以带标头节的 `ResponseReceived` 到达，之后每个主体分块对应一个 `DataReceived`。主体可能分成任意多块到达，所以客户端不断追加 `event.data`，直到某一块带有 `end_stream=True`。如果有 `1xx` 信息响应，它会先以 `InformationalResponseReceived` 到达；尾部字段则以 `TrailersReceived` 到达。

## 关闭连接 {#close-the-connection}

```python
--8<-- "examples/http3_request.py:close"
```

关闭 HTTP/3 连接要使用 HTTP/3 错误码。`H3ErrorCode.H3_NO_ERROR`（`0x100`）表示没有出错（[RFC 9114 第 8.1 节](https://www.rfc-editor.org/rfc/rfc9114#section-8.1)）。服务器的 `ConnectionTerminated` 报告这个错误码时，`reason` 为 `CloseReason.APPLICATION_ERROR`，因为这个错误码属于应用协议，而不属于 QUIC。

!!! warning "警告"
    对端关闭连接或重置流时，使用的错误码可能不在 `H3ErrorCode` 中：未知错误码一律视为 `H3_NO_ERROR`（[RFC 9114 第 9 节](https://www.rfc-editor.org/rfc/rfc9114#section-9)）。请把 `error_code` 与枚举成员比较，不要用 `H3ErrorCode(...)` 转换每个值。

客户端用完连接后，像这个客户端一样直接关闭即可。服务器如果想停止接收新请求，又不中断正在处理的请求，就先调用 `send_shutdown_notice()`，过一两个往返时间（RTT）后再调用 `send_goaway()`，等 `is_drained` 为真时再关闭连接（[RFC 9114 第 5.2 节](https://www.rfc-editor.org/rfc/rfc9114#section-5.2)）。

## 下一步 {#next-steps}

- 要在 UDP 上运行，可以拿[在 UDP 上运行](udp.md)中的 `udp_echo.py`，向 `connect()` 和 `accept()` 传入 `h3=H3Config()`，再把其中的事件处理换成上面的 HTTP/3 处理逻辑。
- `H3Connection`、`H3Config`、HTTP/3 事件和 `H3ErrorCode` 见 [HTTP/3 参考](../reference/h3.md)。
