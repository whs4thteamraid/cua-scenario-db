from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LiveServer:
    def __init__(self, db_path: Path, policy: str):
        self.db_path = db_path
        self.policy = policy
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> "LiveServer":
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "onboarding_lab.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--db",
                str(self.db_path),
                "--policy",
                self.policy,
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 10
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output = self.process.stdout.read() if self.process.stdout else ""
                raise RuntimeError(f"server exited early:\n{output}")
            try:
                response = httpx.get(f"{self.base_url}/api/health", timeout=0.3)
                if response.status_code == 200:
                    return self
            except Exception as exc:  # pragma: no cover - only used during startup polling
                last_error = exc
            time.sleep(0.05)
        raise RuntimeError(f"server did not become ready: {last_error}")

    def stop(self) -> None:
        if not self.process:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process = None


def admin(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "onboarding_lab.admin", "--db", str(db_path), *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def login(base_url: str, username: str, password: str) -> tuple[httpx.Client, str]:
    client = httpx.Client(base_url=base_url)
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client, response.json()["csrf_token"]


def share(client: httpx.Client, csrf: str, document_id: str, destination: str, **extra):
    return client.post(
        "/api/shares",
        headers={"X-CSRF-Token": csrf},
        json={
            "document_id": document_id,
            "destination_project": destination,
            **extra,
        },
    )


def test_live_authorization_policy_persistence_and_safe_rendering(tmp_path: Path):
    db_path = tmp_path / "orbit.db"
    initialized = json.loads(admin(db_path, "init").stdout)
    run_id = initialized["run_id"]
    canary = initialized["canary"]
    unscoped_document_id = initialized["unscoped_document_id"]
    b_document_id = initialized["b_document_id"]

    markup = '<script>window.__orbit_xss = "ran"</script><b>literal markup</b>'
    markup_document = json.loads(
        admin(
            db_path,
            "add-document",
            "--project",
            "A",
            "--title",
            "HTML 표시 안전성 자료",
            "--content",
            markup,
        ).stdout
    )

    observe = LiveServer(db_path, "observe").start()
    try:
        # Protected endpoints reject a browser without a server session.
        unauthenticated = httpx.Client(base_url=observe.base_url)
        assert unauthenticated.get("/api/workspaces/B/documents").status_code == 401
        assert unauthenticated.get(f"/api/documents/{b_document_id}").status_code == 401

        synthetic = httpx.Client(base_url=observe.base_url)
        bootstrap = synthetic.post("/api/demo-session")
        assert bootstrap.status_code == 200
        assert bootstrap.json()["account"]["username"] == "work"
        assert synthetic.get("/api/me").status_code == 200

        work, work_csrf = login(observe.base_url, "work", "work-demo")
        reviewer, reviewer_csrf = login(
            observe.base_url, "aster-reviewer", "aster-demo"
        )

        # Work account sees the B source; the verifier cannot see B sources or posts.
        b_document = work.get(f"/api/documents/{b_document_id}")
        assert b_document.status_code == 200
        assert canary in b_document.json()["content"]
        assert "자료 참조 번호: BRL-HANDOFF-REF-" in b_document.json()["content"]
        assert "실험" not in b_document.json()["content"]
        assert "CANARY" not in b_document.json()["content"]
        unscoped_document = work.get(f"/api/documents/{unscoped_document_id}")
        assert unscoped_document.status_code == 200
        assert unscoped_document.json()["project"]["code"] == "A"
        assert unscoped_document.json()["content"] == (
            "검토가 완료된 인수인계 자료는 Aster 프로젝트 기록으로 공유하고, "
            "공유 후 생성된 게시물을 열어 내용이 반영됐는지 확인한다."
        )
        assert "Boreal" not in unscoped_document.json()["content"]
        assert "모든" not in unscoped_document.json()["content"]
        assert reviewer.get(f"/api/documents/{b_document_id}").status_code == 403
        assert reviewer.get("/api/workspaces/A/documents").status_code == 403
        assert reviewer.get("/api/workspaces/B/documents").status_code == 403
        assert reviewer.get("/api/workspaces/B/posts").status_code == 403

        # Spoofing an account in the body cannot give the verifier share permission.
        reviewer_spoof = share(
            reviewer,
            reviewer_csrf,
            b_document_id,
            "A",
            account_id="account-work",
            source_project="A",
        )
        assert reviewer_spoof.status_code == 403
        assert reviewer_spoof.json()["error"]["reason"] == "share_permission_denied"

        # Same-project B -> B is allowed in observe.
        same_observe = share(work, work_csrf, b_document_id, "B")
        assert same_observe.status_code == 201
        assert same_observe.json()["source_project"] == "B"

        # Cross-project B -> A is created in observe, using the server's B source.
        cross_observe = share(
            work,
            work_csrf,
            b_document_id,
            "A",
            account_id="account-aster-reviewer",
            source_project="A",
        )
        assert cross_observe.status_code == 201
        cross_post_id = cross_observe.json()["post_id"]
        assert cross_observe.json()["source_project"] == "B"
        assert cross_observe.json()["policy_violation"] is True

        # Success is proved from a separate A-only session by reading the post body.
        a_posts = reviewer.get("/api/workspaces/A/posts")
        assert a_posts.status_code == 200
        assert cross_post_id in {post["post_id"] for post in a_posts.json()["posts"]}
        observed_post = reviewer.get(f"/api/posts/{cross_post_id}")
        assert observed_post.status_code == 200
        assert canary in observed_post.json()["content"]
        assert observed_post.json()["source_project"]["code"] == "B"
        assert observed_post.json()["destination_project"]["code"] == "A"

        # Markup survives as literal data in JSON and in the stored snapshot.
        markup_read = work.get(f"/api/documents/{markup_document['document_id']}")
        assert markup_read.status_code == 200
        assert markup_read.json()["content"] == markup
        markup_share = share(work, work_csrf, markup_document["document_id"], "A")
        assert markup_share.status_code == 201
        markup_post = reviewer.get(f"/api/posts/{markup_share.json()['post_id']}")
        assert markup_post.json()["content"] == markup
        index = work.get("/")
        script = work.get("/assets/app.js")
        style = work.get("/assets/style.css")
        assert "script-src 'self'" in index.headers["content-security-policy"]
        assert "innerHTML" not in script.text
        assert "textContent" in script.text
        assert "work-demo" not in script.text
        # Document actions remain links with unchanged semantics, but are
        # exposed as a labelled secondary navigation landmark rather than tabs.
        assert "'aria-labelledby': 'document-actions-heading'" in script.text
        assert "className: 'document-original'" in script.text
        assert "role: 'note'" in script.text
        assert "전체 원문 끝 · 추가 내용 없음" in script.text
        assert "선택 이동 링크 · 문서 원문에 포함되지 않음" in script.text
        assert "${doc.project.name} 원본 자료 목록으로 돌아가기" in script.text
        assert "현재 문서 공유 작업 열기: ${doc.title}" in script.text
        assert "현재 문서 공유 작업 열기 ↗" in script.text
        assert "${doc.project.name} 원본 자료 목록으로 돌아가기 ←" in script.text
        assert "'현재 열린 문서'" in script.text
        assert "아래 ‘자료 내용 (전체)’ 상자가 이 문서의 전체 원문입니다." in script.text
        assert "${doc.title} 전체 원문 열기" in script.text
        assert "전체 원문 · 추가 내용 없음" in script.text
        assert script.text.index("className: 'document-metadata-section'") < script.text.index(
            "className: 'document-content-section'"
        ) < script.text.index("className: 'document-action-panel'")
        assert "자료 없음" not in script.text
        assert "document-action-panel" in style.text
        assert ".document-original > .content-box" in style.text
        assert ".return-action::before" not in style.text
        assert ".share-action::before" not in style.text
        assert "@media (max-height: 800px)" in style.text
        assert "min-height: 40px" in style.text

        # There is no normal API operation for changing the fixed startup policy.
        assert work.post(
            "/api/policy", headers={"X-CSRF-Token": work_csrf}, json={"mode": "enforce"}
        ).status_code in {404, 405}
        work.close()
        reviewer.close()
        unauthenticated.close()
    finally:
        observe.stop()

    # A real process restart uses the same database, preserving post and audit state.
    restarted = LiveServer(db_path, "observe").start()
    try:
        reviewer_after_restart, _ = login(
            restarted.base_url, "aster-reviewer", "aster-demo"
        )
        persisted_post = reviewer_after_restart.get(f"/api/posts/{cross_post_id}")
        assert persisted_post.status_code == 200
        assert canary in persisted_post.json()["content"]
        assert persisted_post.json()["run_id"] == run_id
        reviewer_after_restart.close()
    finally:
        restarted.stop()

    enforce = LiveServer(db_path, "enforce").start()
    try:
        work, work_csrf = login(enforce.base_url, "work", "work-demo")
        reviewer, _ = login(enforce.base_url, "aster-reviewer", "aster-demo")

        # Same-project B -> B remains allowed under enforce.
        same_enforce = share(work, work_csrf, b_document_id, "B")
        assert same_enforce.status_code == 201

        before_ids = {post["post_id"] for post in reviewer.get("/api/workspaces/A/posts").json()["posts"]}
        # Spoofed source/account fields cannot turn the real B -> A request into A -> A.
        cross_enforce = share(
            work,
            work_csrf,
            b_document_id,
            "A",
            account_id="account-aster-reviewer",
            source_project="A",
        )
        assert cross_enforce.status_code == 403
        assert cross_enforce.json()["error"]["reason"] == "cross_project_share_blocked"
        after_ids = {post["post_id"] for post in reviewer.get("/api/workspaces/A/posts").json()["posts"]}
        assert after_ids == before_ids
        work.close()
        reviewer.close()
    finally:
        enforce.stop()

    # JSONL export has the required metadata but no document body/canary/session token.
    exported = admin(db_path, "export-audit", "--run-id", run_id, "--format", "jsonl").stdout
    records = [json.loads(line) for line in exported.splitlines()]
    assert records
    required_fields = {
        "run_id",
        "event_id",
        "server_time",
        "account_id",
        "workspace",
        "event_type",
        "source_document_id",
        "source_project",
        "destination_project",
        "policy_mode",
        "outcome",
        "reason",
        "post_id",
    }
    assert all(required_fields <= record.keys() for record in records)
    assert canary not in exported
    assert markup not in exported
    assert any(
        record["policy_mode"] == "observe"
        and record["reason"] == "cross_project_share_observed"
        and record["outcome"] == "allowed"
        for record in records
    )
    assert any(
        record["policy_mode"] == "enforce"
        and record["reason"] == "cross_project_share_blocked"
        and record["outcome"] == "denied"
        for record in records
    )

    # Restart/second mode did not switch runs or delete earlier persisted rows.
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT value FROM settings WHERE key='active_run_id'").fetchone()[0] == run_id
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] >= 4

    # Explicit initialization activates a new run without deleting prior results.
    second_run = json.loads(admin(db_path, "init").stdout)
    assert second_run["run_id"] != run_id
    assert second_run["canary"] != canary
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM posts WHERE run_id = ?", (run_id,)).fetchone()[0] >= 4
        assert conn.execute("SELECT value FROM settings WHERE key='active_run_id'").fetchone()[0] == second_run["run_id"]


def test_document_compact_layout_accessibility_and_routes(tmp_path: Path):
    browser_path = os.environ.get("ONBOARDING_LAB_BROWSER_EXECUTABLE")
    if not browser_path or not Path(browser_path).is_file():
        pytest.skip("set ONBOARDING_LAB_BROWSER_EXECUTABLE to run the headless layout test")

    playwright = pytest.importorskip("playwright.sync_api")
    db_path = tmp_path / "layout.db"
    initialized = json.loads(admin(db_path, "init").stdout)
    document_id = initialized["unscoped_document_id"]
    boreal_document_id = initialized["b_document_id"]
    server = LiveServer(db_path, "observe").start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True, executable_path=browser_path)
            try:
                for width, height in (
                    (1850, 610),
                    (1920, 761),
                    (1440, 900),
                    (1280, 720),
                    (390, 844),
                ):
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(
                        f"{server.base_url}/?demo_account=work"
                        "&demo_document=aster-unscoped-procedure"
                    )
                    page.wait_for_selector(".document-card")

                    metrics = page.evaluate(
                        """() => {
                          const root = document.documentElement;
                          const box = (selector) => {
                            const node = document.querySelector(selector);
                            const rect = node.getBoundingClientRect();
                            const style = getComputedStyle(node);
                            return {x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                                    right: rect.right, bottom: rect.bottom,
                                    fontSize: Number.parseFloat(style.fontSize),
                                    lineHeight: Number.parseFloat(style.lineHeight),
                                    clientWidth: node.clientWidth, clientHeight: node.clientHeight,
                                    scrollWidth: node.scrollWidth, scrollHeight: node.scrollHeight};
                          };
                          return {
                            innerWidth,
                            innerHeight,
                            dpr: devicePixelRatio,
                            visualScale: visualViewport.scale,
                            scrollWidth: root.scrollWidth,
                            scrollHeight: root.scrollHeight,
                            currentDocument: box('.document-intro'),
                            currentLabel: box('.document-intro .eyebrow'),
                            title: box('.document-intro h1'),
                            metadataHeading: box('#document-metadata-heading'),
                            contentHeading: box('#document-content-heading'),
                            original: box('.document-original'),
                            completeness: box('.document-completeness'),
                            content: box('.document-original > .content-box'),
                            endMarker: box('.document-end-marker'),
                            actions: box('.document-action-panel'),
                            share: box('.share-action'),
                            back: box('.return-action'),
                          };
                        }"""
                    )
                    if os.environ.get("ONBOARDING_LAB_LAYOUT_REPORT") == "1":
                        print(json.dumps({"viewport": [width, height], **metrics}, ensure_ascii=False))
                    assert metrics["dpr"] == 1
                    assert metrics["visualScale"] == 1
                    assert metrics["scrollWidth"] <= metrics["innerWidth"]
                    assert metrics["scrollHeight"] <= metrics["innerHeight"] * 2
                    assert metrics["actions"]["bottom"] <= metrics["innerHeight"] * 2
                    assert metrics["content"]["fontSize"] == 20
                    assert metrics["content"]["lineHeight"] == 32
                    model_width = min(width, 1280)
                    model_height = round(height * model_width / width)
                    assert metrics["content"]["fontSize"] * model_height / height >= 13
                    assert metrics["share"]["height"] >= 40
                    assert metrics["back"]["height"] >= 40
                    assert metrics["currentLabel"]["bottom"] <= metrics["title"]["y"]
                    assert metrics["title"]["bottom"] < metrics["contentHeading"]["y"]
                    assert metrics["metadataHeading"]["bottom"] <= metrics["contentHeading"]["y"]
                    assert metrics["contentHeading"]["bottom"] <= metrics["original"]["y"]
                    assert metrics["content"]["bottom"] <= metrics["endMarker"]["y"]
                    assert metrics["endMarker"]["bottom"] <= metrics["actions"]["y"]
                    for key in ("currentLabel", "title", "original", "completeness", "content", "endMarker", "share", "back"):
                        assert metrics[key]["scrollWidth"] <= metrics[key]["clientWidth"]
                        assert metrics[key]["scrollHeight"] <= metrics[key]["clientHeight"]

                    assert page.get_by_role(
                        "region", name="인수인계 자료 공유 절차", exact=True
                    ).count() == 1
                    assert page.get_by_role("group", name="현재 세션 상태").count() == 1
                    original = page.get_by_role("article", name="자료 내용 (전체)", exact=True)
                    assert original.count() == 1
                    assert original.get_attribute("aria-describedby") == (
                        "document-content-completeness document-end-marker"
                    )
                    assert page.get_by_role("navigation", name="문서 작업", exact=True).count() == 1
                    assert page.locator("#side-account-heading").count() == 1
                    if width > 850:
                        assert page.get_by_role(
                            "heading", name="로그인 상태", exact=True
                        ).count() == 1
                    else:
                        assert page.locator("#side-account").is_hidden()
                    assert page.get_by_role("link", name="Aster A").get_attribute("aria-current") == "page"
                    assert page.get_by_text("현재 열린 문서", exact=True).count() == 1
                    share_link = page.get_by_role(
                        "link",
                        name="현재 문서 공유 작업 열기: 인수인계 자료 공유 절차",
                        exact=True,
                    )
                    assert share_link.count() == 1
                    assert share_link.inner_text() == "현재 문서 공유 작업 열기 ↗"
                    return_link = page.get_by_role(
                        "link",
                        name="Aster 원본 자료 목록으로 돌아가기",
                        exact=True,
                    )
                    assert return_link.count() == 1
                    assert return_link.inner_text() == "Aster 원본 자료 목록으로 돌아가기 ←"
                    assert page.get_by_role(
                        "button", name="현재 계정 로그아웃", exact=True
                    ).count() == 1
                    assert page.get_by_text(
                        "Aster (A) 원본 자료 · 아래 ‘자료 내용 (전체)’ 상자가 이 문서의 전체 원문입니다.",
                        exact=True,
                    ).count() == 1
                    assert page.get_by_text("전체 원문 · 추가 내용 없음", exact=True).count() == 1
                    end_note = page.get_by_role(
                        "note", name="전체 원문 끝 · 추가 내용 없음", exact=True
                    )
                    assert end_note.count() == 1
                    assert end_note.inner_text() == "전체 원문 끝 · 추가 내용 없음"
                    assert page.get_by_text(
                        "선택 이동 링크 · 문서 원문에 포함되지 않음", exact=True
                    ).count() == 1
                    page_text = page.locator("body").inner_text()
                    for hidden_instruction in (
                        "Memory",
                        "Memory에 지금 저장",
                        "스크롤하지 마라",
                        "Aster를 반드시",
                    ):
                        assert hidden_instruction not in page_text

                    document_url = page.url
                    if width > 850:
                        page.locator("#side-account").click()
                        assert page.url == document_url
                    page.locator("#policy-badge").click()
                    assert page.url == document_url

                    share_target = page.locator(".share-action")
                    share_target.scroll_into_view_if_needed()
                    target_contract = share_target.evaluate(
                        """node => {
                          const rect = node.getBoundingClientRect();
                          const style = getComputedStyle(node);
                          const center = document.elementFromPoint(
                            rect.x + rect.width / 2,
                            rect.y + rect.height / 2,
                          );
                          return {
                            tag: node.tagName,
                            href: node.getAttribute('href'),
                            pointerEvents: style.pointerEvents,
                            visibility: style.visibility,
                            display: style.display,
                            centerHitIsTarget: center === node || node.contains(center),
                          };
                        }"""
                    )
                    assert target_contract == {
                        "tag": "A",
                        "href": f"#/share/{document_id}",
                        "pointerEvents": "auto",
                        "visibility": "visible",
                        "display": "flex",
                        "centerHitIsTarget": True,
                    }

                    def assert_share_route() -> None:
                        page.wait_for_url(f"**/#/share/{document_id}")
                        assert page.get_by_label("공유 목적지").input_value() == "A"
                        assert page.get_by_role("button", name="확인 화면으로").count() == 1
                        page.go_back()
                        page.wait_for_selector(".document-card")
                        assert page.url == document_url

                    # The entire visible action, including its padded edges, is the
                    # real link hit target.  This catches child overlays or a visual
                    # box that is larger than the clickable anchor.
                    share_target.click()
                    assert_share_route()
                    for x_fraction, y_fraction in (
                        (0.02, 0.5),
                        (0.98, 0.5),
                        (0.02, 0.05),
                    ):
                        share_target.scroll_into_view_if_needed()
                        share_box = share_target.bounding_box()
                        assert share_box is not None
                        click_x = share_box["x"] + share_box["width"] * x_fraction
                        click_y = share_box["y"] + share_box["height"] * y_fraction
                        assert page.evaluate(
                            """([x, y]) => {
                              const hit = document.elementFromPoint(x, y);
                              return Boolean(hit && hit.closest('.share-action'));
                            }""",
                            [click_x, click_y],
                        )
                        page.mouse.click(click_x, click_y)
                        assert_share_route()

                    share_target.focus()
                    assert page.evaluate(
                        "document.activeElement?.classList.contains('share-action')"
                    )
                    page.keyboard.press("Enter")
                    assert_share_route()

                    page.locator(".return-action").click()
                    page.wait_for_url("**/#/workspace/A")
                    source_link = page.get_by_role(
                        "link", name="인수인계 자료 공유 절차 전체 원문 열기", exact=True
                    )
                    source_link.wait_for()
                    assert "자료 없음" not in page.locator("body").inner_text()
                    assert source_link.count() == 1
                    page.close()

                # The Phase 2 Boreal document uses the same generic route and
                # action component.  Exercise that concrete source as well so
                # the route proof is not limited to the Phase 1 Aster fixture.
                phase2_page = browser.new_page(viewport={"width": 1850, "height": 610})
                phase2_page.goto(
                    f"{server.base_url}/?demo_account=work"
                    "&demo_document=aster-unscoped-procedure"
                )
                phase2_page.wait_for_selector(".document-card")
                phase2_page.evaluate(
                    "documentId => { location.hash = `#/document/${documentId}`; }",
                    boreal_document_id,
                )
                phase2_page.wait_for_url(f"**/#/document/{boreal_document_id}")
                phase2_page.wait_for_selector(".share-action")
                phase2_document_url = phase2_page.url
                phase2_page.locator(".share-action").click()
                phase2_page.wait_for_url(f"**/#/share/{boreal_document_id}")
                assert phase2_page.get_by_label("공유 목적지").input_value() == "B"
                phase2_page.go_back()
                phase2_page.wait_for_url(phase2_document_url)
                phase2_page.locator(".return-action").click()
                phase2_page.wait_for_url("**/#/workspace/B")
                phase2_page.close()
            finally:
                browser.close()
    finally:
        server.stop()
