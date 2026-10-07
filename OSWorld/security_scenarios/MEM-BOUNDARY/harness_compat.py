#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ONBOARDING-MEMORY 호환 덧대기 — 하네스 두 곳의 차이를 이 폴더 안에서만 메운다.

자체 러너(run_onboarding_memory.py)가 기대하는 하네스 기능 중, 이 레포의 하네스에 없는 것이 둘
있다. 벤더·stock 코드는 고치지 않는다 — 프로세스 안에서 **런타임에** 덧댄다.
이 파일을 지우면(또는 apply() 를 안 부르면) 그대로 원복이다. 하네스가 이미 같은 기능을 갖고
있으면 아무것도 하지 않는다.

1) Session(image_delivery_policy=...)
   자체 러너는 이 인자를 넘긴다. 이 하네스의 Session 은 모른다(TypeError). 이 하네스는 이미지를
   항상 폭 상한(width-capped)으로 보낸다 = 자체 러너의 기본값과 같은 동작이다. 그래서 그 값만
   받아 주고, 다른 값("source-native")은 지원하지 않는다고 거부한다.

2) 크롬 getter — 시나리오 호스트 주소 정규화
   주소창 접근성 텍스트에는 스킴이 없는 `onboarding-lab.internal:8080/...` 가 나온다. 이것을
   http:// 로 읽어야 활성 탭 본문을 얻고 '페이지 준비됨' 판정이 선다. 함께 쓰이는 주소 동일성
   비교·절대 URL 검사·준비 실패 표기(page_readiness_failure)를 같은 규칙으로 맞춘다.
   이 둘은 판정이 아니라 **판정의 전제**다 — 빠지면 전 시행이 '준비 실패'로 무효가 된다.
"""
from __future__ import annotations

import importlib
import inspect
import re
import time
from typing import Any, Dict
from urllib.parse import unquote, urlparse


def _patch_session() -> str:
    from redteam import run_cua

    base = run_cua.Session
    if getattr(base, "_scenario_compat", False):
        return "shim(already)"
    if "image_delivery_policy" in inspect.signature(base.__init__).parameters:
        return "native"

    class Session(base):                                  # type: ignore[valid-type,misc]
        _scenario_compat = True

        def __init__(self, *args, image_delivery_policy: str = "width-capped", **kwargs):
            if image_delivery_policy != "width-capped":
                raise ValueError(
                    f"이 하네스는 image_delivery_policy='width-capped' 만 지원합니다 "
                    f"(요청: {image_delivery_policy!r}).")
            super().__init__(*args, **kwargs)
            self.image_delivery_policy = "width-capped"

    Session.__name__ = Session.__qualname__ = base.__name__
    Session.__module__ = base.__module__
    run_cua.Session = Session
    return "shim"


def _patch_chrome() -> str:
    chrome = importlib.import_module("desktop_env.evaluators.getters.chrome")
    existing = getattr(chrome, "_canonical_url_identity", None)
    if existing is not None:        # 하네스가 이미 갖고 있거나, 이 파일이 이미 덧댄 경우
        return "patched(already)" if getattr(existing, "_scenario_compat", False) else "native"
    original_normalize = chrome._normalize_access_tree_url_text

    def _normalize_access_tree_url_text(raw_text: str, goto_prefix: str) -> str:
        text = raw_text.strip()
        # 크로미움은 로컬 시나리오 호스트의 주소창 텍스트에서 스킴을 뺀다. 이 호스트는 일반
        # 스킴 정규식에도 (가짜 스킴으로) 걸리므로, 일반 규칙보다 먼저 명시적으로 처리한다.
        if not re.match(r"^https?://", text, flags=re.IGNORECASE):
            authority_text = text[2:] if text.startswith("//") else text
            try:
                host = (urlparse(f"//{authority_text}").hostname or "").casefold()
            except ValueError:
                host = ""
            if host == "onboarding-lab.internal":
                return f"http://{authority_text}"
        return original_normalize(raw_text, goto_prefix)

    def _canonical_url_identity(url: str):
        """브라우저 문서 하나를 가리키는 URL 필드(스킴·호스트·실효 포트·경로·쿼리·프래그먼트).
        부분 문자열 비교가 아니라 필드 비교다 — 일회성 부트스트랩 쿼리를 history.replaceState 로
        지우는 시나리오라서 주소창 URL 과 CDP page.url 이 이 규칙으로 일치한다."""
        if not isinstance(url, str):
            return None
        absolute = _normalize_access_tree_url_text(url, "")
        try:
            parsed = urlparse(absolute)
            scheme = parsed.scheme.casefold()
            hostname = (parsed.hostname or "").casefold()
            port = parsed.port
        except ValueError:
            return None
        if scheme not in {"http", "https"} or not hostname:
            return None
        if port is None:
            port = 80 if scheme == "http" else 443
        path = unquote(parsed.path or "/")
        if path != "/":
            path = path.rstrip("/") or "/"
        query = unquote(parsed.query or "")
        fragment = unquote(parsed.fragment or "")
        return scheme, hostname, port, path, query, fragment

    def _urls_identify_same_document(expected: str, actual: str) -> bool:
        expected_identity = _canonical_url_identity(expected)
        actual_identity = _canonical_url_identity(actual)
        return expected_identity is not None and expected_identity == actual_identity

    def _absolute_navigation_url(url: str):
        """Page.goto 에 줘도 안전한 절대 http(s) URL, 아니면 None."""
        absolute = _normalize_access_tree_url_text(url, "")
        return absolute if _canonical_url_identity(absolute) is not None else None

    def get_active_tab_url_and_body_text(env, config: Dict[str, Any]):
        """활성 탭의 URL 과 본문 텍스트. 탭을 새로고침하지 않는다(접근성 트리에서 URL 을 읽음).
        준비 실패는 예외가 아니라 page_readiness_failure 필드로 알린다."""
        log = chrome.logger
        active_tab_url = chrome.get_active_url_from_accessTree(env, config)
        if not isinstance(active_tab_url, str):
            log.error("[ACTIVE_TAB_BODY] Failed to get the url of active tab")
            return {"url": "", "body": "", "page_readiness_failure": True,
                    "readiness_error": "active_tab_url_unavailable"}

        navigation_url = _absolute_navigation_url(active_tab_url)
        if navigation_url is None:
            log.error(f"[ACTIVE_TAB_BODY] Refusing non-absolute URL: {active_tab_url}")
            return {"url": active_tab_url, "body": "", "page_readiness_failure": True,
                    "readiness_error": "active_tab_url_is_not_absolute_http"}
        active_tab_url = navigation_url
        log.info(f"[ACTIVE_TAB_BODY] Active tab URL: {active_tab_url}")

        remote_debugging_url = f"http://{env.vm_ip}:{env.chromium_port}"
        max_retries = 2
        timeout_ms = 60000
        for attempt in range(max_retries):
            try:
                with chrome.sync_playwright() as p:
                    try:
                        browser = p.chromium.connect_over_cdp(remote_debugging_url)
                    except Exception as e:                    # noqa: BLE001
                        log.error(f"[ACTIVE_TAB_BODY] Failed to connect to Chrome instance: {e}")
                        return {"url": active_tab_url, "body": "", "page_readiness_failure": True,
                                "readiness_error":
                                    f"cdp_connection_failed: {type(e).__name__}: {e}"}

                    # 이미 열린 탭 중 같은 문서를 우선 쓴다 — 새로고침하면 쿠키·상태를 잃을 수 있다.
                    target_page = None
                    for context in browser.contexts:
                        for page in context.pages:
                            if _urls_identify_same_document(active_tab_url, page.url):
                                target_page = page
                                break
                        if target_page is not None:
                            break

                    body = ""
                    readiness_error = None
                    matched_page_url = target_page.url if target_page is not None else None
                    fallback_page = None
                    try:
                        if target_page is not None:
                            body = target_page.evaluate(
                                "document.body ? document.body.innerText : ''") or ""
                        else:
                            log.warning(f"[ACTIVE_TAB_BODY] No open tab matched "
                                        f"{active_tab_url}; opening a new page")
                            fallback_page = browser.new_page()
                            fallback_page.set_default_timeout(timeout_ms)
                            fallback_page.goto(navigation_url, wait_until="load",
                                               timeout=timeout_ms)
                            matched_page_url = fallback_page.url
                            body = fallback_page.evaluate(
                                "document.body ? document.body.innerText : ''") or ""
                    except Exception as e:                    # noqa: BLE001
                        log.error(f"[ACTIVE_TAB_BODY] Failed to read body text: {e}")
                        readiness_error = f"{type(e).__name__}: {e}"
                    finally:
                        if fallback_page is not None:
                            try:
                                fallback_page.close()
                            except Exception:                 # noqa: BLE001
                                pass
                        browser.close()

                    return {"url": active_tab_url, "body": body,
                            "matched_page_url": matched_page_url,
                            "page_readiness_failure": readiness_error is not None,
                            "readiness_error": readiness_error}
            except Exception as e:                            # noqa: BLE001
                log.error(f"[ACTIVE_TAB_BODY] Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(3)

        return {"url": active_tab_url, "body": "", "page_readiness_failure": True,
                "readiness_error": "active_tab_body_retries_exhausted"}

    _canonical_url_identity._scenario_compat = True        # 두 번 덧대지 않도록 표식
    chrome._normalize_access_tree_url_text = _normalize_access_tree_url_text
    chrome._canonical_url_identity = _canonical_url_identity
    chrome._urls_identify_same_document = _urls_identify_same_document
    chrome._absolute_navigation_url = _absolute_navigation_url
    chrome.get_active_tab_url_and_body_text = get_active_tab_url_and_body_text
    # 패키지가 이름을 직접 import 해 둔 경우(`from ...getters import get_active_tab_...`)도 덮는다.
    pkg = importlib.import_module("desktop_env.evaluators.getters")
    pkg.get_active_tab_url_and_body_text = get_active_tab_url_and_body_text
    return "patched"


def apply() -> Dict[str, str]:
    """필요한 덧대기만 적용하고, 무엇이 어떻게 처리됐는지 돌려준다 (로그용)."""
    return {"session_image_delivery": _patch_session(),
            "chrome_url_normalization": _patch_chrome()}
