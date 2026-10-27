// Applied before the first paint (a classic script in <head>), so the page never flashes the other theme.
try {
  const t = localStorage.getItem("inklight-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (_) { /* storage blocked: follow the system */ }
