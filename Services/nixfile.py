import asyncio
import json
import logging
import os
import re
import signal
import threading
import time
import traceback
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from App.config import Settings

logger = logging.getLogger(__name__)

DEBUG_DIR = Path("storage/nixfile-debug")


class NixfileError(Exception):
    pass


class NixfileUploader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._driver: WebDriver | None = None
        self._lock = asyncio.Lock()
        self._logged_in = False
        self._progress: dict | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.nixfile_username and self._settings.nixfile_pass)

    def progress_snapshot(self) -> dict | None:
        snap = self._progress
        return dict(snap) if snap is not None else None

    async def upload(
        self,
        file_path: Path,
        upload_started: threading.Event | None = None,
    ) -> str:
        if not self.enabled:
            raise NixfileError("NIXFILE_USERNAME/NIXFILE_PASS تنظیم نشده است.")
        if not file_path.exists():
            raise NixfileError(f"فایل آپلود پیدا نشد: {file_path}")

        async with self._lock:
            return await asyncio.to_thread(self._upload_sync, file_path, upload_started)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._shutdown_sync)

    def force_shutdown(self) -> None:
        """Synchronous, lock-free, signal-safe driver kill.

        Safe to call from a signal handler or from the main loop while an
        upload thread is still inside selenium. Kills the chromedriver
        subprocess so any pending HTTP calls inside the worker thread
        fail fast instead of looping forever on connection-refused.
        """
        driver = self._driver
        if driver is None:
            return
        self._driver = None
        self._logged_in = False

        process = None
        with suppress(Exception):
            service = getattr(driver, "service", None)
            process = getattr(service, "process", None) if service else None

        if process is not None:
            with suppress(Exception):
                if os.name == "nt":
                    process.kill()
                else:
                    os.kill(process.pid, signal.SIGKILL)
        with suppress(Exception):
            driver.quit()

    def _upload_sync(
        self,
        file_path: Path,
        upload_started: threading.Event | None,
    ) -> str:
        step = "init"
        self._progress = {"percent": 0, "info": "", "state": "preparing"}
        try:
            logger.info("[nixfile] upload starting: file=%s size=%d", file_path, file_path.stat().st_size)
            step = "ensure_login"
            self._ensure_login()
            step = "do_upload"
            url = self._do_upload(file_path, upload_started)
            logger.info("[nixfile] upload finished: url=%s", url)
            return url
        except NixfileError as exc:
            logger.error("[nixfile] step=%s failed: %s", step, exc)
            self._dump_debug(step)
            raise
        except (TimeoutException, NoSuchElementException, WebDriverException) as exc:
            detail = self._format_selenium_error(exc)
            logger.exception("[nixfile] step=%s selenium error: %s", step, detail)
            self._dump_debug(step)
            self._shutdown_sync()
            raise NixfileError(f"[step={step}] {detail}") from exc
        except Exception as exc:
            logger.exception("[nixfile] step=%s unexpected error", step)
            self._dump_debug(step)
            self._shutdown_sync()
            raise NixfileError(f"[step={step}] {exc.__class__.__name__}: {exc}") from exc
        finally:
            self._progress = None

    def _ensure_driver(self) -> WebDriver:
        if self._driver is not None:
            return self._driver

        logger.info("[nixfile] starting Chrome driver (headless=%s)", self._settings.nixfile_headless)
        options = Options()
        if self._settings.nixfile_headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1600,1000")
        options.add_argument("--lang=fa-IR")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        self._driver = webdriver.Chrome(options=options)
        self._driver.set_page_load_timeout(60)
        return self._driver

    def _shutdown_sync(self) -> None:
        if self._driver is not None:
            with suppress(Exception):
                self._driver.quit()
        self._driver = None
        self._logged_in = False

    def _ensure_login(self) -> None:
        driver = self._ensure_driver()
        if self._logged_in and self._on_panel(driver):
            logger.info("[nixfile] reusing existing session")
            return

        if self._try_restore_session(driver):
            self._logged_in = True
            logger.info("[nixfile] session restored from file, url=%s", driver.current_url)
            return

        username = self._settings.nixfile_username or ""
        password = self._settings.nixfile_pass or ""

        logger.info("[nixfile] navigating to login: %s", self._settings.nixfile_login_url)
        driver.get(self._settings.nixfile_login_url)
        logger.info("[nixfile] login page loaded url=%s title=%r", driver.current_url, driver.title)

        username_input = self._wait_visible(
            driver,
            (
                By.XPATH,
                "//input[@type='text' or @type='email' or @type='tel' or "
                "contains(@placeholder,'موبایل') or contains(@placeholder,'ایمیل')]",
            ),
            timeout=30,
            label="username_input",
        )
        username_input.clear()
        username_input.send_keys(username)
        logger.info("[nixfile] username entered")

        self._click_login_button(driver, label="username_submit")

        password_input = self._wait_visible(
            driver,
            (By.XPATH, "//input[@type='password']"),
            timeout=30,
            label="password_input",
        )
        password_input.clear()
        password_input.send_keys(password)
        logger.info("[nixfile] password entered")

        self._click_login_button(driver, label="password_submit")

        WebDriverWait(driver, 45).until(lambda d: self._on_panel(d))
        self._logged_in = True
        logger.info("[nixfile] logged in, current_url=%s", driver.current_url)
        self._save_session(driver)

    def _try_restore_session(self, driver: WebDriver) -> bool:
        session_path = self._settings.nixfile_session_file
        if not session_path.exists():
            return False

        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[nixfile] session file unreadable: %s", exc)
            return False

        cookies = data.get("cookies") or []
        local_storage = data.get("localStorage") or {}
        session_storage = data.get("sessionStorage") or {}
        if not cookies and not local_storage:
            return False

        panel_url = self._settings.nixfile_panel_url
        host = urlparse(panel_url).netloc or "panel.nixfile.com"
        bootstrap_url = f"https://{host}/"

        logger.info("[nixfile] attempting session restore from %s", session_path)
        with suppress(Exception):
            driver.get(bootstrap_url)

        for cookie in cookies:
            sanitized = {k: v for k, v in cookie.items() if k in {
                "name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite"
            }}
            if "expiry" in sanitized:
                with suppress(Exception):
                    sanitized["expiry"] = int(sanitized["expiry"])
            with suppress(Exception):
                driver.add_cookie(sanitized)

        if local_storage:
            with suppress(Exception):
                driver.execute_script(
                    "const d=arguments[0];"
                    "for (const k in d) { try { localStorage.setItem(k, d[k]); } catch(e){} }",
                    local_storage,
                )
        if session_storage:
            with suppress(Exception):
                driver.execute_script(
                    "const d=arguments[0];"
                    "for (const k in d) { try { sessionStorage.setItem(k, d[k]); } catch(e){} }",
                    session_storage,
                )

        target = self._settings.nixfile_panel_url.rstrip("/") + "/media"
        with suppress(Exception):
            driver.get(target)

        if self._on_panel(driver):
            return True

        logger.info("[nixfile] session expired/invalid, falling back to fresh login")
        with suppress(Exception):
            driver.delete_all_cookies()
        return False

    def _save_session(self, driver: WebDriver) -> None:
        session_path = self._settings.nixfile_session_file
        try:
            session_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[nixfile] cannot create session dir: %s", exc)
            return

        cookies = []
        with suppress(Exception):
            cookies = driver.get_cookies()

        local_storage = {}
        session_storage = {}
        with suppress(Exception):
            local_storage = driver.execute_script(
                "const o={}; for (let i=0;i<localStorage.length;i++){"
                "const k=localStorage.key(i); o[k]=localStorage.getItem(k);} return o;"
            ) or {}
        with suppress(Exception):
            session_storage = driver.execute_script(
                "const o={}; for (let i=0;i<sessionStorage.length;i++){"
                "const k=sessionStorage.key(i); o[k]=sessionStorage.getItem(k);} return o;"
            ) or {}

        payload = {
            "saved_at": datetime.now().isoformat(),
            "cookies": cookies,
            "localStorage": local_storage,
            "sessionStorage": session_storage,
        }
        try:
            session_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            logger.info(
                "[nixfile] session saved (cookies=%d, local=%d, session=%d) to %s",
                len(cookies), len(local_storage), len(session_storage), session_path,
            )
        except Exception as exc:
            logger.warning("[nixfile] failed to write session file: %s", exc)

    def _on_panel(self, driver: WebDriver) -> bool:
        try:
            url = driver.current_url
        except Exception:
            return False
        if "/auth/" in url or "/login" in url:
            return False
        if self._settings.nixfile_panel_url not in url:
            return False
        nav_markers = (
            "داشبورد",
            "فایل های من",
            "آپلود فایل",
            "کیف پول",
            "نیکس فایل",
        )
        for marker in nav_markers:
            try:
                driver.find_element(By.XPATH, f"//*[contains(normalize-space(.), '{marker}')]")
                return True
            except NoSuchElementException:
                continue
        return False

    def _click_login_button(self, driver: WebDriver, label: str) -> None:
        candidates = [
            (By.XPATH, "//button[contains(normalize-space(.), 'ورود به نیکس')]"),
            (By.XPATH, "//button[contains(normalize-space(.), 'ادامه')]"),
            (By.XPATH, "//button[@type='submit']"),
        ]
        for locator in candidates:
            try:
                element = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(locator))
                logger.info("[nixfile] clicking %s via %s", label, locator[1])
                element.click()
                return
            except TimeoutException:
                continue
        raise NixfileError(f"دکمه ورود ({label}) پیدا نشد.")

    def _do_upload(
        self,
        file_path: Path,
        upload_started: threading.Event | None,
    ) -> str:
        driver = self._ensure_driver()

        logger.info("[nixfile] ensuring files page, current_url=%s", driver.current_url)
        if "/media" not in driver.current_url:
            self._navigate_to_files(driver)

        self._ensure_files_ui_ready(driver)

        existing_names = self._existing_file_names(driver)
        logger.info("[nixfile] existing file count=%d", len(existing_names))

        file_input = self._find_file_input(driver)
        logger.info("[nixfile] file input found, sending path")
        if upload_started is not None:
            upload_started.set()
        file_input.send_keys(str(file_path.resolve()))

        new_card = self._wait_for_new_card(
            driver,
            existing_names,
            file_path,
            timeout=self._settings.nixfile_upload_timeout,
        )
        logger.info("[nixfile] new card detected")

        return self._copy_link_from_card(driver, new_card)

    def _navigate_to_files(self, driver: WebDriver) -> None:
        target = self._settings.nixfile_panel_url.rstrip("/") + "/media"
        logger.info("[nixfile] navigating directly to %s", target)
        try:
            driver.get(target)
        except WebDriverException as exc:
            logger.warning("[nixfile] direct nav failed: %s; trying sidebar click", exc)
            self._click_sidebar_files(driver)

        try:
            self._wait_files_page_ready(driver)
            logger.info("[nixfile] files page ready, url=%s", driver.current_url)
            return
        except TimeoutException:
            logger.warning("[nixfile] /media did not render files UI; trying sidebar click")

        self._click_sidebar_files(driver)
        self._wait_files_page_ready(driver)
        logger.info("[nixfile] files page ready via sidebar, url=%s", driver.current_url)

    def _click_sidebar_files(self, driver: WebDriver) -> None:
        locators = [
            (By.XPATH, "//aside//button[normalize-space(.)='فایل های من']"),
            (By.XPATH, "//aside//button[contains(normalize-space(.), 'فایل های من')]"),
            (By.XPATH, "//button[contains(normalize-space(.), 'فایل های من')]"),
            (By.XPATH, "//a[contains(normalize-space(.), 'فایل های من')]"),
        ]
        for locator in locators:
            elements = driver.find_elements(*locator)
            if not elements:
                continue
            element = elements[0]
            with suppress(Exception):
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            try:
                element.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", element)
            logger.info("[nixfile] sidebar 'فایل های من' clicked via %s", locator[1])
            return
        raise NixfileError("دکمه 'فایل های من' در سایدبار پیدا نشد.")

    def _wait_files_page_ready(self, driver: WebDriver, timeout: int = 30) -> None:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//button[contains(normalize-space(.), 'آپلود فایل')] | "
                    "//*[self::button or self::a][contains(normalize-space(.), 'پوشه جدید')] | "
                    "//input[@type='file']",
                )
            )
        )

    def _ensure_files_ui_ready(self, driver: WebDriver) -> None:
        for attempt in range(1, 4):
            try:
                self._wait_files_page_ready(driver, timeout=20)
                logger.info("[nixfile] files UI ready on attempt %d", attempt)
                return
            except TimeoutException:
                logger.warning(
                    "[nixfile] files UI not ready (attempt %d); skeletons=%d, retrying",
                    attempt,
                    self._count_skeletons(driver),
                )
                if attempt == 1:
                    with suppress(Exception):
                        driver.refresh()
                elif attempt == 2:
                    logger.warning("[nixfile] invalidating session and re-logging in")
                    self._logged_in = False
                    with suppress(Exception):
                        driver.delete_all_cookies()
                    self._ensure_login()
                    if "/media" not in driver.current_url:
                        self._navigate_to_files(driver)
        raise NixfileError("صفحه فایل ها بارگذاری نشد (UI آپلود ظاهر نشد).")

    @staticmethod
    def _count_skeletons(driver: WebDriver) -> int:
        with suppress(Exception):
            return len(driver.find_elements(By.CSS_SELECTOR, "[class*='skeleton']"))
        return 0

    def _existing_file_names(self, driver: WebDriver) -> set[str]:
        names: set[str] = set()
        for element in driver.find_elements(By.CSS_SELECTOR, "[data-file-name], [title]"):
            try:
                value = element.get_attribute("data-file-name") or element.get_attribute("title")
            except StaleElementReferenceException:
                continue
            if value:
                names.add(value.strip())
        return names

    def _find_file_input(self, driver: WebDriver) -> WebElement:
        for locator in (
            (By.CSS_SELECTOR, "input[type='file']"),
            (By.XPATH, "//input[@type='file']"),
        ):
            elements = driver.find_elements(*locator)
            if elements:
                logger.info("[nixfile] file input located via %s (count=%d)", locator[1], len(elements))
                return elements[0]

        logger.info("[nixfile] no input[type=file] visible, clicking 'آپلود فایل' button")
        upload_button = driver.find_element(
            By.XPATH, "//*[self::button or self::a][contains(normalize-space(.), 'آپلود فایل')]"
        )
        upload_button.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
        )
        return driver.find_element(By.XPATH, "//input[@type='file']")

    def _wait_for_new_card(
        self,
        driver: WebDriver,
        existing_names: set[str],
        file_path: Path,
        timeout: int,
    ) -> WebElement:
        end = time.monotonic() + timeout
        attempts = 0
        last_widget_text = ""
        last_dom_dump = 0.0
        upload_done_seen = False
        filename = file_path.name
        stem = file_path.stem

        while time.monotonic() < end:
            attempts += 1

            if not self._driver_alive(driver):
                raise NixfileError("جلسه مرورگر قطع شد (chromedriver).")

            with suppress(Exception):
                widget_text, percent_value = self._read_upload_widget(driver)
                if widget_text and widget_text != last_widget_text:
                    last_widget_text = widget_text
                    logger.info("[nixfile] upload widget: %s", widget_text)
                if widget_text and self._is_upload_complete(widget_text):
                    if not upload_done_seen:
                        logger.info("[nixfile] upload widget reports completion")
                    upload_done_seen = True
                    percent_value = max(percent_value, 99)
                if self._progress is not None:
                    self._progress.update(
                        state="uploading" if not upload_done_seen else "finalizing",
                        percent=percent_value,
                        info=widget_text,
                    )

            try:
                card = self._find_uploaded_card(driver, existing_names, filename, stem)
            except (InvalidSessionIdException, NoSuchWindowException) as exc:
                raise NixfileError(f"جلسه مرورگر بسته شد: {exc}") from exc
            except WebDriverException as exc:
                if self._is_fatal_webdriver_error(exc):
                    raise NixfileError(f"ارتباط با chromedriver قطع شد: {exc}") from exc
                if attempts % 10 == 1:
                    logger.warning("[nixfile] card scan recoverable error: %s", exc.__class__.__name__)
                card = None
            except Exception as exc:
                if attempts % 10 == 1:
                    logger.warning("[nixfile] card scan error: %s", exc)
                card = None

            if card is not None:
                return card

            if attempts % 5 == 1:
                logger.info(
                    "[nixfile] waiting for new card (attempt=%d, upload_done=%s, widget=%r)",
                    attempts,
                    upload_done_seen,
                    last_widget_text[:80],
                )

            now = time.monotonic()
            if now - last_dom_dump > 30:
                self._dump_debug(f"wait_card_{attempts}")
                last_dom_dump = now

            time.sleep(1.5)

        raise NixfileError(
            f"کارت فایل آپلود شده پیدا نشد (filename={filename}, last_widget={last_widget_text!r})."
        )

    @staticmethod
    def _driver_alive(driver: WebDriver) -> bool:
        try:
            _ = driver.current_url
            return True
        except (InvalidSessionIdException, NoSuchWindowException):
            return False
        except WebDriverException as exc:
            return not NixfileUploader._is_fatal_webdriver_error(exc)
        except Exception:
            return False

    @staticmethod
    def _is_fatal_webdriver_error(exc: Exception) -> bool:
        text = str(exc).lower()
        for marker in (
            "connection refused",
            "max retries exceeded",
            "invalid session",
            "no such window",
            "chrome not reachable",
            "session deleted",
            "session not created",
            "target window already closed",
        ):
            if marker in text:
                return True
        return False

    def _read_upload_widget(self, driver: WebDriver) -> tuple[str, int]:
        script = r"""
            const drawer = document.querySelector(
                'div.fixed.bottom-0.end-0, div.fixed.bottom-0'
            );
            const scope = drawer || document;
            let counter = '';
            for (const s of scope.querySelectorAll('span')) {
                const t = (s.innerText || s.textContent || '').replace(/\s+/g, ' ').trim();
                if (t.includes('فایل') && t.includes('از') && /\d/.test(t)) {
                    counter = t;
                    break;
                }
            }
            let pct = '';
            const pctEl = scope.querySelector('span.text-2xl.text-primary')
                || scope.querySelector('span.text-primary.text-2xl')
                || document.querySelector('span.text-2xl.text-primary');
            if (pctEl) {
                pct = (pctEl.innerText || pctEl.textContent || '').replace(/\s+/g, ' ').trim();
            }
            return {counter: counter, pct: pct};
        """
        try:
            result = driver.execute_script(script) or {}
        except Exception:
            return "", 0

        counter_text = (result.get("counter") or "").strip()
        percent_text = (result.get("pct") or "").strip()

        percent_value = 0
        match = re.search(r"(\d{1,3})", percent_text)
        if match:
            percent_value = max(0, min(100, int(match.group(1))))

        if not counter_text and percent_text:
            counter_text = ""

        parts = []
        if counter_text:
            parts.append(counter_text)
        if percent_text:
            parts.append(percent_text + ("%" if "%" not in percent_text else ""))
        text = " | ".join(parts)[:120]
        if not text and percent_value == 0:
            return "", 0
        return text, percent_value

    @staticmethod
    def _is_upload_complete(widget_text: str) -> bool:
        if not widget_text:
            return False
        match = re.search(r"(\d+)\s*از\s*(\d+)\s*فایل", widget_text)
        if match:
            done, total = int(match.group(1)), int(match.group(2))
            if total > 0 and done >= total:
                return True
        if re.search(r"\b100\b", widget_text):
            return True
        return False

    def _find_uploaded_card(
        self,
        driver: WebDriver,
        existing_names: set[str],
        filename: str,
        stem: str,
    ) -> WebElement | None:
        candidates = [stem, filename]
        for needle in candidates:
            if not needle:
                continue
            with suppress(Exception):
                paragraphs = driver.find_elements(
                    By.XPATH,
                    f"//p[contains(@class,'truncate') and "
                    f"normalize-space(text())={self._xpath_literal(needle)}]",
                )
                for paragraph in paragraphs:
                    card = self._climb_to_card(driver, paragraph)
                    if card is not None:
                        return card

                paragraphs = driver.find_elements(
                    By.XPATH,
                    f"//p[contains(@class,'truncate') and "
                    f"contains(normalize-space(.), {self._xpath_literal(needle)})]",
                )
                for paragraph in paragraphs:
                    card = self._climb_to_card(driver, paragraph)
                    if card is not None:
                        return card
        return None

    def _climb_to_card(self, driver: WebDriver, anchor: WebElement) -> WebElement | None:
        script = (
            "let el = arguments[0];"
            "for (let i = 0; i < 12 && el && el.parentElement; i++) {"
            "  el = el.parentElement;"
            "  if (el.querySelector && el.querySelector('button[aria-haspopup=\"menu\"]')) {"
            "    return el;"
            "  }"
            "}"
            "return null;"
        )
        with suppress(Exception):
            result = driver.execute_script(script, anchor)
            if result is not None:
                return result
        return None

    @staticmethod
    def _xpath_literal(value: str) -> str:
        if "'" not in value:
            return f"'{value}'"
        if '"' not in value:
            return f'"{value}"'
        parts = value.split("'")
        return "concat('" + "',\"'\",'".join(parts) + "')"

    def _copy_link_from_card(self, driver: WebDriver, card: WebElement) -> str:
        try:
            menu_button = card.find_element(
                By.XPATH, ".//button[@aria-haspopup='menu']"
            )
        except NoSuchElementException:
            try:
                menu_button = card.find_element(
                    By.XPATH,
                    ".//button[.//svg[contains(@class,'lucide-ellipsis-vertical') "
                    "or contains(@class,'lucide-more-vertical') "
                    "or contains(@class,'lucide-ellipsis')]]",
                )
            except NoSuchElementException:
                menu_button = card.find_element(By.XPATH, ".//button")

        self._install_clipboard_hook(driver)
        with suppress(Exception):
            driver.execute_script("window.__nixCopiedLinks = [];")

        logger.info("[nixfile] opening file menu")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", menu_button)
        try:
            menu_button.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", menu_button)

        copy_link_item = self._find_menu_item(driver, "کپی لینک", timeout=10)
        if copy_link_item is None:
            raise NixfileError("منوی فایل باز نشد یا 'کپی لینک' پیدا نشد.")

        logger.info("[nixfile] clicking 'کپی لینک' (tag=%s)", copy_link_item.tag_name)
        try:
            copy_link_item.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", copy_link_item)

        link = self._read_hooked_link(driver)
        if link:
            return link

        link = self._link_from_dom(driver)
        if link:
            logger.info("[nixfile] link read from DOM fallback")
            return link

        raise NixfileError("استخراج لینک کپی شده ناموفق بود.")

    def _find_menu_item(
        self, driver: WebDriver, label: str, timeout: float
    ) -> WebElement | None:
        deadline = time.monotonic() + timeout
        last_seen: list[str] = []
        while time.monotonic() < deadline:
            item = self._scan_menu_for(driver, label, last_seen)
            if item is not None:
                return item
            time.sleep(0.3)
        logger.warning("[nixfile] menu items seen: %s", last_seen)
        return None

    def _scan_menu_for(
        self,
        driver: WebDriver,
        label: str,
        last_seen: list[str],
    ) -> WebElement | None:
        item_selectors = [
            (By.CSS_SELECTOR, "[role='menuitem']"),
            (By.CSS_SELECTOR, "[id*='headlessui-menu-item']"),
            (By.XPATH, "//div[@role='menu']//a"),
            (By.XPATH, "//div[@role='menu']//button"),
            (By.XPATH, "//div[@role='menu']//li"),
        ]

        candidates: list[WebElement] = []
        for locator in item_selectors:
            with suppress(Exception):
                for element in driver.find_elements(*locator):
                    candidates.append(element)

        seen_local: list[str] = []
        for element in candidates:
            try:
                if not element.is_displayed():
                    continue
                text = (element.text or "").strip()
            except (StaleElementReferenceException, WebDriverException):
                continue
            if not text:
                continue
            seen_local.append(text)
            if text == label or text.split("\n", 1)[0].strip() == label:
                return element

        if seen_local:
            last_seen.clear()
            last_seen.extend(seen_local)
        return None

    def _install_clipboard_hook(self, driver: WebDriver) -> None:
        script = """
            window.__nixCopiedLinks = window.__nixCopiedLinks || [];
            if (!window.__nixClipboardHooked) {
                window.__nixClipboardHooked = true;
                try {
                    if (navigator.clipboard) {
                        const origWrite = navigator.clipboard.writeText
                            ? navigator.clipboard.writeText.bind(navigator.clipboard)
                            : null;
                        navigator.clipboard.writeText = function(text) {
                            try { window.__nixCopiedLinks.push(String(text)); } catch (e) {}
                            if (origWrite) {
                                try { return origWrite(text); } catch (e) { return Promise.resolve(); }
                            }
                            return Promise.resolve();
                        };
                    }
                } catch (e) {}
                try {
                    const origExec = document.execCommand.bind(document);
                    document.execCommand = function(cmd) {
                        if (cmd === 'copy') {
                            try {
                                const sel = window.getSelection && window.getSelection().toString();
                                if (sel) window.__nixCopiedLinks.push(String(sel));
                                const active = document.activeElement;
                                if (active && active.value) window.__nixCopiedLinks.push(String(active.value));
                            } catch (e) {}
                        }
                        return origExec.apply(document, arguments);
                    };
                } catch (e) {}
            }
        """
        with suppress(Exception):
            driver.execute_script(script)

    def _read_hooked_link(self, driver: WebDriver) -> str:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with suppress(Exception):
                items = driver.execute_script("return window.__nixCopiedLinks || [];")
                if isinstance(items, list):
                    for item in reversed(items):
                        if isinstance(item, str) and item.strip().startswith("http"):
                            logger.info("[nixfile] link captured via clipboard hook")
                            return item.strip()
            time.sleep(0.3)
        return ""

    def _link_from_dom(self, driver: WebDriver) -> str:
        candidates_xpath = (
            "//input[starts-with(@value,'http')] | "
            "//textarea[starts-with(normalize-space(text()),'http')] | "
            "//*[contains(@class,'toast') or contains(@class,'snackbar') or contains(@class,'notification')]"
            "//a[starts-with(@href,'http')]"
        )
        with suppress(Exception):
            for element in driver.find_elements(By.XPATH, candidates_xpath):
                value = (
                    element.get_attribute("value")
                    or element.get_attribute("href")
                    or element.text
                    or ""
                )
                value = value.strip()
                if value.startswith("http"):
                    return value
        return ""

    def _dump_debug(self, step: str) -> None:
        if self._driver is None:
            return
        with suppress(Exception):
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            prefix = DEBUG_DIR / f"{stamp}-{step}"
            try:
                self._driver.save_screenshot(str(prefix.with_suffix(".png")))
            except Exception as exc:
                logger.warning("[nixfile] screenshot failed: %s", exc)
            try:
                (prefix.with_suffix(".html")).write_text(self._driver.page_source, encoding="utf-8")
            except Exception as exc:
                logger.warning("[nixfile] page_source dump failed: %s", exc)
            try:
                (prefix.with_suffix(".url.txt")).write_text(
                    f"{self._driver.current_url}\n", encoding="utf-8"
                )
            except Exception:
                pass
            logger.info("[nixfile] debug artifacts saved to %s.*", prefix)

    @staticmethod
    def _format_selenium_error(exc: Exception) -> str:
        msg = getattr(exc, "msg", None) or str(exc) or exc.__class__.__name__
        msg = msg.strip()
        if not msg:
            msg = exc.__class__.__name__
        tb = traceback.extract_tb(exc.__traceback__)
        if tb:
            last = tb[-1]
            msg = f"{exc.__class__.__name__}: {msg} (at {last.filename}:{last.lineno} in {last.name})"
        return msg

    @staticmethod
    def _wait_visible(
        driver: WebDriver,
        locator: tuple[str, str],
        timeout: int = 20,
        label: str = "",
    ) -> WebElement:
        try:
            return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located(locator))
        except TimeoutException as exc:
            raise NixfileError(
                f"عنصر '{label or locator[1]}' در {timeout}s پیدا نشد."
            ) from exc
