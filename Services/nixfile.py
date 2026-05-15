import asyncio
import logging
import threading
import time
import traceback
from contextlib import suppress
from datetime import datetime
from pathlib import Path

try:
    import pyperclip  # type: ignore
    _PYPERCLIP_AVAILABLE = True
except Exception:
    pyperclip = None  # type: ignore
    _PYPERCLIP_AVAILABLE = False

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
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

    @property
    def enabled(self) -> bool:
        return bool(self._settings.nixfile_username and self._settings.nixfile_pass)

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

    def _upload_sync(
        self,
        file_path: Path,
        upload_started: threading.Event | None,
    ) -> str:
        step = "init"
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

        existing_names = self._existing_file_names(driver)
        logger.info("[nixfile] existing file count=%d", len(existing_names))

        file_input = self._find_file_input(driver)
        logger.info("[nixfile] file input found, sending path")
        if upload_started is not None:
            upload_started.set()
        file_input.send_keys(str(file_path.resolve()))

        new_card = self._wait_for_new_card(
            driver, existing_names, timeout=self._settings.nixfile_upload_timeout
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
        self, driver: WebDriver, existing_names: set[str], timeout: int
    ) -> WebElement:
        end = time.monotonic() + timeout
        last_error: Exception | None = None
        attempts = 0
        while time.monotonic() < end:
            attempts += 1
            try:
                cards = driver.find_elements(
                    By.XPATH,
                    "//*[(@data-file-name or @title) and "
                    "(.//button or .//*[contains(@class,'menu') or contains(@class,'dots')])]",
                )
                if attempts % 5 == 1:
                    logger.info("[nixfile] waiting for new card (attempt=%d, candidates=%d)", attempts, len(cards))
                for card in cards:
                    try:
                        name = (card.get_attribute("data-file-name") or card.get_attribute("title") or "").strip()
                    except StaleElementReferenceException:
                        continue
                    if name and name not in existing_names:
                        logger.info("[nixfile] new card name=%s", name)
                        return card
            except Exception as exc:
                last_error = exc
                logger.warning("[nixfile] card scan error: %s", exc)
            time.sleep(2)

        msg = "کارت فایل آپلود شده پیدا نشد."
        if last_error:
            msg += f" (last_error={last_error})"
        raise NixfileError(msg)

    def _copy_link_from_card(self, driver: WebDriver, card: WebElement) -> str:
        try:
            menu_button = card.find_element(
                By.XPATH,
                ".//button[contains(@class,'menu') or contains(@class,'dots') or "
                "contains(@aria-label,'منو') or contains(@aria-label,'گزینه')]",
            )
        except NoSuchElementException:
            menu_button = card.find_element(By.XPATH, ".//button")

        logger.info("[nixfile] opening file menu")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", menu_button)
        try:
            menu_button.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", menu_button)

        copy_link_item = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//*[self::button or self::a or self::li or self::div]"
                          "[contains(normalize-space(.), 'کپی لینک')]")
            )
        )

        logger.info("[nixfile] clicking 'کپی لینک'")
        if _PYPERCLIP_AVAILABLE:
            with suppress(Exception):
                pyperclip.copy("")  # type: ignore[union-attr]

        try:
            copy_link_item.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", copy_link_item)

        link = self._read_link_after_copy(driver, copy_link_item)
        if link:
            return link

        raise NixfileError("کپی لینک از کلیپ‌بورد ناموفق بود.")

    def _read_link_after_copy(self, driver: WebDriver, copy_item: WebElement) -> str:
        deadline = time.monotonic() + 10

        while time.monotonic() < deadline:
            if _PYPERCLIP_AVAILABLE:
                try:
                    candidate = (pyperclip.paste() or "").strip()  # type: ignore[union-attr]
                except Exception as exc:
                    logger.warning("[nixfile] pyperclip read failed: %s", exc)
                else:
                    if candidate.startswith("http"):
                        logger.info("[nixfile] link read from clipboard")
                        return candidate

            link = self._link_from_dom(driver, copy_item)
            if link:
                logger.info("[nixfile] link read from DOM")
                return link

            time.sleep(0.4)

        return ""

    def _link_from_dom(self, driver: WebDriver, copy_item: WebElement) -> str:
        with suppress(Exception):
            href = copy_item.get_attribute("data-link") or copy_item.get_attribute("data-href") or copy_item.get_attribute("href")
            if href and href.startswith("http"):
                return href.strip()

        candidates_xpath = (
            "//input[starts-with(@value,'http')] | "
            "//*[contains(@class,'toast') or contains(@class,'snackbar') or contains(@class,'notification')]"
            "//a[starts-with(@href,'http')]"
        )
        with suppress(Exception):
            for element in driver.find_elements(By.XPATH, candidates_xpath):
                value = element.get_attribute("value") or element.get_attribute("href") or element.text
                if value and value.strip().startswith("http"):
                    return value.strip()

        with suppress(Exception):
            result = driver.execute_script(
                "if (navigator.clipboard && navigator.clipboard.readText) {"
                "  return navigator.clipboard.readText().catch(() => null);"
                "} else { return null; }"
            )
            if isinstance(result, str) and result.startswith("http"):
                return result.strip()

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
