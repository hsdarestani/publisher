"""Read-only public checks against the canonical TaskService deployment."""
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

origin = "https://taskservice.smarbiz.sbs"
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (390, 1440):
        page = browser.new_page(viewport={"width": width, "height": 900})
        response = page.goto(origin, wait_until="domcontentloaded", timeout=20000)
        assert response and response.ok
        url = urlparse(page.url)
        assert url.scheme == "https" and url.netloc == "taskservice.smarbiz.sbs"
        parts = url.path.strip("/").split("/")
        assert len(parts) == 2 and parts[0] == "unternehmen"
        api = origin + "/api/v1/tenants/" + parts[1]
        catalog = page.request.get(api + "/catalog")
        assert catalog.ok
        entries = catalog.json()
        assert all(isinstance(row.get("formVersion"), str) for row in entries)
        expect(page.get_by_role("heading", name="Elektroservice anfragen")).to_be_visible()
        if entries:
            page.get_by_role("button", name=entries[0]["label"], exact=True).click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.keyboard.press("Escape")
        else:
            expect(page.get_by_text("Dieser Betrieb nimmt derzeit keine Online-Anfragen an.")).to_be_visible()
        assert page.request.get(origin + "/api/v1/platform/overview").status in (401, 403)
        assert page.request.get(api + "/requests").status in (401, 403)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.close()
    browser.close()
