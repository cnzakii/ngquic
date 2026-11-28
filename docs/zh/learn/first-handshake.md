---
title: 第一次握手
description: 安装 ngquic，然后在内存中运行一个 QUIC 客户端和服务器，完成握手并回显一个流。
source_commit: ab51bfa
---

# 完成第一次握手

学完本教程，你会得到一个 Python 脚本：其中的 QUIC 客户端和 QUIC 服务器完成 TLS 1.3 握手，服务器把一个流上收到的数据转成大写后发回。整个过程不打开任何套接字，每个数据报都由你的代码从一端交给另一端；ngquic 对真实程序的要求也正是如此。

## 准备工作 {#before-you-start}

- CPython 3.10 或更高版本，以及一个终端。

## 安装 ngquic {#install-ngquic}

为这几篇教程新建一个目录，在其中安装 ngquic。后面各页的脚本都放在这个目录里。

=== "uv"

    ```console
    uv init --bare quic-tour
    cd quic-tour
    uv add ngquic
    ```

    教程中用 `python` 运行脚本；在 uv 项目里请换成 `uv run`，例如 `uv run first_handshake.py`。

=== "pip"

    ```console
    mkdir quic-tour
    cd quic-tour
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install ngquic
    ```

    在 Windows 上，用 `.venv\Scripts\activate` 激活虚拟环境。

wheel 已打包 ngtcp2、nghttp3 和 AWS-LC，覆盖 Linux、macOS 和 Windows，无需安装任何系统库。

## 获取测试证书 {#get-a-test-certificate}

QUIC 总是运行在 TLS 1.3 之上（[RFC 9001](https://www.rfc-editor.org/rfc/rfc9001)），所以即使是本地测试也需要服务器证书。把下面的文件保存到 `quic-tour` 中，命名为 `localhost_certs.py`，后面每篇教程都会导入它。文件里有一张签发给 `localhost` 和 `127.0.0.1` 的证书、为它签名的证书颁发机构（CA），以及函数 `cert_chain_files()`，用于把证书和密钥写入临时目录。

```python title="localhost_certs.py"
--8<-- "examples/localhost_certs.py"
```

!!! warning "警告"
    这个文件里的私钥是公开的，只能用于这些示例；真实的服务器要加载自己的证书和密钥。

## 运行示例 {#run-the-exchange}

把下面的程序保存到 `quic-tour` 中，命名为 `first_handshake.py`，与 `localhost_certs.py` 放在一起：

```python title="first_handshake.py"
--8<-- "examples/first_handshake.py"
```

运行：

```console
python first_handshake.py
```

输出如下：

```text
HandshakeCompleted(alpn_protocol='echo', session_resumed=False, early_data_accepted=False)
server received b'hello' on stream 0
StreamDataReceived(stream_id=0, data=b'HELLO', end_stream=True, early=False)
```

接下来的三节逐段讲解这个程序。其中的代码都摘自 `first_handshake.py`，不需要再输入。

## 在两端配置 TLS {#configure-tls-on-both-sides}

```python
--8<-- "examples/first_handshake.py:tls"
```

每个 `TLSContext` 只用于一种 `Role`。`load_cert_chain()` 像 `ssl.SSLContext` 一样从文件读取服务器的证书和密钥，返回之后证书文件就可以删除。客户端信任为该证书签名的 CA，CA 证书以字符串形式通过 `load_verify_locations(cadata=...)` 传入。

两个上下文都调用了 `set_alpn_protocols()`。QUIC 要求双方在握手期间商定应用协议（[RFC 9001 第 8.1 节](https://www.rfc-editor.org/rfc/rfc9001#section-8.1)），商定不成，握手就会失败。`echo` 是本示例随意起的名字，HTTP/3 用的是 `h3`。

## 创建 Endpoint 并启动客户端 {#create-endpoints-and-start-the-client}

```python
--8<-- "examples/first_handshake.py:connect"
```

一个 `Endpoint` 代表一个本地 UDP 地址。它按连接 ID 把收到的数据报交给对应的连接；在服务器上，它还会报告新的连接尝试。这里的地址只起标识作用，并没有绑定到任何套接字。

`Endpoint.connect()` 创建客户端的 `Connection`，并把首轮要发送的数据包放入队列。它通过 `now` 参数接收当前时间；ngquic 中凡是可能启动或运行定时器的调用都要传入 `now`。`server_name` 会在 TLS 握手中发送，并用来与服务器证书比对。

## 传递数据报并处理事件 {#carry-datagrams-and-handle-events}

```python
--8<-- "examples/first_handshake.py:loop"
```

循环每一轮都做同样的三件事：

1. `datagrams_to_send(now)` 返回连接此刻要发送的 `Transmit` 对象。每个对象的 `data` 是一个 UDP 载荷，`remote_addr` 是目的地址。
2. 另一端的 `Endpoint.receive_datagram()` 接收载荷、载荷的来源地址和 `now`。遇到新连接的第一个数据报时，它返回一个 `Incoming`，服务器用自己的 TLS 上下文调用 `accept()`，得到服务器端的 `Connection`。
3. `events()` 按协议顺序返回上次调用之后发生的事件。

客户端这一侧的握手完成时，客户端会收到 `HandshakeCompleted`，其中带有双方商定的 ALPN（应用层协议协商）协议。随后客户端用 `open_stream()` 打开一个流，以 `end_stream=True` 发送 `b"hello"`，同时结束自己这一方向的发送。流 0 是客户端打开的第一个双向流（[RFC 9000 第 2.1 节](https://www.rfc-editor.org/rfc/rfc9000#section-2.1)）。

服务器收到 `StreamDataReceived` 后，在同一个流 ID 上回复。客户端收到带 `end_stream=True` 的 `StreamDataReceived`，就说明回复已经完整。

!!! note "备注"
    这个循环从不等待，因此没有处理定时器。没有丢包，也就不需要重传。下一篇教程会补上真实程序必须运行的定时器。

## 小结 {#recap}

- 两端各有一个 `TLSContext`，提供相同的 ALPN 协议。
- 每个本地地址对应一个 `Endpoint`；`connect()` 发起客户端连接，`Incoming.accept()` 建立服务器端连接。
- 你的代码把 `datagrams_to_send()` 返回的每个 `Transmit` 交给另一端的 `receive_datagram()`，再读取 `events()`。

## 下一步 {#next-steps}

- [理解 sans-I/O 模型](protocol-model.md)：加入定时器，关闭连接，并说明哪些工作归你的程序负责。
- `Endpoint`、`Connection` 和 `Incoming` 见 [API 参考](../reference/connections.md)，`TLSContext` 见 [TLS 参考](../reference/tls.md)。
