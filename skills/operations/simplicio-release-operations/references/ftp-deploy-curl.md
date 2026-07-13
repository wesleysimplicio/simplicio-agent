# FTP Deploy via curl

Quickest way to update individual files on simpleti.com.br without the full 
lftp mirror.

## Credentials

From `deploy/.ftp-credentials` (gitignored):
- Host: `ftp.simpleti.com.br`
- User: `wesley@simpleti.com.br`  
- Pass: stored in `.ftp-credentials`
- Remote path: `/public_html` (NOT `/public`)
- Mode: FTP (not SFTP)

## Binary deploy

```bash
curl -sS --ftp-create-dirs -T <local-binary> \
  -u "wesley@simpleti.com.br:PASS" \
  ftp://ftp.simpleti.com.br/public_html/simplicio/dist/simplicio-darwin-arm64
```

## Version.txt deploy

```bash
echo "0.9.5" > /tmp/version.txt
curl -sS --ftp-create-dirs -T /tmp/version.txt \
  -u "wesley@simpleti.com.br:PASS" \
  ftp://ftp.simpleti.com.br/public_html/simplicio/dist/version.txt
```

## Verification

```bash
curl -sS https://simpleti.com.br/simplicio/dist/version.txt
# → 0.9.5 (matches Cargo.toml)

curl -sI https://simpleti.com.br/simplicio/dist/simplicio-darwin-arm64
# → HTTP/1.1 200 OK
```

## dist/ directory structure

```
simplicio/
  dist/
    simplicio-darwin-arm64       # macOS binary (13MB)
    simplicio-windows-x64.exe    # Windows binary (14MB)
    simplicio-badge.vsix         # VS Code extension
    version.txt                  # plain-text version
  index.html                     # landing page
  install.sh                     # macOS/Linux installer
  install.ps1                    # Windows installer
  uninstall.sh / .ps1            # Uninstallers
```
