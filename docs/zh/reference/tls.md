---
title: TLS
description: ngquic 连接的 TLS 1.3 配置。
source_commit: ab51bfa
---

# TLS

QUIC 连接都运行在 TLS 1.3 之上（[RFC 9001](https://www.rfc-editor.org/rfc/rfc9001)）。一个 `TLSContext` 服务于一种角色，保存证书、信任锚和 ALPN（应用层协议协商）协议，接口仿照 `ssl.SSLContext`；握手由 AWS-LC 完成。

::: ngquic.TLSContext

::: ngquic.ngtcp2_version

::: ngquic.tls_version
