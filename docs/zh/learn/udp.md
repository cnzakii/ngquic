---
title: 跑在 UDP 上
description: 在 localhost 的真实 UDP 套接字上运行回显示例，然后在 Linux 和 macOS 上改用 ngquic.udp 的批量 I/O。
source_commit: ab51bfa
---

# 在 UDP 上运行

学完本教程，第一篇教程中的回显示例会运行在 `127.0.0.1` 上的两个 UDP 套接字之上，由一个 `selectors` 循环驱动，在真实的单调时钟上等待数据报或下一个定时器。之后你会再写一个副本，改用 `ngquic.udp`，在 Linux 和 macOS 上批量完成套接字调用。

## 准备工作 {#before-you-start}

- 先完成[第一次握手](first-handshake.md)和[理解 sans-I/O 模型](protocol-model.md)。本教程使用同一个 `quic-tour` 目录，并导入[获取测试证书](first-handshake.md#get-a-test-certificate)一节中的 `localhost_certs.py`。
- 最后一节需要 Linux 或 macOS，其余部分在任何平台上都能运行。

## 在套接字上运行示例 {#run-the-exchange-over-sockets}

把下面的程序保存到 `quic-tour` 中，命名为 `udp_echo.py`，与 `localhost_certs.py` 放在一起：

```python title="udp_echo.py"
--8<-- "examples/udp_echo.py"
```

运行：

```console
python udp_echo.py
```

输出与内存版本相同，也是这三行：

```text
HandshakeCompleted(alpn_protocol='echo', session_resumed=False, early_data_accepted=False)
server received b'hello' on stream 0
StreamDataReceived(stream_id=0, data=b'HELLO', end_stream=True, early=False)
```

TLS 配置与第一篇教程相同。接下来的五节分部分讲解其余代码，代码都摘自 `udp_echo.py`；在[最后一节](#batch-system-calls-with-ngquicudp)之前不需要再输入任何代码。

## 为每个套接字创建 Endpoint {#give-each-socket-an-endpoint}

```python
--8<-- "examples/udp_echo.py:sockets"
```

每个套接字都绑定到端口 0，由系统挑选空闲端口；每个 `Endpoint` 通过 `getsockname()` 取得绑定后的地址。`Endpoint` 必须知道自己的真实地址，因为 ngtcp2 跟踪的每条路径都包含这个地址。套接字设为非阻塞，并注册到同一个选择器上，这样一个线程就能同时等待两个套接字。

程序把每个连接和发送它所用的套接字放在一起：客户端连接用客户端自己的套接字，服务器连接用其 `Incoming` 到达的那个套接字。

## 每次输入后都发送 {#send-after-every-input}

```python
--8<-- "examples/udp_echo.py:send"
```

`send_all()` 先发送各个 `Endpoint` 的无状态回复，再用 `sendto()` 发送每个连接的 `Transmit` 对象。除非你要求分段（[最后一节](#batch-system-calls-with-ngquicudp)会这样做），每个 `Transmit` 就是一个 UDP 载荷。

## 读完所有待读数据 {#read-everything-that-is-waiting}

```python
--8<-- "examples/udp_echo.py:receive"
```

`receive()` 一直读到套接字即将阻塞为止，把每个载荷连同发送方地址和当前时间交给 `Endpoint.receive_datagram()`。每次读取 65,535 字节，这样数据报就不会被截断。

## 等待数据报或定时器 {#wait-for-a-datagram-or-a-timer}

```python
--8<-- "examples/udp_echo.py:loop"
```

开始等待之前，循环向每个连接询问 `get_timer()`，把最早的截止时间换算成选择器的超时时间。等待结束后，截止时间已过的连接会被调用 `handle_timer()`。

如果等待因超时而结束，就把定时器原定的截止时间传给 `handle_timer()`：选择器或事件循环可能会稍早醒来，而早于截止时间的 `now` 不会触发任何动作。此时也不要重新调用 `get_timer()`，因为等待期间的输入可能已经把截止时间推后。

事件处理与第一篇教程相同。

## 关闭连接并释放套接字 {#close-and-release-the-sockets}

```python
--8<-- "examples/udp_echo.py:close"
```

`close()` 把 CONNECTION_CLOSE 放入队列，再调用一次 `send_all()` 把它发出去。随后程序直接退出，不再经历关闭期（closing period）。长期运行的程序则要继续驱动连接的定时器，直到连接进入 `ConnectionState.CLOSED`，做法见[上一篇教程](protocol-model.md)。

!!! warning "警告"
    QUIC 禁止 IP 分片（[RFC 9000 第 14 节](https://www.rfc-editor.org/rfc/rfc9000#section-14)）。普通套接字沿用系统设置，而各平台的默认设置并不相同。`ngquic.udp.UDPSocket` 会替你关闭分片。

## 用 ngquic.udp 批量完成系统调用 {#batch-system-calls-with-ngquicudp}

事件循环的数据报传输不会做批量 UDP 系统调用，`ngquic.udp` 补上了这一点，作用于你自己创建、绑定、等待和关闭的套接字。这个模块只在 Linux 和 macOS 上构建；在 Windows 上导入会失败，所以在 Windows 上请继续使用上面的普通套接字循环。

| 平台 | `UDPSocket` 增加的能力 |
| --- | --- |
| Linux | 分段发送（GSO，通用分段卸载）、用 `recvmmsg` 批量接收、合并接收（GRO，通用接收合并）、ECN（显式拥塞通知）、目的地址 |
| macOS | 在 C 中循环读取，不必返回 Python、ECN、目的地址；不支持 GSO 和 GRO |
| Windows | 不可用 |

把 `quic-tour` 中的 `udp_echo.py` 复制为 `udp_batched.py`，做四处修改，高亮的行就是改动的地方。第一，在顶部的导入中加上 `import sys`，然后在 `import ngquic` 下方的平台检查之后导入 `UDPSocket`：

```python hl_lines="1 2 4"
--8<-- "examples/udp_batched.py:imports"
```

第二，用 `UDPSocket` 包装每个套接字，并以它作为查找 `Endpoint` 的键。这段代码替换[为每个套接字创建 Endpoint](#give-each-socket-an-endpoint)一节中的代码：

```python hl_lines="5 6 9 10 13 14 16"
--8<-- "examples/udp_batched.py:sockets"
```

包装时，套接字会被设为非阻塞，并配置好 QUIC 所需的选项，所以 `setblocking()` 调用可以删去；此后套接字的选项都交给包装器管理。`UDPSocket` 提供 `fileno()`，选择器可以直接等待它。

第三，改为通过包装器收发。下面两段代码替换 `send_all()` 和 `receive()`：

```python hl_lines="3 5 7 8 9"
--8<-- "examples/udp_batched.py:send"
```

```python hl_lines="1 2 3 7"
--8<-- "examples/udp_batched.py:receive"
```

`UDPSocket.send()` 直接接受 `Transmit`，无需转换。`datagrams_to_send(gso=...)` 让一个 `Transmit` 携带多个大小为 `segment_size` 字节的载荷，`UDPSocket.gso` 表示内核是否会把它们拆开发送；在 macOS 上它为 `False`。

`UDPSocket.receive_into(endpoint, now)` 读取所有待读数据并交给 `Endpoint`，不必为每个数据报创建 Python 对象。它按到达顺序返回接收了数据报的连接和新的 `Incoming` 连接尝试，每个只出现一次。如果需要数据报本身，`receive()` 返回 `ReceivedDatagram` 对象，其字段正好是 `receive_datagram()` 的参数。

第四，在程序末尾关闭套接字本身。现在 `Endpoint` 以 `UDPSocket` 为键，而 `UDPSocket` 没有 `close()`：套接字仍要由你自己关闭。

```python hl_lines="4 5"
--8<-- "examples/udp_batched.py:close"
```

`receive()` 与关闭之间的循环保持不变。运行这个副本：

```console
python udp_batched.py
```

输出与 `udp_echo.py` 相同，也是这三行。

!!! note "备注"
    套接字缓冲区已满时，`UDPSocket.send()` 抛出 `BlockingIOError`，并且什么也不发送。发送量比本示例大的程序应等待套接字变为可写，再重新发送那个 `Transmit`。

## 下一步 {#next-steps}

- [发起 HTTP/3 请求](http3.md)：在同样的连接上发送请求和响应。
- `UDPSocket` 见[批量 UDP 参考](../reference/udp.md)，`get_timer()` 和 `handle_timer()` 见 [API 参考](../reference/connections.md)。
