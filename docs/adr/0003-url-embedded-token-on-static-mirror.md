# 0003-url-embedded-token-on-static-mirror.md

# URL-embedded token on the static mirror

The static mirror authenticates via a secret token in the URL path prefix,
not headers or Cloudflare Access. Web chats' fetch tools fetch URLs but
don't send custom headers, and Access's OTP flow requires a browser they
don't have. The token is revocable by rotating and redeploying.