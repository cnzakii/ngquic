# Simplified Chinese translation guide

This guide adds Simplified Chinese rules to the general process in
[the translation guide](README.md). The pages live in `docs/zh/`; the values
the Chinese site changes are in `zh.toml` beside this file.

Terms follow the RFCs first, then the Simplified Chinese editions of the Python
documentation ([glossary][py], [`ssl`][py-ssl], [`asyncio` transports][py-asyncio])
and MDN ([translation guide][mdn-guide], [glossary][mdn-glossary]). Glossary rows
without a source are this project's own convention.

## Write natural Chinese

Translate the meaning, then phrase it the way a Chinese technical writer would.
Do not translate word for word. Accuracy still decides: never add or drop a
fact to make a sentence read better.

- Rebuild the sentence instead of keeping the English order. Put the topic
  first, use short clauses, and drop articles and pronouns that Chinese does
  not need (一个, 它, 其).
- Avoid calques such as 以……的形式到达, 对……进行……, 地道的 X, and 从这里开始
  used for "start with".
- Headings must read as native Chinese headings: a noun phrase or a short
  verb-object phrase. A bare adjective such as 快 for "Fast" is not a heading.

| English | Literal (avoid) | Natural |
|---|---|---|
| If you need to… / Start with | 如果你需要…… / 从这里开始 | 要做的事 / 入口 |
| share everything in `BaseConnection` | 共享 `BaseConnection` 中的全部内容 | 都继承 `BaseConnection` 的全部功能 |
| in the shape of `ssl.SSLContext` | 形式与 `ssl.SSLContext` 相同 | 接口仿照 `ssl.SSLContext` |
| problems on the wire arrive as `ConnectionTerminated` | 以 `ConnectionTerminated` 事件的形式到达 | 通过 `ConnectionTerminated` 事件告知你 |
| The content is maintained in English | 本页内容以英文维护 | 本页只维护英文版 |
| Fast (heading) | 快 | 性能 |
| Python-native and typed (heading) | 地道的 Python，类型完整 | 符合 Python 习惯，类型完备 |

## Tiers

Each term belongs to one tier. The glossary marks the tier as 译, 注 or 留.

- **译 (translate)**: the Chinese term is established and has one meaning, for
  example 连接, 握手, 拥塞控制 or 事件. Write the Chinese only.
- **注 (gloss on first use)**: a Chinese term exists, but readers may not
  recognize it. The first use on each page is written as `中文（English）`,
  for example 无状态重置（stateless reset）, and later uses are Chinese only.
  Count per page, because readers can land on any page. This is MDN's form,
  as in 应用程序接口（API）.
- **留 (keep English)**:
  - API identifiers, always in inline code. `Endpoint` stays `Endpoint` when it
    means the class, never 端点.
  - Type names of frames, packets, settings and error codes that the RFCs
    define, such as Initial, Handshake, Retry, Version Negotiation, STREAM,
    ACK, CONNECTION_CLOSE, DATAGRAM, GOAWAY, SETTINGS, ORIGIN and
    H3_NO_ERROR. Add a Chinese class word after them, as in Retry 包 or
    GOAWAY 帧, and keep or drop backticks as the English page does.
  - Acronyms and proper names: QUIC, TLS, UDP, HTTP/3, ALPN, QPACK, PMTUD,
    MTU, RTT, PTO, GSO, GRO, ECN, AEAD, GIL, qlog, 0-RTT, 1-RTT, NewReno,
    CUBIC, BBR, and library names. An acronym readers may not know is
    explained on its first use on a page as `English（中文说明）`, then written
    in English, as [ruanyf][ruanyf-text] recommends (英文处理, item 5).
    Common ones such as QUIC, TLS, UDP and HTTP are not explained.
  - Terms whose Chinese rendering would mislead. The glossary gives the reason
    for each.

## Glossary

### QUIC

| English | 译法 | Tier | Reason |
|---|---|---|---|
| connection | 连接 | 译 | |
| stream | 流 | 译 | Not 数据流, which reads as a byte stream |
| bidirectional / unidirectional stream | 双向流 / 单向流 | 译 | |
| packet | 数据包; 包 in compounds | 译 | [MDN][mdn-packet]. Examples: Initial 包, 1-RTT 包 |
| frame | 帧 | 译 | |
| UDP datagram | UDP 数据报 | 译 | [Python][py-asyncio]. Used by `receive_datagram()`, `datagrams_to_send()` and `Transmit` |
| DATAGRAM frame | DATAGRAM 帧 | 留 | RFC 9221 frame, not a UDP datagram. Used by `Connection.send_datagram()` and `DatagramReceived` |
| unreliable datagram | 不可靠数据报 | 注 | The RFC 9221 feature. Never write a bare 数据报 where one of the four kinds could be meant |
| HTTP datagram | HTTP 数据报 | 译 | RFC 9297. Used by `H3Connection.send_datagram()` |
| endpoint (protocol sense) | 端点 | 译 | RFC 9000: either the client or the server. The `Endpoint` class stays code |
| peer | 对端 | 译 | [Python][py-ssl] |
| client / server | 客户端 / 服务器 | 译 | [Python][py-ssl]. Not 服务端 |
| handshake | 握手 | 译 | [Python][py-ssl]. The Handshake packet keeps its English name |
| handshake complete / confirmed | 握手完成 / 握手确认 | 译 | Two distinct states ([RFC 9001 §4.1.1][rfc9001-411], [§4.1.2][rfc9001-412]) |
| 0-RTT / 1-RTT | 0-RTT / 1-RTT | 留 | |
| early data | 早期数据 | 注 | |
| round-trip time | 往返时间（RTT） | 注 | |
| session ticket | 会话票据 | 注 | [Python][py-ssl] writes 票据 |
| session resumption | 会话恢复 | 译 | [Python][py-ssl] |
| token | 令牌 | 注 | 地址验证令牌, Retry 令牌, NEW_TOKEN 令牌, 无状态重置令牌. Not 词元, the lexer token in [Python][py] |
| Retry | Retry 包 | 留 | A packet type ([RFC 9000 §17.2.5][rfc9000-retry]). 重试 suggests the client resending on its own |
| address validation | 地址验证 | 译 | |
| stateless reset | 无状态重置 | 注 | |
| connection ID | 连接 ID | 译 | |
| path validation | 路径验证 | 译 | PATH_CHALLENGE and PATH_RESPONSE stay English |
| connection migration | 连接迁移 | 译 | |
| preferred address | 首选地址 | 注 | Matches 首选版本 for `preferred_versions` |
| key update | 密钥更新 | 译 | |
| packet protection | 数据包保护 | 译 | |
| congestion control | 拥塞控制 | 译 | |
| flow control | 流量控制 | 译 | [Python][py-asyncio]. Never 流控: in QUIC, 流 means stream |
| flow-control credit / window | 流量控制额度 / 窗口 | 译 | Write stream-level and connection-level control as 流级 and 连接级 |
| loss detection / recovery | 丢包检测 / 丢包恢复 | 译 | |
| probe timeout | PTO（探测超时） | 留 | |
| acknowledgment | 确认 | 译 | The ACK frame stays English |
| PMTUD | PMTUD（路径 MTU 发现） | 留 | |
| closing period | 关闭期 | 注 | The `CLOSING` state stays code |
| draining period | 排空期 | 注 | Not the same as HTTP/3 `is_drained`, which is 已排空 |
| idle timeout | 空闲超时 | 译 | |
| keep-alive | 保活 | 译 | |
| transport parameters | 传输参数 | 译 | Parameter names stay code |
| version negotiation | 版本协商 | 译 | The Version Negotiation packet keeps its English name |
| ALPN | ALPN（应用层协议协商） | 留 | [Python][py-ssl] keeps ALPN |
| certificate / chain | 证书 / 证书链 | 译 | [Python][py-ssl] |
| certificate authority | 证书颁发机构（CA） | 注 | [MDN][mdn-ca] |
| keylog | 密钥日志 | 译 | [Python][py-ssl] |
| head-of-line blocking | 队头阻塞 | 译 | |
| multiplexing | 多路复用 | 译 | |
| packet header | 首部 | 译 | 长首部, 短首部. HTTP headers are 标头 |
| error code | 错误码 | 译 | |
| GSO / GRO / ECN | GSO / GRO / ECN | 留 | Explain on first use: 通用分段卸载, 通用接收合并, 显式拥塞通知 |
| GREASE | GREASE | 留 | RFC 9287 |
| payload | 载荷 | 译 | |
| first flight | 首轮数据包 | 注 | The packets an endpoint sends before it hears from its peer |

### HTTP/3

| English | 译法 | Tier | Reason |
|---|---|---|---|
| request / response | 请求 / 响应 | 译 | [MDN][mdn-messages] |
| informational response | 信息响应 | 译 | 1xx |
| header | 标头 | 译 | [MDN glossary][mdn-glossary]. Not 首部 or 头部 |
| field / field section | 字段 / 字段节 | 译 | RFC 9110 §5 |
| pseudo-header | 伪标头 | 译 | |
| body / chunk | 主体 / 分块 | 译 | [MDN][mdn-messages] |
| header section | 标头节 | 译 | As 字段节 above |
| trailer | 尾部字段 | 注 | RFC 9110 §6.5. `TrailersReceived` stays code |
| QPACK | QPACK | 留 | 动态表, 编码器流, 解码器流 |
| GOAWAY | GOAWAY 帧 | 留 | |
| graceful shutdown | 优雅关闭 | 译 | |
| priority | 优先级 | 译 | PRIORITY_UPDATE stays English |
| settings | 设置 | 译 | SETTINGS and SETTINGS_* stay English |
| extended CONNECT | 扩展 CONNECT | 译 | CONNECT is a method name |
| origin | 源 | 译 | [MDN][mdn-origin]. The ORIGIN frame stays English |

### Python and the binding

| English | 译法 | Tier | Reason |
|---|---|---|---|
| sans-I/O | sans-I/O | 留 | A design-pattern name. 无 I/O misleads: the caller still performs the I/O. Keep the English casing |
| event | 事件 | 译 | |
| event loop | 事件循环 | 译 | [Python][py-asyncio] |
| transmit (verb) | 发送 | 译 | As a noun it is the `Transmit` object, which stays code |
| callback | 回调 | 译 | [Python][py] |
| buffer / buffer protocol | 缓冲区 / 缓冲协议 | 译 | [Python][py] |
| bytes-like object | 字节型对象 | 译 | [Python][py] |
| free-threaded | 自由线程 | 注 | [Python][py]. A free-threaded build is 自由线程构建版 |
| GIL | 全局解释器锁（GIL） | 注 | [Python][py] |
| thread-safe | 线程安全 | 译 | [Python][py] |
| backpressure | 背压 | 注 | |
| high / low water mark | 高水位 / 低水位 | 译 | [Python][py-asyncio] |
| socket | 套接字 | 译 | [Python][py-asyncio] |
| timer | 定时器 | 译 | |
| deadline | 截止时间 | 译 | |
| driver (the caller's loop) | 驱动程序 | 译 | The code that moves datagrams, events and timers; not a device driver |
| selector | 选择器 | 译 | [Python][py] `selectors` |
| immutable | 不可变 | 译 | [Python][py] |
| type stub | 类型存根 | 译 | [Python][py-typing] |
| wheel | wheel | 留 | A packaging format name |
| middlebox | 中间设备 | 注 | |

## Typography

These rules follow the [MDN translation guide][mdn-guide], then
[ruanyf][ruanyf] and [sparanoid][sparanoid]. Where they differ, MDN wins.

- **Spacing**: put one half-width space between Chinese and Latin letters,
  digits or inline code: 支持 CPython 3.10 至 3.15, 调用 `connect()` 时.
- **Punctuation**: Chinese sentences use full-width punctuation (，。：；？！（）“”),
  with no space next to it: 它是 QUIC。 and 应用层协议协商（ALPN）. Separate
  items in a list with 、, even when they are English: QPACK、优先级和扩展 CONNECT.
  Use “” for quotes, not 「」. A sentence that is entirely English keeps
  half-width punctuation.
- **Numbers and units**: write digits half-width and put a space before a unit,
  as in 16 MiB, 30 秒 and 1452 字节. Write percentages without a space: 15%.
  Keep KiB and KB exactly as the English has them. In prose, 4× becomes 4 倍;
  tables keep ×. Write ranges with ～ and the unit on both ends: 24 倍～80 倍
  ([ruanyf][ruanyf-number]).
- **Headings**: a heading never ends with 。，：； ([ruanyf][ruanyf-marks]).
- **Line breaks**: write each paragraph on one line. In Markdown, a line break
  between Chinese characters becomes a space ([MDN][mdn-guide]).
- **Links**: spacing depends on the neighbouring characters, not on the link
  markup: 请参阅[迁移指南](...)；使用 [ngtcp2](...) 实现.
- **RFC citations**: write RFC 9000 第 10.2 节 and RFC 9000 附录 A, linked to the
  section. Do not use §: it is rare in Chinese prose, and ruanyf writes
  第 1.3 节.
- **Style**: address the reader as 你, not 您 ([MDN][mdn-guide]). Drop English
  plurals: 流, not streams. Prefer the active voice.

## Admonition titles

| Type | Title |
|---|---|
| `note` | 备注 |
| `tip` | 提示 |
| `info` | 说明 |
| `warning` | 警告 |
| `danger` | 危险 |
| `example` | 示例 |

The lag banner:

```markdown
!!! warning "翻译滞后"
    本页落后于[英文原文](/<path>/)，内容以英文为准。
```

[py]: https://docs.python.org/zh-cn/3/glossary.html
[py-ssl]: https://docs.python.org/zh-cn/3/library/ssl.html
[py-asyncio]: https://docs.python.org/zh-cn/3/library/asyncio-protocol.html
[py-typing]: https://docs.python.org/zh-cn/3/library/typing.html
[mdn-guide]: https://github.com/mdn/translated-content/blob/main/docs/zh-cn/translation-guide.md
[mdn-glossary]: https://github.com/mdn/translated-content/blob/main/docs/zh-cn/glossary.md
[mdn-packet]: https://developer.mozilla.org/zh-CN/docs/Glossary/Packet
[mdn-ca]: https://developer.mozilla.org/zh-CN/docs/Glossary/Certificate_authority
[mdn-origin]: https://developer.mozilla.org/zh-CN/docs/Glossary/Origin
[mdn-messages]: https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Guides/Messages
[ruanyf]: https://github.com/ruanyf/document-style-guide
[ruanyf-text]: https://github.com/ruanyf/document-style-guide/blob/master/docs/text.md
[ruanyf-marks]: https://github.com/ruanyf/document-style-guide/blob/master/docs/marks.md
[ruanyf-number]: https://github.com/ruanyf/document-style-guide/blob/master/docs/number.md
[sparanoid]: https://github.com/sparanoid/chinese-copywriting-guidelines
[rfc9000-retry]: https://www.rfc-editor.org/rfc/rfc9000#section-17.2.5
[rfc9001-411]: https://www.rfc-editor.org/rfc/rfc9001#section-4.1.1
[rfc9001-412]: https://www.rfc-editor.org/rfc/rfc9001#section-4.1.2
