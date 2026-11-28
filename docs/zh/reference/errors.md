---
title: 错误
description: ngquic 中的异常、错误码和关闭原因。
source_commit: ab51bfa
---

# 错误

API 用法有误时，方法抛出下列异常。网络上出现的问题不会抛出异常，而是导致连接关闭，并通过 [`ConnectionTerminated`](events.md#ngquic.ConnectionTerminated) 事件告知你；事件的 `reason` 和 `error_code` 取自下面的枚举。

## 异常 {#exceptions}

::: ngquic.QUICError

::: ngquic.ConnectionStateError

::: ngquic.StreamLimitError

::: ngquic.StreamStateError

::: ngquic.DatagramError

::: ngquic.TLSError

::: ngquic.InternalError

## 错误码 {#codes}

::: ngquic.ErrorCode
    options:
      members: false

::: ngquic.CloseReason
    options:
      members: false
