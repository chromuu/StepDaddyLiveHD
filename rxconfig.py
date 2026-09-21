import reflex as rx
import os


proxy_content = os.environ.get("PROXY_CONTENT", "TRUE").upper() == "TRUE"
socks5 = os.environ.get("SOCKS5", "")
backend_port = os.environ.get("BACKEND_PORT", "8004")
# curl_cffi browser fingerprint used for upstream requests. Newer Chrome
# profiles (chrome146+) are currently blocked by the embed host's WAF.
impersonate = os.environ.get("IMPERSONATE", "chrome136")

print(f"PROXY_CONTENT: {proxy_content}\nSOCKS5: {socks5}\nIMPERSONATE: {impersonate}")

config = rx.Config(
    app_name="StepDaddyLiveHD",
    proxy_content=proxy_content,
    backend_host="::",
    backend_port=int(backend_port),
    telemetry_enabled=False,
    socks5=socks5,
    impersonate=impersonate,
    show_built_with_reflex=False,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ],
)
