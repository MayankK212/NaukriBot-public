from playwright.sync_api import sync_playwright

def setup_session():
    with sync_playwright() as p:
        # executable_path mein apna path daal (slash ko double kar dena)
        brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
        
        browser = p.chromium.launch(
            executable_path=brave_path,
            headless=False
        )
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://www.naukri.com/nlogin/login")

        print("--- PAUSED ---")
        print("Login karo aur phir wapas yahan aake Enter dabao.")
        
        page.pause()

        cookies = context.cookies()
        import json
        with open("cookies.json", "w") as f:
            json.dump(cookies, f)
        
        print("Cookies saved!")
        browser.close()

if __name__ == "__main__":
    setup_session()