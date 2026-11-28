---
title: Overview
description: A fast Sans-I/O QUIC and HTTP/3 library for Python, powered by ngtcp2 and nghttp3.
hide:
  - navigation
  - toc
---

<div class="nq-home" markdown>

<div class="nq-hero" markdown>
<div markdown>

<p class="nq-eyebrow">QUIC · HTTP/3 · Python</p>

# QUIC and HTTP/3 for Python, on the I/O you already have

<p class="nq-lede">
ngquic turns received datagrams into events and your calls into datagrams to
send. Your code owns the sockets, the event loop and the clock; ngtcp2,
nghttp3 and AWS-LC do the protocol work.
</p>

<div class="nq-actions" markdown>
[Start the tutorial](learn/first-handshake.md){ .md-button .md-button--primary }
[API reference](reference/index.md){ .md-button }
</div>

<div class="nq-install" markdown>

=== "uv"

    ```console
    uv add ngquic
    ```

=== "pip"

    ```console
    pip install ngquic
    ```

</div>

</div>

<figure class="nq-figure">
<svg viewBox="0 0 520 214" role="img" aria-labelledby="sansio-title sansio-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="sansio-title">The Sans-I/O boundary</title>
  <desc id="sansio-desc">Your program passes datagrams and the current time to ngquic; ngquic returns datagrams to send and events.</desc>
  <rect class="box" x="2" y="8" width="178" height="198" rx="12"/>
  <text class="title" x="22" y="42">Your program</text>
  <text class="item" x="22" y="78">UDP socket</text>
  <text class="item" x="22" y="104">event loop</text>
  <text class="item" x="22" y="130">clock</text>
  <text class="item" x="22" y="156">application logic</text>
  <rect class="core" x="340" y="8" width="178" height="198" rx="12"/>
  <text class="core-title" x="360" y="42">ngquic</text>
  <text class="item" x="360" y="78">QUIC connections</text>
  <text class="item" x="360" y="104">TLS 1.3 · AWS-LC</text>
  <text class="item" x="360" y="130">loss recovery</text>
  <text class="item" x="360" y="156">HTTP/3 · nghttp3</text>
  <path class="flow" d="M188 86 H326"/>
  <path class="flow-head" d="M334 86 l-10 -5 v10 z"/>
  <text class="label" x="261" y="74" text-anchor="middle">datagrams, now</text>
  <path class="flow" d="M332 134 H194"/>
  <path class="flow-head" d="M186 134 l10 -5 v10 z"/>
  <text class="label" x="261" y="156" text-anchor="middle">transmits, events</text>
</svg>
<figcaption>ngquic never opens a socket or reads a clock: you pass both in, and send what comes out.</figcaption>
</figure>

</div>

## Why ngquic

<div class="nq-cards" markdown>
<div class="nq-card" markdown>
<span class="nq-stat">4–80×</span>

### Fast

Handshakes complete about 4× faster than with the pure-Python
[aioquic](https://github.com/aiortc/aioquic); bulk data and requests move
[24–80× faster](https://github.com/cnzakii/ngquic#performance).
</div>
<div class="nq-card" markdown>
<span class="nq-stat">ngtcp2 · nghttp3</span>

### Built on proven engines

QUIC comes from [ngtcp2](https://github.com/ngtcp2/ngtcp2) and HTTP/3 from
[nghttp3](https://github.com/ngtcp2/nghttp3) (together, curl's only
[non-experimental HTTP/3 backend](https://curl.se/docs/http3.html)), and
TLS 1.3 from [AWS-LC](https://github.com/aws/aws-lc).
</div>
<div class="nq-card" markdown>
<span class="nq-stat">.pyi</span>

### Pythonic and typed

Immutable events with readable `repr()` and `match` support, Python
exceptions, and precise stubs for editors and type checkers.
</div>
<div class="nq-card" markdown>
<span class="nq-stat">sans-I/O</span>

### Fits any runtime

ngquic never opens sockets or starts an event loop, so the same code runs on
asyncio, threads, Trio, or in-memory tests.
</div>
</div>

## Sister libraries

ngquic has two siblings from the same author: Sans-I/O libraries for the
earlier HTTP versions, built the same way.

<!-- Each library publishes its logo at docs/overrides/assets/brand/<name>-logo.svg. -->
<div class="nq-family">
<a href="https://h11r.readthedocs.io/"><img src="https://raw.githubusercontent.com/cnzakii/h11r/main/docs/overrides/assets/brand/h11r-logo.svg" alt=""><strong>h11r</strong><span>HTTP/1.1, Rust core</span></a>
<a href="https://ngh2.readthedocs.io/"><img src="https://raw.githubusercontent.com/cnzakii/ngh2/main/docs/overrides/assets/brand/ngh2-logo.svg" alt=""><strong>ngh2</strong><span>HTTP/2, on nghttp2</span></a>
<a href="./" aria-current="page"><img src="assets/brand/ngquic-logo.svg" alt=""><strong>ngquic</strong><span>QUIC and HTTP/3, on ngtcp2</span></a>
</div>

</div>
