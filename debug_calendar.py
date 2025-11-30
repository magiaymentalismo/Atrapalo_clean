#!/usr/bin/env python3
from playwright.sync_api import sync_playwright

url = "https://feverup.com/m/290561"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    
    # Wait for calendar container
    page.wait_for_selector('app-booking-calendar', timeout=20000)
    page.wait_for_timeout(5000)
    
    # Scroll to calendar
    page.evaluate('document.querySelector("app-booking-calendar").scrollIntoView()')
    page.wait_for_timeout(2000)
    
    # Take screenshot
    page.screenshot(path="fever_calendar_debug.png")
    
    # Try to find days
    days = page.query_selector_all('.ngb-dp-day')
    print(f"Found {len(days)} total calendar days")
    
    available = page.query_selector_all('.ngb-dp-day[aria-disabled="false"]')
    print(f"Found {len(available)} available days")
    
    if available:
        for day in available[:5]:
            label = day.get_attribute('aria-label')
            print(f"  - {label}")
    
    input("Press Enter to close...")
    browser.close()
