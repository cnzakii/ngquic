---
title: 概览
description: 快速的 Sans-I/O QUIC 与 HTTP/3 Python 库，基于 ngtcp2 和 nghttp3。
hide:
  - navigation
  - toc
---

<div class="nq-home" markdown>

<div class="nq-hero" markdown>
<div markdown>

<p class="nq-eyebrow">QUIC · HTTP/3 · Python</p>

# 在你自己的 I/O 上运行 QUIC 与 HTTP/3

<p class="nq-lede">
ngquic 把收到的数据报转换为事件，把你的调用转换为待发送的数据报。套接字、事件循环和时钟都由你的代码掌控，协议层的工作交给 ngtcp2、nghttp3 和 AWS-LC。
</p>

<div class="nq-actions" markdown>
[开始教程](learn/first-handshake.md){ .md-button .md-button--primary }
[API 参考](reference/index.md){ .md-button }
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
  <title id="sansio-title">Sans-I/O 的边界</title>
  <desc id="sansio-desc">你的程序把数据报和当前时间交给 ngquic；ngquic 返回待发送的数据报和事件。</desc>
  <rect class="box" x="2" y="8" width="178" height="198" rx="12"/>
  <text class="title" x="22" y="42">你的程序</text>
  <text class="item" x="22" y="78">UDP 套接字</text>
  <text class="item" x="22" y="104">事件循环</text>
  <text class="item" x="22" y="130">时钟</text>
  <text class="item" x="22" y="156">应用逻辑</text>
  <rect class="core" x="340" y="8" width="178" height="198" rx="12"/>
  <text class="core-title" x="360" y="42">ngquic</text>
  <text class="item" x="360" y="78">QUIC 连接</text>
  <text class="item" x="360" y="104">TLS 1.3 · AWS-LC</text>
  <text class="item" x="360" y="130">丢包恢复</text>
  <text class="item" x="360" y="156">HTTP/3 · nghttp3</text>
  <path class="flow" d="M188 86 H326"/>
  <path class="flow-head" d="M334 86 l-10 -5 v10 z"/>
  <text class="label" x="261" y="74" text-anchor="middle">数据报 + now</text>
  <path class="flow" d="M332 134 H194"/>
  <path class="flow-head" d="M186 134 l10 -5 v10 z"/>
  <text class="label" x="261" y="156" text-anchor="middle">Transmit + 事件</text>
</svg>
<figcaption>ngquic 从不打开套接字，也不读取时钟：两者都由你传入，产出的数据报也由你发送。</figcaption>
</figure>

</div>

## 为什么选择 ngquic {#why-ngquic}

<div class="nq-cards" markdown>
<div class="nq-card" markdown>
<span class="nq-stat">4–80×</span>

### 高性能

握手速度约为纯 Python 实现 [aioquic](https://github.com/aiortc/aioquic) 的 4 倍，大块数据传输和请求处理快 [24 倍～80 倍](https://github.com/cnzakii/ngquic#performance)。
</div>
<div class="nq-card" markdown>
<span class="nq-stat">ngtcp2 · nghttp3</span>

### 基于成熟的协议实现

QUIC 由 [ngtcp2](https://github.com/ngtcp2/ngtcp2) 实现，HTTP/3 由 [nghttp3](https://github.com/ngtcp2/nghttp3) 实现（二者组成 curl 唯一的[非实验性 HTTP/3 后端](https://curl.se/docs/http3.html)），TLS 1.3 由 [AWS-LC](https://github.com/aws/aws-lc) 提供。
</div>
<div class="nq-card" markdown>
<span class="nq-stat">.pyi</span>

### 符合 Python 习惯，类型完备

事件是不可变对象，`repr()` 清晰易读，并支持 `match`；错误以 Python 异常的形式抛出；附带精确的类型存根，编辑器和类型检查器开箱即用。
</div>
<div class="nq-card" markdown>
<span class="nq-stat">sans-I/O</span>

### 不绑定运行时

ngquic 不打开套接字，也不启动事件循环，同一份代码可以用在 asyncio、多线程、Trio 或内存中的测试里。
</div>
</div>

## 姊妹项目 {#sister-libraries}

ngquic 还有两个出自同一作者的姊妹库，分别面向更早的 HTTP 版本，设计思路一致。

<!-- Each library publishes its logo at docs/overrides/assets/brand/<name>-logo.svg. -->
<div class="nq-family">
<a href="https://h11r.readthedocs.io/zh/"><img src="https://raw.githubusercontent.com/cnzakii/h11r/main/docs/overrides/assets/brand/h11r-logo.svg" alt=""><strong>h11r</strong><span>HTTP/1.1，Rust 内核</span></a>
<a href="https://ngh2.readthedocs.io/zh/"><img src="https://raw.githubusercontent.com/cnzakii/ngh2/main/docs/overrides/assets/brand/ngh2-logo.svg" alt=""><strong>ngh2</strong><span>HTTP/2，基于 nghttp2</span></a>
<a href="./" aria-current="page"><img src="assets/brand/ngquic-logo.svg" alt=""><strong>ngquic</strong><span>QUIC 与 HTTP/3，基于 ngtcp2</span></a>
</div>

</div>
