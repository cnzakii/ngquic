---
title: Configuration
description: Transport and endpoint configuration, roles, versions and congestion control.
---

# Configuration

Configuration objects are immutable and validated when created. Pass a `TransportConfig` per connection and an `EndpointConfig` per endpoint.

## Transport and endpoint

::: ngquic.TransportConfig
    options:
      members: false

::: ngquic.EndpointConfig
    options:
      members: false

## Choices

::: ngquic.Role
    options:
      members: false

::: ngquic.Version
    options:
      members: false

::: ngquic.CongestionControl
    options:
      members: false
