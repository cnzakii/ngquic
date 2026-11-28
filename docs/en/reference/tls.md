---
title: TLS
description: TLS 1.3 configuration for ngquic connections.
---

# TLS

Every QUIC connection runs TLS 1.3 ([RFC 9001](https://www.rfc-editor.org/rfc/rfc9001)). A `TLSContext` holds certificates, trust anchors and ALPN protocols for one role, in the shape of `ssl.SSLContext`; ngquic uses AWS-LC for the handshake.

::: ngquic.TLSContext

::: ngquic.ngtcp2_version

::: ngquic.tls_version
