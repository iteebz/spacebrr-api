---
description: Need to see UI, verify rendering, click things
---

# Visual Feedback

See and interact with what renders.

## Quick Screenshot (preferred)

```bash
pnpm screenshot "/(tabs)" /tmp/screen.png
```

Then read `/tmp/screen.png`.

Args: `[path] [output] [wait_ms]`

Examples:
```bash
pnpm screenshot "/(tabs)/channels" /tmp/channels.png
pnpm screenshot "/(tabs)/spawns" /tmp/spawns.png 3000
```

## Raw Playwright

```bash
npx playwright screenshot --viewport-size=390,844 http://localhost:8081 /tmp/screen.png
```

## Interact

```bash
# Click by text
npx playwright click "text=Spawns" --url http://localhost:8081

# Click by selector
npx playwright click "button.submit" --url http://localhost:8081

# Fill input
npx playwright fill "input[placeholder='Search']" "query" --url http://localhost:8081
```

## Complex Navigation

For multi-step flows, write a throwaway script:

```javascript
// /tmp/nav.js
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto('http://localhost:8081');
  await page.click('text=Spawns');
  await page.waitForTimeout(500);
  await page.screenshot({ path: '/tmp/screen.png' });
  await browser.close();
})();
```

```bash
node /tmp/nav.js
```

## Loop

1. Screenshot
2. Read image
3. Click/fill as needed
4. Screenshot again
5. Repeat
