---
title: Errors
description: Exceptions, error codes and close reasons in ngquic.
---

# Errors

Methods raise these exceptions for misuse of the API; problems on the wire close the connection instead and arrive as [`ConnectionTerminated`](events.md#ngquic.ConnectionTerminated), whose `reason` and `error_code` use the enums below.

## Exceptions

::: ngquic.QUICError

::: ngquic.ConnectionStateError

::: ngquic.StreamLimitError

::: ngquic.StreamStateError

::: ngquic.DatagramError

::: ngquic.TLSError

::: ngquic.InternalError

## Codes

::: ngquic.ErrorCode
    options:
      members: false

::: ngquic.CloseReason
    options:
      members: false
