"""Untrusted media GETs: validate each hop and bind DNS to the socket used.

This policy is deliberately separate from configured Comfy/provider clients.
No application cookies, credentials, environment proxies or local files enter it.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urljoin

import requests
import urllib3
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from fastapi import HTTPException


def public_destination(url, resolver=None):
    try:
        value = urlsplit(url)
        if value.scheme not in {'http', 'https'} or not value.hostname or value.username or value.password:
            raise ValueError()
        port = value.port or (443 if value.scheme == 'https' else 80)
        host = value.hostname.encode('idna').decode('ascii')
        records = (resolver or socket.getaddrinfo)(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(row[4][0] for row in records))
        if not addresses:
            raise ValueError()
        for address in addresses:
            ip = ipaddress.ip_address(address)
            mapped = getattr(ip, 'ipv4_mapped', None)
            if not (mapped or ip).is_global or '%' in address:
                raise ValueError()
        return value, host, port, addresses[0]
    except (ValueError, UnicodeError, OSError) as exc:
        raise HTTPException(403, '此下载地址不属于允许的公共媒体地址；内网素材请使用已配置平台的受权素材入口。') from exc


def _pool_for(value, host, port, address):
    base = HTTPSConnection if value.scheme == 'https' else HTTPConnection
    class PinnedConnection(base):
        def _new_conn(self):
            # TLS connect still uses self.host for SNI and certificate checking.
            return socket.create_connection((address, port), self.timeout, self.source_address)
    pool_type = HTTPSConnectionPool if value.scheme == 'https' else HTTPConnectionPool
    class PinnedPool(pool_type):
        ConnectionCls = PinnedConnection
    options = {'cert_reqs':'CERT_REQUIRED', 'ca_certs':requests.certs.where()} if value.scheme == 'https' else {}
    return PinnedPool(host, port, **options)


class MediaResponse:
    def __init__(self, response, pool):
        self.raw, self.pool = response, pool
        self.status_code = response.status
        self.headers = response.headers.copy()
        if response.headers.get('content-encoding','identity').lower() != 'identity':
            # iter_content yields decoded bytes, matching the previous requests
            # contract. Compressed length/encoding no longer describe that body.
            self.headers.pop('content-length', None)
            self.headers.pop('content-encoding', None)

    def raise_for_status(self):
        if self.status_code >= 400:
            self.close()
            raise requests.HTTPError('媒体下载返回错误状态')

    def iter_content(self, chunk_size=256 * 1024):
        yield from self.raw.stream(chunk_size, decode_content=True)

    def close(self):
        self.raw.close()
        self.pool.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def open_media(url, *, headers=None, timeout=(10, 60)):
    """Return a closeable stream; redirect targets are independently resolved."""
    for hop in range(4):
        value, host, port, address = public_destination(url)
        pool = _pool_for(value, host, port, address)
        target = value.path or '/'
        if value.query: target += '?' + value.query
        safe_headers = {'User-Agent':'InfiniteCanvas-Media/1.0', 'Accept-Encoding':'identity'}
        if headers and headers.get('Range'): safe_headers['Range'] = headers['Range']
        connect, read = timeout if isinstance(timeout, tuple) else (min(timeout, 10), timeout)
        try:
            response = pool.urlopen('GET', target, headers=safe_headers, redirect=False,
                preload_content=False, retries=False, timeout=urllib3.Timeout(connect=connect, read=read))
        except Exception as exc:
            pool.close()
            raise requests.RequestException('媒体连接失败') from exc
        if response.status in {301, 302, 303, 307, 308}:
            location = response.headers.get('location')
            response.close();pool.close()
            if not location or hop == 3:
                raise HTTPException(400, '媒体重定向无效或次数过多')
            url = urljoin(url, location)
            continue
        return MediaResponse(response, pool)
    raise HTTPException(400, '媒体重定向次数过多')
