import asyncio
import logging
import time
from pathlib import Path

import pyperclip
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from App.config import Settings

logger = logging.getLogger(__name__)


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

    async def upload(self, file_path: Path) -> str:
        if not self.enabled:
            raise NixfileError("NIXFILE_USERNAME/NIXFILE_PASS تنظیم نشده است.")
        if not file_path.exists():
            raise NixfileError(f"فایل آپلود پیدا نشد: {file_path}")

        async with self._lock:
            return await asyncio.to_thread(self._upload_sync, file_path)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._shutdown_sync)

    def _upload_sync(self, file_path: Path) -> str:
        try:
            self._ensure_login()
            return self._do_upload(file_path)
        except NixfileError:
            raise
        except Exception as exc:
            logger.exception("Nixfile upload failed")
            self._shutdown_sync()
            raise NixfileError(f"آپلود به نیکس‌فایل ناموفق بود: {exc}") from exc

    def _ensure_driver(self) -> WebDriver:
        if self._driver is not None:
            return self._driver

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
            try:
                self._driver.quit()
            except Exception:
                logger.debug("Failed to quit driver cleanly", exc_info=True)
        self._driver = None
        self._logged_in = False

    def _ensure_login(self) -> None:
        driver = self._ensure_driver()
        if self._logged_in and self._on_panel(driver):
            return

        username = self._settings.nixfile_username or ""
        password = self._settings.nixfile_pass or ""

        driver.get(self._settings.nixfile_login_url)

        username_input = self._wait_visible(
            driver,
            (
                By.XPATH,
                "//input[@type='text' or @type='email' or @type='tel' or "
                "contains(@placeholder,'موبایل') or contains(@placeholder,'ایمیل')]",
            ),
            timeout=30,
        )
        username_input.clear()
        username_input.send_keys(username)

        self._click_login_button(driver)

        password_input = self._wait_visible(
            driver, (By.XPATH, "//input[@type='password']"), timeout=30
        )
        password_input.clear()
        password_input.send_keys(password)

        self._click_login_button(driver)

        WebDriverWait(driver, 45).until(lambda d: self._on_panel(d))
        self._logged_in = True
        logger.info("Logged in to nixfile.com")

    def _on_panel(self, driver: WebDriver) -> bool:
        try:
            url = driver.current_url
        except Exception:
            return False
        if "/auth/" in url:
            return False
        if self._settings.nixfile_panel_url not in url:
            return False
        try:
            driver.find_element(
                By.XPATH, "//*[contains(normalize-space(.), 'آپلود فایل')]"
            )
            return True
        except NoSuchElementException:
            return False

    def _click_login_button(self, driver: WebDriver) -> None:
        candidates = [
            (By.XPATH, "//button[contains(normalize-space(.), 'ورود به نیکس')]"),
            (By.XPATH, "//button[contains(normalize-space(.), 'ادامه')]"),
            (By.XPATH, "//button[@type='submit']"),
        ]
        for locator in candidates:
            try:
                element = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(locator))
                element.click()
                return
            except TimeoutException:
                continue
        raise NixfileError("دکمه ورود نیکس‌فایل پیدا نشد.")

    def _do_upload(self, file_path: Path) -> str:
        driver = self._ensure_driver()

        if "/files" not in driver.current_url and "files" not in driver.current_url.lower():
            self._navigate_to_files(driver)

        existing_names = self._existing_file_names(driver)

        file_input = self._find_file_input(driver)
        file_input.send_keys(str(file_path.resolve()))

        new_card = self._wait_for_new_card(
            driver, existing_names, timeout=self._settings.nixfile_upload_timeout
        )

        return self._copy_link_from_card(driver, new_card)

    def _navigate_to_files(self, driver: WebDriver) -> None:
        try:
            link = driver.find_element(
                By.XPATH, "//*[contains(normalize-space(.), 'فایل های من')]"
            )
            link.click()
        except NoSuchElementException:
            driver.get(self._settings.nixfile_panel_url.rstrip("/") + "/files")

        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(normalize-space(.), 'آپلود فایل')]")
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
                return elements[0]

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
        while time.monotonic() < end:
            try:
                cards = driver.find_elements(
                    By.XPATH,
                    "//*[(@data-file-name or @title) and "
                    "(.//button or .//*[contains(@class,'menu') or contains(@class,'dots')])]",
                )
                for card in cards:
                    try:
                        name = (card.get_attribute("data-file-name") or card.get_attribute("title") or "").strip()
                    except StaleElementReferenceException:
                        continue
                    if name and name not in existing_names:
                        return card
            except Exception as exc:
                last_error = exc
            time.sleep(2)

        if last_error:
            raise NixfileError(f"کارت فایل آپلود شده پیدا نشد: {last_error}")
        raise NixfileError("کارت فایل آپلود شده پیدا نشد.")

    def _copy_link_from_card(self, driver: WebDriver, card: WebElement) -> str:
        try:
            menu_button = card.find_element(
                By.XPATH,
                ".//button[contains(@class,'menu') or contains(@class,'dots') or "
                "contains(@aria-label,'منو') or contains(@aria-label,'گزینه')]",
            )
        except NoSuchElementException:
            menu_button = card.find_element(By.XPATH, ".//button")

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", menu_button)
        menu_button.click()

        copy_link_item = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//*[self::button or self::a or self::li or self::div]"
                          "[contains(normalize-space(.), 'کپی لینک')]")
            )
        )

        pyperclip.copy("")
        copy_link_item.click()

        deadline = time.monotonic() + 10
        link = ""
        while time.monotonic() < deadline:
            link = (pyperclip.paste() or "").strip()
            if link.startswith("http"):
                return link
            time.sleep(0.3)

        raise NixfileError("کپی لینک از کلیپ‌بورد ناموفق بود.")

    @staticmethod
    def _wait_visible(driver: WebDriver, locator: tuple[str, str], timeout: int = 20) -> WebElement:
        return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located(locator))
