---
title: 配置
description: 传输配置与端点配置、角色、版本和拥塞控制。
source_commit: ab51bfa
---

# 配置

配置对象在创建时校验，之后不可修改。`TransportConfig` 按连接传入，`EndpointConfig` 按 `Endpoint` 传入。

## 传输配置与端点配置 {#transport-and-endpoint}

::: ngquic.TransportConfig
    options:
      members: false

::: ngquic.EndpointConfig
    options:
      members: false

## 枚举选项 {#choices}

::: ngquic.Role
    options:
      members: false

::: ngquic.Version
    options:
      members: false

::: ngquic.CongestionControl
    options:
      members: false
