const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 2600, height: 1815 }, deviceScaleFactor: 2 });
  await p.goto('file://' + process.argv[2]); await p.screenshot({ path: process.argv[3] }); await b.close();
})();
