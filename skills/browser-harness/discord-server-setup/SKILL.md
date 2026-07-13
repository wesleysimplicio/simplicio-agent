---
name: discord-server-setup
description: Create and configure Discord servers, categories, channels, and messages via Playwright browser automation. Covers login flow, DOM interaction patterns specific to Discord's React UI, and known pitfalls.
version: 1.0.0
author: Hermes Agent
tags: [discord, playwright, browser-automation, server-setup]
---

# Discord Server Setup via Playwright

Use this skill when automating Discord server creation and channel management via the web UI (Playwright browser), as the Discord API may return 401 for user tokens.

## Architecture

Two approaches for Discord automation:

| Approach | When to use | Reliability |
|---|---|---|
| **Playwright UI clicks** | Discord API token unavailable (401) | Medium — Discord's React UI is resistant to automation |
| **Discord API (fetch)** | Token available (from webpack or cookies) | High — direct REST calls |

## Login Flow

Discord usually requires QR code scanning — the user must scan on their phone.

```typescript
await page.goto('https://discord.com/login');
// Wait for QR code or email/password form
// If using email/password, fill and submit
// If QR, tell user to scan
```

After login, navigate directly:
```typescript
await page.goto(`https://discord.com/channels/@me`);
```

## Server Creation

```typescript
// Click the "+" (Add a Server) button in the server sidebar
await page.getByLabel('Adicionar um servidor').click();
// Or find by text
await page.getByText('Adicionar um servidor').click();

// In the modal, click "Criar Meu Próprio" / "Create My Own"
// Fill server name → click "Criar" / "Create"
```

Server ID is visible in the URL after creation: `https://discord.com/channels/<guild_id>/<channel_id>`

## Category Creation

Click the server name dropdown → "Create Category" / "Criar Categoria":

```typescript
// Click server name to open dropdown
await page.locator('[class*="nameTag"]').first().click();
// Find and click "Create Category"
await page.getByText(/criar categoria|create category/i).click();
// Fill name in the dialog input
await page.locator('input[class*="inputDefault"]').fill('📋 Welcome');
// Click Create button
await page.getByRole('button', { name: /criar|create/i }).last().click();
```

## Channel Creation (Hover-Revealed Buttons)

Discord's "+" (add channel) buttons are only visible on **hover**. This is the #1 pitfall.

```typescript
// Hover over the category to reveal its "+" button
await page.evaluate(() => {
  const containers = document.querySelectorAll('[class*="containerDefault"]');
  for (const c of containers) {
    if (c.textContent.includes('Welcome')) {
      c.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      break;
    }
  }
});
await page.waitForTimeout(300);

// Now click the revealed "+" button
await page.evaluate(() => {
  const btns = document.querySelectorAll('[class*="addButton"]');
  for (const btn of btns) {
    if (btn.offsetParent !== null) { btn.click(); return; }
  }
});
await page.waitForTimeout(600);
```

### Filling the Channel Name

Discord's React doesn't respond to standard `input.value = ...` + `dispatchEvent`. Use `execCommand('insertText')` instead:

```typescript
await page.evaluate((name) => {
  const editor = document.activeElement;
  if (editor && editor.tagName === 'INPUT') {
    editor.value = '';
    editor.focus();
    document.execCommand('insertText', false, name);
  }
}, name);
```

### Submitting (Create Button)

Find the modal footer button:
```typescript
await page.evaluate(() => {
  const btns = document.querySelectorAll('button');
  for (const btn of btns) {
    if (btn.disabled) continue;
    const txt = btn.textContent.trim().toLowerCase();
    if (txt === 'criar canal' || txt === 'create channel' || txt === 'criar') {
      btn.click(); return;
    }
  }
});
await page.waitForTimeout(800);
```

### Important: One Channel Per Modal Invocation
- After clicking "Create", wait for the modal to close before creating the next channel
- Each channel requires: hover → click "+" → fill name → click Create → wait for close
- Do NOT try to batch multiple fills in one modal

## Sending Messages

Discord uses a custom Slate contenteditable editor. Standard `type()` or `fill()` doesn't work reliably.

```typescript
// Approach 1: execCommand (most reliable)
await page.evaluate(() => {
  const editor = document.querySelector('[role="textbox"][contenteditable="true"]');
  if (editor) {
    editor.focus();
    document.execCommand('insertText', false, '**Welcome message**\n\nHello!');
  }
});

// Approach 2: ClipboardEvent paste
await page.evaluate((text) => {
  const editor = document.querySelector('[role="textbox"][contenteditable="true"]');
  if (editor) {
    editor.focus();
    const clipboardData = new DataTransfer();
    clipboardData.setData('text/plain', text);
    editor.dispatchEvent(new ClipboardEvent('paste', {
      clipboardData, bubbles: true, cancelable: true
    }));
  }
}, messageText);

// Send: Ctrl+Enter or Enter (depending on Discord settings)
await page.keyboard.press('Enter');
```

**Known issue:** `execCommand('insertText')` inserts the text into the editor but `keyboard.press('Enter')` sometimes doesn't send the message. Discord's keyboard handler may not fire reliably via Playwright. In that case, the message stays in the input box — the user can press Enter themselves, or use `Ctrl+Enter`.

## Getting the Auth Token (for API calls)

If you need the auth token for direct API calls:

```typescript
// Method 1: From webpack module (most reliable)
await page.evaluate(() => {
  const wc = window.webpackChunkdiscord_app;
  const req = wc.push([[Symbol()], {}, (e) => e]);
  wc.pop();
  for (const key in req.c) {
    const m = req.c[key].exports;
    if (m && m.default && m.default.getToken) {
      return m.default.getToken();
    }
  }
});

// Method 2: From localStorage
await page.evaluate(() => localStorage.getItem('token'));

// Method 3: Inspect network requests
// After page load, find a /api/v9/ request and extract the Authorization header
```

## Modal Stacking

When automation fails mid-flow, Discord can accumulate stacked modals. Each failed attempt adds another "Criar Canal" dialog on top. Close them all:

```typescript
for (let i = 0; i < 35; i++) {
  const closed = await page.evaluate(() => {
    const closeBtn = document.querySelector('[aria-label="Close"]');
    if (closeBtn) { closeBtn.click(); return true; }
    return false;
  });
  if (!closed) break;
  await page.waitForTimeout(150);
}
```

## Known Pitfalls

- **Hover-revealed buttons**: The "+" (add channel) buttons are invisible until mouse hover. `click()` on invisible elements fails silently. Always trigger `mouseenter` first.
- **React synthetic events**: Discord uses React's synthetic event system. Native DOM `dispatchEvent(new Event('input'))` may not trigger React's change detection. Use `execCommand('insertText')` or `nativeSetter`.
- **Multiple invocations of same modal**: Opening "Create Channel" while one is already open creates stacked modals. Track open state explicitly.
- **Page navigation on channel creation**: Creating a channel navigates to it. The sidebar DOM re-renders. `ref=` selectors from prior snapshots become stale.
- **Connection drops**: Playwright can time out if Discord WebSocket is slow. Use `page.waitForTimeout(2000)` generously between steps.
- **User-must-scan-QR**: Discord's login often requires QR code from phone. The agent can't bypass this. Always plan for user interaction at login.
- **Rate limiting**: Fast API calls get 429 responses. Add delays between channel creations.
- **Language**: Discord's UI language depends on the user's locale setting. The "Criar canal" / "Create Channel" button text varies. Match both.
