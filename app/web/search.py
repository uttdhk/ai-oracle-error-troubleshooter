# app/web/search.py
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
import os
import re

from urllib.parse import urlparse, parse_qs, unquote

STRICT_ORA_MATCH = (os.getenv("STRICT_ORA_MATCH", "true").lower() == "true")

# 입력 문자열(text)에서 Oracle 오류 코드(예: ORA-12514)를 찾아내는 내부 유틸리티 함수
def _extract_ora_code(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"\bORA-\d{5}\b", text.upper())
    return m.group(0) if m else None

# 웹 검색 결과(hit) 가 특정 Oracle 에러 코드(예: ORA-12514)를 실제로 포함하고 있는지 여부를 검사하는 함수
def _hit_contains_code(code: str, *, url: str = "", title: str = "", text: str = "", snippet: str = "") -> bool:
    """결과(본문/제목/URL/스니펫)에 ORA-코드가 실제로 포함되는지 검사"""
    if not code:
        return True
    hay = " ".join([url or "", title or "", text or "", snippet or ""]).upper()
    return code in hay

# DuckDuckGo(DDG) 검색 결과 URL이 중간 리디렉션(https://duckduckgo.com/l/?uddg=...)으로 감싸져 있을 때, 그 실제 원본 URL을 추출(unwrap) 하는 내부 유틸리티 함수
def _unwrap_ddg_redirect(href: str) -> str:
    """
    DDG HTML 검색 결과의 redirect 링크(duckduckgo.com/l/?uddg=...)를 실제 목적지로 풀어준다.
    redirect가 아니면 원본 href를 그대로 반환.
    """
    try:
        if not href:
            return href
        u = urlparse(href)
        if (u.hostname or "").lower().endswith("duckduckgo.com") and u.path.startswith("/l/"):
            qs = parse_qs(u.query or "")
            if "uddg" in qs and qs["uddg"]:
                return unquote(qs["uddg"][0])
        return href
    except Exception:
        return href
    
# ---- 환경 플래그 ----
WEB_SEARCH_BACKEND = (os.getenv("WEB_SEARCH_BACKEND") or "").lower().strip()  # ddgs | duckduckgo_search | html | ""
INSECURE_SKIP_VERIFY = (os.getenv("INSECURE_SKIP_VERIFY", "false").lower() == "true")
CA_BUNDLE = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")  # 있으면 requests verify에 사용

# ---- 우선순위: ddgs(9.x) -> duckduckgo_search(6.x) -> html 파서 ----
_have_ddgs = False
_have_ddgsearch = False
try:
    from ddgs import DDGS  # ddgs 9.x
    _have_ddgs = True
except Exception:
    pass

if not _have_ddgs:
    try:
        from duckduckgo_search import DDGS as LEGACY_DDGS  # 6.x
        _have_ddgsearch = True
    except Exception:
        pass
else:
    # ddgs 있더라도 duckduckgo_search도 있으면 기록해둠(폴백용)
    try:
        from duckduckgo_search import DDGS as LEGACY_DDGS  # 6.x
        _have_ddgsearch = True
    except Exception:
        pass


# ---- Allowlist (그대로 유지) ----
_ALLOWED = {
    "oracle.com",              # ✅ *.oracle.com 전역 허용
    "docs.oracle.com",
    "asktom.oracle.com",
    "community.oracle.com",
    "oracle-base.com",
    "stackoverflow.com",
    "dba.stackexchange.com",
    "github.com",
    "medium.com",
    "blogspot.com",
}

# 주어진 URL의 호스트(host, 도메인) 가 허용 가능한(“신뢰할 수 있는”) 도메인인지 검사하는 내부 함수
def _host_ok(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
#    return any(host.endswith(d) for d in _ALLOWED)
    # *.oracle.com 전체 허용 + 나머지는 endswith 체크
    return (
        host.endswith(".oracle.com") or host == "oracle.com" or
        any(host.endswith(d) for d in _ALLOWED)
    )

MIN_LEN_PRIMARY   = 220
MIN_LEN_SECONDARY = 60

# ---- HTML 파서 백업 (requests + BeautifulSoup; verify/프록시 자동) ----
# 웹 검색을 한 번 수행해서(once) 그 결과를 HTML 형태로 가져오는 함수
def _search_once_html(query: str, max_results: int = 6, region: str = "wt-wt") -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception:
        return items
    params = {"q": query, "kl": region}
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
    verify = False if INSECURE_SKIP_VERIFY else (CA_BUNDLE or True)
    try:
        r = requests.get("https://html.duckduckgo.com/html/", params=params, headers=headers,
                         timeout=12, verify=verify)
        if r.status_code != 200:
            return items
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.result__a"):
            href_raw = (a.get("href") or "").strip()
            url = _unwrap_ddg_redirect(href_raw)  # ✅ 리다이렉트 해제
            title = (a.get_text(strip=True) or url)
            if not url or not _host_ok(url):
                continue
            items.append({"title": title, "url": url, "snippet": ""})
            if len(items) >= max_results:
                break
    except Exception:
        return items
    return items

# 웹페이지를 가져(fetch) 와서, 그중 사람이 읽을 수 있는(본문 중심의) 텍스트만 추출(readable) 하는 함수
def _fetch_readable(url: str) -> Optional[str]:
    # trafilatura 우선 (내부 requests 사용 시 CA_BUNDLE/프록시 자동 반영)
    try:
        import trafilatura
        # trafilatura는 verify 인자를 직접 받지 않지만, 내부 요청은 시스템 CA/프록시 환경을 따릅니다.
        downloaded = trafilatura.fetch_url(url, timeout=12)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if text and text.strip():
                return text.strip()
    except Exception:
        pass
    # requests + bs4 백업 (verify 제어)
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception:
        return None
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
    verify = False if INSECURE_SKIP_VERIFY else (CA_BUNDLE or True)
    try:
        r = requests.get(url, headers=headers, timeout=12, verify=verify)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        cands = []
        for sel in ("article", "[role=main]", "main", ".content", "#content"):
            for node in soup.select(sel):
                txt = node.get_text("\n", strip=True)
                if txt:
                    cands.append(txt)
        if not cands:
            cands.append(soup.get_text("\n", strip=True))
        cands.sort(key=len, reverse=True)
        txt = cands[0] if cands else ""
        return txt.strip() or None
    except Exception:
        return None

# 웹 검색을 한 번 수행하는 핵심 함수
def _search_once(query: str, max_results: int = 6, region: str = "wt-wt") -> List[Dict[str, str]]:
    """
    백엔드 선택 순서:
      1) WEB_SEARCH_BACKEND 로 명시된 엔진
      2) ddgs -> duckduckgo_search -> html (자동 폴백)
    ddgs/duckduckgo_search는 verify 제어가 어려우므로 TLS 에러 시 자동 폴백합니다.
    """
    # 1) 강제 백엔드
    backend = WEB_SEARCH_BACKEND
    items: List[Dict[str, str]] = []
    # ddgs 강제
    if backend == "ddgs":
        try:
            if not _have_ddgs:
                raise RuntimeError("ddgs 모듈 없음")
            from ddgs.exceptions import DDGSException  # type: ignore
            with DDGS() as s:
                for r in s.text(query, max_results=max_results, safesearch="moderate", region=region):
                    url = (r.get("href") or r.get("url") or "").strip()
                    title = (r.get("title") or "").strip() or url
                    if not url or not _host_ok(url):
                        continue
                    items.append({"title": title, "url": url, "snippet": r.get("body") or ""})
                    if len(items) >= max_results: break
            return items
        except Exception:
            return _search_once_html(query, max_results, region)
    # duckduckgo_search 강제
    if backend == "duckduckgo_search":
        try:
            if not _have_ddgsearch:
                raise RuntimeError("duckduckgo_search 모듈 없음")
            with LEGACY_DDGS() as s:
                for r in s.text(query, max_results=max_results, safesearch="moderate", region=region):
                    url = (r.get("href") or r.get("url") or "").strip()
                    title = (r.get("title") or "").strip() or url
                    if not url or not _host_ok(url):
                        continue
                    items.append({"title": title, "url": url, "snippet": r.get("body") or ""})
                    if len(items) >= max_results: break
            return items
        except Exception:
            return _search_once_html(query, max_results, region)
    # html 강제
    if backend == "html":
        return _search_once_html(query, max_results, region)

    # 2) 자동(우선 ddgs 시도 -> 실패 시 duckduckgo_search -> 실패 시 html)
    if _have_ddgs:
        try:
            from ddgs.exceptions import DDGSException  # type: ignore
            with DDGS() as s:
                for r in s.text(query, max_results=max_results, safesearch="moderate", region=region):
                    url = (r.get("href") or r.get("url") or "").strip()
                    title = (r.get("title") or "").strip() or url
                    if not url or not _host_ok(url):
                        continue
                    items.append({"title": title, "url": url, "snippet": r.get("body") or ""})
                    if len(items) >= max_results: break
            return items
        except Exception:
            # TLS / DDGSException -> 다음 백엔드
            pass
    if _have_ddgsearch:
        try:
            with LEGACY_DDGS() as s:
                for r in s.text(query, max_results=max_results, safesearch="moderate", region=region):
                    url = (r.get("href") or r.get("url") or "").strip()
                    title = (r.get("title") or "").strip() or url
                    if not url or not _host_ok(url):
                        continue
                    items.append({"title": title, "url": url, "snippet": r.get("body") or ""})
                    if len(items) >= max_results: break
            return items
        except Exception:
            pass
    # 최후: html 파서
    return _search_once_html(query, max_results, region)

# 웹 검색에 사용할 쿼리(query) 문자열들을 자동 생성하는 함수
def _build_queries(user_query: str) -> List[str]:
    qs = [user_query]
    m = re.search(r"(ORA-\d{5})", (user_query or "").upper())
    if m:
        code  = m.group(1)
        short = code[:8]
        qs += [
            f'"{code}"',                            # 정확 매칭
            f'"{code}" Oracle',
            f'{code.replace("-", " ")} site:docs.oracle.com',
            f'"{code}" site:docs.oracle.com',
            f'"{code}" site:oracle-base.com',
            f'{short} Oracle error',
            'ORA- error code list site:docs.oracle.com',
            'list of ORA- codes oracle-base',
            f'"{code}" "does not exist" Oracle',
            f'"{code}" site:community.oracle.com',
            f'"{code}" site:asktom.oracle.com',
        ]
    else:
        qs += [
            f'{user_query} site:docs.oracle.com',
            f'{user_query} Oracle error',
        ]
    seen, out = set(), []
    for q in qs:
        if q not in seen:
            out.append(q); seen.add(q)
    return out

# 여러 검색 결과나 처리 결과를 “모아(collect)” 하나의 리스트나 딕셔너리 형태로 정리하는 내부 유틸리티 함수
def _collect(queries: List[str], min_len: int, max_results: int = 6, *, code: str | None = None) -> List[Dict[str, str]]:
    collected: List[Dict[str, str]] = []
    seen_urls = set()
    for q in queries:
        for item in _search_once(q, max_results=max_results, region="wt-wt"):
            url = item["url"]
            if url in seen_urls:
                continue
            text = _fetch_readable(url)
            snippet = item.get("snippet") or ""
            title = item.get("title") or ""
            # 🔒 엄격 매칭: ORA 코드가 본문/제목/URL/스니펫 어디에도 없으면 버림
            if STRICT_ORA_MATCH and code:
                if not _hit_contains_code(code, url=url, title=title, text=(text or ""), snippet=snippet):
                    continue
            # 길이컷 (짧아도 스니펫이 있으면 수용)
            if text and len(text) > min_len:
                collected.append({"title": title or url, "url": url, "text": text})
                seen_urls.add(url)
            elif text:
                collected.append({"title": title or url, "url": url, "text": text})
                seen_urls.add(url)
            elif snippet:
                collected.append({"title": title or url, "url": url, "text": snippet})
                seen_urls.add(url)
    return collected

# 웹 검색을 “안전하게(safely)” 수행하는 함수
def search_web_safely(user_query: str, max_results: int = 6) -> Tuple[List[Dict[str, str]], List[str]]:
    queries = _build_queries(user_query)
    code = _extract_ora_code(user_query)  # ← 추가

    primary = _collect(queries, min_len=MIN_LEN_PRIMARY, max_results=max_results, code=code)
    if primary:
        return primary, queries

    secondary = _collect(queries, min_len=MIN_LEN_SECONDARY, max_results=max_results, code=code)
    if secondary:
        return secondary, queries

    tertiary = _collect(queries, min_len=MIN_LEN_SECONDARY, max_results=max_results, code=code)
    return tertiary, queries
