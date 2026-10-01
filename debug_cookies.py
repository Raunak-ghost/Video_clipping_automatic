"""Debug: verify cookies.txt actually represents a logged-in YouTube session."""
import http.cookiejar
import urllib.request

cj = http.cookiejar.MozillaCookieJar("cookies.txt")
cj.load(ignore_discard=True, ignore_expires=True)

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")]

req = opener.open("https://www.youtube.com/", timeout=30)
html = req.read().decode("utf-8", "replace")

print("status:", req.status)
print("cookies sent:", len(list(cj)))
# Logged-in pages contain these markers
print("has avatar/account marker:", '"isSignedIn":true' in html or "ytcfg.data_.LOGGED_IN = true" in html or "LOGGED_IN\":true" in html)
print("has 'Sign in' button:", ">Sign in<" in html or '"SIGN_IN"' in html)
# Check for bot interstitial
print("bot interstitial:", "confirm you're not a bot" in html.lower() or "not a bot" in html.lower())
