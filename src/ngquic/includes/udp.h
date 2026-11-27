#ifndef EMBERLYN_UDP_H
#define EMBERLYN_UDP_H

/* UDP fast paths for a socket the caller owns: socket options, control
   messages, segmented sends and batched receives. */

/* RFC 3542 names (IPV6_RECVPKTINFO, in6_pktinfo) on macOS; set before any
   system header, so CMake defines it too. */
#if defined(__APPLE__) && !defined(__APPLE_USE_RFC_3542)
#  define __APPLE_USE_RFC_3542 1
#endif

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <arpa/inet.h>
#ifdef __linux__
#  include <sys/utsname.h>
#endif

#include <ngtcp2/ngtcp2.h>

#include "glue.h"

#ifdef __linux__
#  ifndef SOL_UDP
#    define SOL_UDP 17
#  endif
#  ifndef UDP_SEGMENT
#    define UDP_SEGMENT 103
#  endif
#  ifndef UDP_GRO
#    define UDP_GRO 104
#  endif
#endif

/* Reads one receive call makes at most: enough to amortize the call, few
   enough to return to the event loop before a bulk transfer delays other
   connections. */
#define UDP_BATCH 8
/* Room for any datagram, and for a GRO batch, which the kernel keeps
   below 64 KiB. */
#define UDP_SLOT 65535
/* Control message space: the 88 bytes of the messages below, and room for
   those the caller enables, such as SO_TIMESTAMPNS and IP_RECVTTL. */
#define UDP_CMSG_LEN 256
/* Datagrams one GSO send carries at most (UDP_MAX_SEGMENTS on older
   kernels), and the payload of one send, segmented or not: an IPv4 UDP
   datagram's (65535 - 20 - 8). */
#define UDP_MAX_SEGMENTS 64
#define UDP_MAX_PAYLOAD 65507

/* An address and its length; length 0 for none. */
typedef struct {
  ngtcp2_sockaddr_union addr;
  ngtcp2_socklen len;
} udp_addr;

typedef struct {
  /* The kernel splits segmented sends (Linux GSO). */
  int gso;
  /* An IPv4 send succeeded only without IP_TOS: later ones leave it out. */
  int ipv4_tos_refused;
  /* SO_SNDBUF after configuration, for the macOS bound below; -1 if
     unknown. */
  int send_buffer_size;
  /* The socket's port in network order, read once it has one, for the
     destination of received datagrams. */
  uint16_t port;
  /* Connected when wrapped: connect() fixed both addresses, so sends name
     neither. */
  int connected;
  /* An IPv6 socket, whose addresses received are all reported as IPv6. */
  int ipv6;
} udp_state;

/* One send: data as datagrams of segment_size bytes, the last possibly
   shorter, or one datagram if segment_size is 0. */
typedef struct {
  udp_addr remote;
  /* The source address; length 0 lets the system choose. */
  udp_addr local;
  const unsigned char *data;
  size_t length;
  uint16_t segment_size;
  uint8_t ecn;
} udp_message;

/* One read: datagrams of stride bytes, the last possibly shorter. */
typedef struct {
  udp_addr remote;
  /* The address the datagrams were sent to; length 0 if unreported. */
  udp_addr local;
  unsigned char *data;
  size_t length;
  size_t stride;
  uint8_t ecn;
} udp_received;

typedef union {
  char buf[UDP_CMSG_LEN];
  struct cmsghdr align;
} udp_cmsg;

typedef struct {
  unsigned char *buffers; /* UDP_BATCH slots of UDP_SLOT bytes */
  udp_cmsg ctrl[UDP_BATCH];
  struct iovec iov[UDP_BATCH];
#ifdef __linux__
  struct mmsghdr hdrs[UDP_BATCH];
#else
  struct msghdr hdrs[UDP_BATCH];
#endif
  udp_received received[UDP_BATCH];
} udp_batch;

/* Whether a call failed with error only because the socket was not ready. */
static int udp_would_block(int error) {
  return error == EAGAIN || error == EWOULDBLOCK;
}

static int udp_setopt(int fd, int level, int name, int value) {
  return setsockopt(fd, level, name, &value, sizeof(value));
}

/* 1 if set, 0 if the platform lacks the option, -1 on another error. */
static int udp_setopt_supported(int fd, int level, int name, int value) {
  if (udp_setopt(fd, level, name, value) == 0) {
    return 1;
  }
  if (errno == ENOPROTOOPT || errno == EOPNOTSUPP) {
    return 0;
  }
  return -1;
}

static uint16_t udp_port(const ngtcp2_sockaddr_union *address) {
  return address->sa.sa_family == AF_INET ? address->in.sin_port
                                          : address->in6.sin6_port;
}

#ifdef __linux__
static int udp_kernel_gso = -1;

/* UDP GSO arrived in Linux 4.18; like quinn-udp, older kernels are not
   trusted on setsockopt alone. */
static int udp_kernel_supports_gso(void) {
  struct utsname name;
  int major = 0, minor = 0;

  if (udp_kernel_gso >= 0) {
    return udp_kernel_gso;
  }
  udp_kernel_gso =
    uname(&name) == 0 && sscanf(name.release, "%d.%d", &major, &minor) == 2 &&
    (major > 4 || (major == 4 && minor >= 18));
  return udp_kernel_gso;
}

static int udp_supports_gso(int fd) {
  if (!udp_kernel_supports_gso() ||
      udp_setopt(fd, SOL_UDP, UDP_SEGMENT, 1500) != 0) {
    return 0;
  }
  /* Segmentation stays off unless a send asks for it in a control
     message. */
  (void)udp_setopt(fd, SOL_UDP, UDP_SEGMENT, 0);
  return 1;
}
#endif

#ifdef __APPLE__
/* macOS refuses a non-blocking sendmsg with control messages with
   EWOULDBLOCK when the payload is at or just under SO_SNDBUF, so the buffer
   is kept above the largest datagram. */
#  define UDP_MIN_SAFE_SNDBUF (65535 + UDP_CMSG_LEN)
#endif

/* Enable the receive metadata, offloads and no-fragmentation options the
   platform has; 0, or -errno on failure. */
static int udp_configure(int fd, int connected, udp_state *state) {
  ngtcp2_sockaddr_union address;
  socklen_t length = sizeof(address);
  int only_v6 = 0, is_ipv4;
  socklen_t option_length = sizeof(only_v6);

  memset(state, 0, sizeof(*state));
  state->send_buffer_size = -1;
  state->connected = connected;
  if (getsockname(fd, &address.sa, &length) != 0) {
    return -errno;
  }
  state->port = udp_port(&address);
  is_ipv4 = address.sa.sa_family == AF_INET;
  state->ipv6 = !is_ipv4;
  if (!is_ipv4 && getsockopt(fd, IPPROTO_IPV6, IPV6_V6ONLY, &only_v6,
                             &option_length) != 0) {
    return -errno;
  }

  /* macOS has no IP_RECVTOS on IPv6-only sockets; older versions lack it. */
  if (is_ipv4 || !only_v6) {
    (void)udp_setopt(fd, IPPROTO_IP, IP_RECVTOS, 1);
  }

#ifdef __linux__
  /* No IPv4 fragmentation, also for IPv4-mapped IPv6 destinations. */
  if (udp_setopt_supported(fd, IPPROTO_IP, IP_MTU_DISCOVER,
                           IP_PMTUDISC_PROBE) < 0) {
    return -errno;
  }
  if (is_ipv4) {
    if (udp_setopt(fd, IPPROTO_IP, IP_PKTINFO, 1) != 0) {
      return -errno;
    }
  } else if (udp_setopt_supported(fd, IPPROTO_IPV6, IPV6_MTU_DISCOVER,
                                  IPV6_PMTUDISC_PROBE) < 0) {
    return -errno;
  }
  (void)udp_setopt(fd, SOL_UDP, UDP_GRO, 1);
  state->gso = udp_supports_gso(fd);
#endif

#ifdef __APPLE__
  if (is_ipv4) {
    if (udp_setopt_supported(fd, IPPROTO_IP, IP_DONTFRAG, 1) < 0 ||
        udp_setopt(fd, IPPROTO_IP, IP_RECVDSTADDR, 1) != 0) {
      return -errno;
    }
  }
#endif

  /* RFC 3542 options. */
  if (!is_ipv4) {
    if (udp_setopt(fd, IPPROTO_IPV6, IPV6_RECVPKTINFO, 1) != 0 ||
        udp_setopt(fd, IPPROTO_IPV6, IPV6_RECVTCLASS, 1) != 0) {
      return -errno;
    }
    /* IPV6_PMTUDISC_PROBE alone still lets Linux fragment
       (__ip6_append_data). */
    if (udp_setopt_supported(fd, IPPROTO_IPV6, IPV6_DONTFRAG, 1) < 0) {
      return -errno;
    }
  }

#ifdef __APPLE__
  {
    int size;
    socklen_t size_length = sizeof(size);

    if (getsockopt(fd, SOL_SOCKET, SO_SNDBUF, &size, &size_length) == 0 &&
        size < UDP_MIN_SAFE_SNDBUF) {
      (void)udp_setopt(fd, SOL_SOCKET, SO_SNDBUF, UDP_MIN_SAFE_SNDBUF);
    }
    size_length = sizeof(size);
    if (getsockopt(fd, SOL_SOCKET, SO_SNDBUF, &size, &size_length) == 0) {
      state->send_buffer_size = size;
    }
  }
#endif
  return 0;
}

/* Whether two addresses name the same host, port and IPv6 scope. */
static int udp_same_address(const udp_addr *a, const udp_addr *b) {
  if (a->addr.sa.sa_family != b->addr.sa.sa_family) {
    return 0;
  }
  if (a->addr.sa.sa_family == AF_INET) {
    return a->addr.in.sin_port == b->addr.in.sin_port &&
           a->addr.in.sin_addr.s_addr == b->addr.in.sin_addr.s_addr;
  }
  return a->addr.in6.sin6_port == b->addr.in6.sin6_port &&
         a->addr.in6.sin6_scope_id == b->addr.in6.sin6_scope_id &&
         memcmp(&a->addr.in6.sin6_addr, &b->addr.in6.sin6_addr, 16) == 0;
}

/* Whether address is absent, 0.0.0.0, :: or ::ffff:0.0.0.0. */
static int udp_unspecified(const udp_addr *address) {
  return !address->len || glue_unspecified(&address->addr.sa);
}

static int udp_is_ipv4_destination(const udp_addr *remote) {
  return remote->addr.sa.sa_family == AF_INET ||
         IN6_IS_ADDR_V4MAPPED(&remote->addr.in6.sin6_addr);
}

#define UDP_PUSH(cmsg, used, level, type, value)                              \
  do {                                                                         \
    (cmsg)->cmsg_level = (level);                                              \
    (cmsg)->cmsg_type = (type);                                                \
    (cmsg)->cmsg_len = CMSG_LEN(sizeof(value));                                \
    memcpy(CMSG_DATA(cmsg), &(value), sizeof(value));                          \
    (used) += CMSG_SPACE(sizeof(value));                                       \
    (cmsg) = (struct cmsghdr *)((char *)(cmsg) + CMSG_SPACE(sizeof(value)));   \
  } while (0)

/* The header of one sendmsg of length bytes at data: the destination, and
   control messages for ECN (IP_TOS only if with_tos), the segment size and
   the source address. */
static void udp_prepare_send(const udp_state *state,
                             const udp_message *message,
                             const unsigned char *data, size_t length,
                             uint16_t segment_size, int with_tos,
                             struct msghdr *header, struct iovec *iov,
                             udp_cmsg *control) {
  struct cmsghdr *cmsg;
  size_t used = 0;
  int tos = message->ecn;

  memset(header, 0, sizeof(*header));
  memset(control, 0, sizeof(*control));
  iov->iov_base = (void *)data;
  iov->iov_len = length;
  if (!state->connected) {
    header->msg_name = (void *)&message->remote.addr;
    header->msg_namelen = message->remote.len;
  }
  header->msg_iov = iov;
  header->msg_iovlen = 1;
  header->msg_control = control->buf;
  header->msg_controllen = sizeof(control->buf);
  cmsg = CMSG_FIRSTHDR(header);

  if (!udp_is_ipv4_destination(&message->remote)) {
    UDP_PUSH(cmsg, used, IPPROTO_IPV6, IPV6_TCLASS, tos);
  } else if (with_tos) {
    UDP_PUSH(cmsg, used, IPPROTO_IP, IP_TOS, tos);
  }

#ifdef __linux__
  if (segment_size) {
    UDP_PUSH(cmsg, used, SOL_UDP, UDP_SEGMENT, segment_size);
  }
#else
  (void)segment_size;
#endif

  /* A connected socket's source is fixed (BSD refuses one, EINVAL), and
     0.0.0.0 or :: leaves the choice to the system (Linux refuses :: for an
     IPv4 destination). */
  if (state->connected || udp_unspecified(&message->local)) {
    /* No source address. */
  } else if (message->local.addr.sa.sa_family == AF_INET) {
    /* IP_PKTINFO on macOS too, which ignores IP_RECVDSTADDR on send. */
    struct in_pktinfo info;

    memset(&info, 0, sizeof(info));
    info.ipi_spec_dst = message->local.addr.in.sin_addr;
    UDP_PUSH(cmsg, used, IPPROTO_IP, IP_PKTINFO, info);
  } else {
    struct in6_pktinfo info;

    memset(&info, 0, sizeof(info));
    info.ipi6_addr = message->local.addr.in6.sin6_addr;
    info.ipi6_ifindex = message->local.addr.in6.sin6_scope_id;
    UDP_PUSH(cmsg, used, IPPROTO_IPV6, IPV6_PKTINFO, info);
  }

  header->msg_controllen = used;
  if (used == 0) {
    header->msg_control = NULL;
  }
}

/* One sendmsg of length bytes at data, segmented by the kernel when
   segment_size is set; 0 or -errno. */
static int udp_sendmsg(udp_state *state, int fd, const udp_message *message,
                       const unsigned char *data, size_t length,
                       uint16_t segment_size) {
  struct msghdr header;
  struct iovec iov;
  udp_cmsg control;
  int with_tos = !state->ipv4_tos_refused;

  udp_prepare_send(state, message, data, length, segment_size, with_tos,
                   &header, &iov, &control);
#ifdef __APPLE__
  if (state->send_buffer_size >= 0 &&
      length + header.msg_controllen > (size_t)state->send_buffer_size) {
    return -EMSGSIZE;
  }
#endif
  for (;;) {
    if (sendmsg(fd, &header, MSG_DONTWAIT) >= 0) {
      /* Remembered only once leaving IP_TOS out made the difference. */
      state->ipv4_tos_refused |= !with_tos;
      return 0;
    }
    if (errno == EINTR) {
      continue;
    }
    /* Some systems refuse IP_TOS, for example on a dual-stack IPv6 socket
       sending to an IPv4-mapped address: try once without it. */
    if (errno == EINVAL && with_tos && udp_is_ipv4_destination(&message->remote)) {
      with_tos = 0;
      udp_prepare_send(state, message, data, length, segment_size, with_tos,
                       &header, &iov, &control);
      continue;
    }
    return -errno;
  }
}

/* Send the datagrams of message: in one GSO send where the kernel can,
   otherwise one by one. 0 once the first went out (later ones the system
   refuses are dropped, as QUIC tolerates), or -errno (-EAGAIN when the
   socket is full) if it did not. */
static int udp_send(udp_state *state, int fd, const udp_message *message) {
  size_t offset, size, segment_size = message->segment_size;
  int rv;

  if (!segment_size || segment_size >= message->length) {
    return udp_sendmsg(state, fd, message, message->data, message->length, 0);
  }
#ifdef __linux__
  if (state->gso) {
    rv = udp_sendmsg(state, fd, message, message->data, message->length,
                     message->segment_size);
    if (rv != -EIO) {
      return rv;
    }
    /* Linux refuses to segment on some routes, such as through IPsec. */
    state->gso = 0;
  }
#endif
  for (offset = 0; offset < message->length; offset += size) {
    size = message->length - offset < segment_size ? message->length - offset
                                                   : segment_size;
    rv = udp_sendmsg(state, fd, message, message->data + offset, size, 0);
    if (rv < 0) {
      return offset ? 0 : rv;
    }
  }
  return 0;
}

static void udp_prepare_receive(udp_batch *batch, int index,
                                struct msghdr *header) {
  udp_received *received = &batch->received[index];

  received->data = batch->buffers + (size_t)index * UDP_SLOT;
  batch->iov[index].iov_base = received->data;
  batch->iov[index].iov_len = UDP_SLOT;
  memset(header, 0, sizeof(*header));
  header->msg_name = &received->remote.addr;
  header->msg_namelen = sizeof(received->remote.addr);
  header->msg_iov = &batch->iov[index];
  header->msg_iovlen = 1;
  header->msg_control = batch->ctrl[index].buf;
  header->msg_controllen = sizeof(batch->ctrl[index].buf);
}

/* An IPv4 address in the IPv4-mapped IPv6 form an IPv6 socket sends to. On
   such a socket macOS reports IPv4 peers of a socket bound to an IPv4-mapped
   address as IPv4, and Linux adds IP_PKTINFO where the caller enabled it. */
static void udp_map_ipv4(udp_addr *address) {
  struct sockaddr_in in;

  if (address->addr.sa.sa_family != AF_INET) {
    return;
  }
  in = address->addr.in;
  memset(&address->addr.in6, 0, sizeof(address->addr.in6));
  address->addr.in6.sin6_family = AF_INET6;
  address->addr.in6.sin6_port = in.sin_port;
  address->addr.in6.sin6_addr.s6_addr[10] = 0xff;
  address->addr.in6.sin6_addr.s6_addr[11] = 0xff;
  memcpy(&address->addr.in6.sin6_addr.s6_addr[12], &in.sin_addr, 4);
  address->len = sizeof(address->addr.in6);
}

/* What the control messages report: ECN, the destination and the GRO
   stride. */
static void udp_decode_receive(const udp_state *state, udp_received *received,
                               struct msghdr *header, size_t length) {
  struct cmsghdr *cmsg;
  udp_addr *local = &received->local;

  received->remote.len = header->msg_namelen;
  received->length = length;
  received->stride = length;
  received->ecn = 0;
  memset(local, 0, sizeof(*local));
  for (cmsg = CMSG_FIRSTHDR(header); cmsg != NULL;
       cmsg = CMSG_NXTHDR(header, cmsg)) {
    if (cmsg->cmsg_level == IPPROTO_IP &&
        (cmsg->cmsg_type == IP_TOS || cmsg->cmsg_type == IP_RECVTOS)) {
      received->ecn = *(unsigned char *)CMSG_DATA(cmsg);
    } else if (cmsg->cmsg_level == IPPROTO_IPV6 &&
               cmsg->cmsg_type == IPV6_TCLASS) {
      int tclass;

      /* macOS may deliver a single byte. */
      if (cmsg->cmsg_len == CMSG_LEN(sizeof(unsigned char))) {
        received->ecn = *(unsigned char *)CMSG_DATA(cmsg);
      } else {
        memcpy(&tclass, CMSG_DATA(cmsg), sizeof(tclass));
        received->ecn = (uint8_t)tclass;
      }
    } else if (cmsg->cmsg_level == IPPROTO_IPV6 &&
               cmsg->cmsg_type == IPV6_PKTINFO) {
      struct in6_pktinfo info;

      memcpy(&info, CMSG_DATA(cmsg), sizeof(info));
      local->addr.in6.sin6_family = AF_INET6;
      local->addr.in6.sin6_addr = info.ipi6_addr;
      /* The receiving interface, as the socket module reports link-local
         addresses. */
      if (IN6_IS_ADDR_LINKLOCAL(&info.ipi6_addr)) {
        local->addr.in6.sin6_scope_id = info.ipi6_ifindex;
      }
      local->len = sizeof(local->addr.in6);
    }
#ifdef __linux__
    else if (cmsg->cmsg_level == IPPROTO_IP && cmsg->cmsg_type == IP_PKTINFO) {
      struct in_pktinfo info;

      memcpy(&info, CMSG_DATA(cmsg), sizeof(info));
      local->addr.in.sin_family = AF_INET;
      local->addr.in.sin_addr = info.ipi_addr;
      local->len = sizeof(local->addr.in);
    } else if (cmsg->cmsg_level == SOL_UDP && cmsg->cmsg_type == UDP_GRO) {
      int stride;

      memcpy(&stride, CMSG_DATA(cmsg), sizeof(stride));
      if (stride > 0) {
        received->stride = (size_t)stride;
      }
    }
#else
    else if (cmsg->cmsg_level == IPPROTO_IP &&
             cmsg->cmsg_type == IP_RECVDSTADDR) {
      local->addr.in.sin_family = AF_INET;
      memcpy(&local->addr.in.sin_addr, CMSG_DATA(cmsg), 4);
      local->len = sizeof(local->addr.in);
    }
#endif
  }
  if (local->addr.sa.sa_family == AF_INET) {
    local->addr.in.sin_port = state->port;
  } else if (local->len) {
    local->addr.in6.sin6_port = state->port;
  }
  if (state->ipv6) {
    udp_map_ipv4(&received->remote);
    udp_map_ipv4(local);
  }
  received->ecn &= 0x3;
}

/* A datagram whose payload or control messages did not fit is dropped: a
   lost UDP_GRO stride would join datagrams into one. */
static int udp_truncated(const struct msghdr *header) {
  return (header->msg_flags & (MSG_TRUNC | MSG_CTRUNC)) != 0;
}

/* Read up to UDP_BATCH datagrams (or GRO batches) into batch->received;
   how many, or -errno when none was waiting or the first read failed. */
static int udp_receive(udp_state *state, udp_batch *batch, int fd) {
  int received = 0;

  /* An unbound socket got its port from its first send. */
  if (!state->port) {
    ngtcp2_sockaddr_union address;
    socklen_t length = sizeof(address);

    if (getsockname(fd, &address.sa, &length) == 0) {
      state->port = udp_port(&address);
    }
  }
#ifdef __linux__
  int index, got;

  for (index = 0; index < UDP_BATCH; ++index) {
    udp_prepare_receive(batch, index, &batch->hdrs[index].msg_hdr);
  }
  do {
    got = recvmmsg(fd, batch->hdrs, UDP_BATCH, MSG_DONTWAIT, NULL);
  } while (got < 0 && errno == EINTR);
  if (got < 0) {
    return -errno;
  }
  for (index = 0; index < got; ++index) {
    struct msghdr *header = &batch->hdrs[index].msg_hdr;

    if (udp_truncated(header)) {
      continue;
    }
    if (received != index) {
      batch->received[received] = batch->received[index];
    }
    udp_decode_receive(state, &batch->received[received], header,
                       batch->hdrs[index].msg_len);
    ++received;
  }
  return received;
#else
  /* One recvmsg per datagram, without returning to Python in between. */
  int reads;

  for (reads = 0; reads < UDP_BATCH;) {
    struct msghdr *header = &batch->hdrs[received];
    ssize_t length;

    udp_prepare_receive(batch, received, header);
    length = recvmsg(fd, header, MSG_DONTWAIT);
    if (length < 0) {
      if (errno == EINTR) {
        continue;
      }
      return received ? received : -errno;
    }
    ++reads;
    if (udp_truncated(header)) {
      continue;
    }
    udp_decode_receive(state, &batch->received[received], header,
                       (size_t)length);
    ++received;
  }
  return received;
#endif
}

#endif
