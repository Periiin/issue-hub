"""IP → 归属地。

为什么自带离线库而不是调在线接口：
- 登录记录是审计数据，查一次调一次外网会慢、会失败、还会把用户 IP 发给第三方
- 内网/离线部署时外网接口根本不通
- 11MB 的 xdb 全量加载进内存，查询是纯二分，微秒级

用的是 ip2region 的 xdb 格式（Apache-2.0）。解析器是纯标准库手写的，
没引第三方包 —— 官方 Python 绑定要求 Python 3.9+ 且带类型体操，
为一个查表功能加依赖不划算。

文件布局（v4）：
    0    .. 256      header（version/indexPolicy/createdAt/startPtr/endPtr/ipVersion）
    256  .. 256+N    向量索引，N = 256*256*8；每格 (s_ptr, e_ptr) 两个 uint32 小端
    之后             段索引区，每条 14 字节 = 4(起始IP) + 4(结束IP) + 2(数据长度) + 4(数据指针)
    再之后           数据区，形如 "中国|0|广东省|深圳市|电信"

注意 IP 在索引里是**小端**存的（历史遗留），比较时要逐字节反着比。
"""
import ipaddress
import threading
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "ip2region_v4.xdb"

HEADER_LEN = 256
VECTOR_COLS = 256
VECTOR_SIZE = 8                      # 每格两个 uint32
VECTOR_LEN = VECTOR_COLS * VECTOR_COLS * VECTOR_SIZE
SEG_INDEX_SIZE = 14                  # 4 + 4 + 2 + 4
IP_BYTES = 4

# 内网/本机段：xdb 里查不到，硬编码更好读
_PRIVATE_HINTS = (
    ("127.", "本机"),
    ("10.", "内网"),
    ("192.168.", "内网"),
)


class _Searcher:
    """线程安全的 xdb 查询器。

    启动时把整个文件读进内存（11MB，可接受），查询全程无 IO。
    延迟加载：只有第一次真正查询时才读文件，避免没开登录功能也占内存。
    """

    def __init__(self, path: Path):
        self.path = path
        self._buf: bytes | None = None
        self._lock = threading.Lock()

    def _load(self) -> bytes:
        if self._buf is not None:
            return self._buf
        with self._lock:
            if self._buf is None:
                self._buf = self.path.read_bytes()
            return self._buf

    @property
    def available(self) -> bool:
        return self.path.is_file()

    def search(self, ip: str) -> str:
        """返回 "国家|省|市|运营商" 这类原始串；查不到返回空串。"""
        try:
            packed = ipaddress.ip_address(ip).packed
        except ValueError:
            return ""
        if len(packed) != IP_BYTES:
            return ""

        buf = self._load()
        if len(buf) < HEADER_LEN + VECTOR_LEN:
            return ""

        # 1) 向量索引：前两字节定位到段索引范围
        idx = HEADER_LEN + (packed[0] * VECTOR_COLS + packed[1]) * VECTOR_SIZE
        s_ptr = _u32(buf, idx)
        e_ptr = _u32(buf, idx + 4)
        if s_ptr == 0 or e_ptr == 0:
            return ""

        # 2) 段索引二分
        low, high = 0, (e_ptr - s_ptr) // SEG_INDEX_SIZE
        while low <= high:
            mid = (low + high) >> 1
            ptr = s_ptr + mid * SEG_INDEX_SIZE
            if _v4_cmp(packed, buf, ptr) < 0:
                high = mid - 1
            elif _v4_cmp(packed, buf, ptr + IP_BYTES) > 0:
                low = mid + 1
            else:
                d_len = _u16(buf, ptr + IP_BYTES * 2)
                d_ptr = _u32(buf, ptr + IP_BYTES * 2 + 2)
                if d_len == 0:
                    return ""
                return buf[d_ptr:d_ptr + d_len].decode("utf-8", "replace")
        return ""


def _u32(buff: bytes, off: int) -> int:
    return int.from_bytes(buff[off:off + 4], "little")


def _u16(buff: bytes, off: int) -> int:
    return int.from_bytes(buff[off:off + 2], "little")


def _v4_cmp(ip: bytes, buff: bytes, off: int) -> int:
    """IP 是网络序（大端），库里是小端，逐字节反着比。"""
    j = off + IP_BYTES - 1
    for i in range(IP_BYTES):
        a, b = ip[i], buff[j]
        if a < b:
            return -1
        if a > b:
            return 1
        j -= 1
    return 0


_searcher = _Searcher(DB_PATH)


def is_available() -> bool:
    return _searcher.available


def lookup(ip: str) -> dict:
    """IP → {ip, country, province, city, isp, text, private}。

    text 是给人看的短串，如「广东省 深圳市 电信」；内网直接标「内网」。
    """
    ip = (ip or "").strip()
    out = {"ip": ip, "country": "", "province": "", "city": "", "isp": "",
           "text": "", "private": False}
    if not ip:
        return out

    if ip in ("::1", "localhost"):
        out.update(text="本机", private=True)
        return out

    for prefix, hint in _PRIVATE_HINTS:
        if ip.startswith(prefix):
            out.update(text=hint, private=True)
            return out
    # 172.16.0.0/12
    if ip.startswith("172."):
        try:
            if 16 <= int(ip.split(".")[1]) <= 31:
                out.update(text="内网", private=True)
                return out
        except (IndexError, ValueError):
            pass

    raw = _searcher.search(ip)
    if not raw:
        out["text"] = "未知"
        return out

    # 原始格式：国家|省|市|运营商|国家代码（空位用 0 占位）
    # 例：中国|江苏省|南京市|0|CN / United States|California|0|Google LLC|US
    parts = raw.split("|")
    while len(parts) < 5:
        parts.append("")

    def clean(v: str) -> str:
        return "" if v in ("0", "") else v

    country, province, city, isp = (clean(p) for p in parts[:4])
    out.update(country=country, province=province, city=city, isp=isp)

    bits = [b for b in (country, province, city, isp) if b]
    # 省市同名时别重复显示（如「北京市 北京市」）
    dedup: list[str] = []
    for b in bits:
        if not dedup or dedup[-1] != b:
            dedup.append(b)
    out["text"] = " ".join(dedup) or "未知"
    return out
