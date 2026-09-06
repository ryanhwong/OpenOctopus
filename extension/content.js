(() => {
  const API = "http://127.0.0.1:8765/products/import-json";

  const normImg = (u) => {
    u = (u || "").trim();
    if (u.startsWith("//")) u = "https:" + u;
    if (u.endsWith("_.webp") && /[.](jpg|jpeg|png)$/i.test(u.slice(0, -7))) {
      u = u.slice(0, -7);
    }
    return u;
  };

  const collectImgs = (selectors) => {
    const out = [];
    document.querySelectorAll(selectors.join(",")).forEach((img) => {
      const u = normImg(img.getAttribute("data-src") || img.getAttribute("src"));
      if (!u.startsWith("http") || u.toLowerCase().endsWith(".svg")) return;
      if (!out.includes(u)) out.push(u);
    });
    return out;
  };

  const extractTitle = () => {
    const og = document.querySelector('meta[property="og:title"]');
    if (og && og.content.trim()) return og.content.trim();
    const n = document.querySelector(".module-od-title .title-content") ||
              document.querySelector(".module-od-title");
    if (n && n.innerText.trim()) return n.innerText.trim();
    return document.title.replace(/\s*[-–|]\s*阿里巴巴\s*$/, "").trim();
  };

  const extractPrice = () => {
    for (const sel of ['[class*="od-price"]', ".od-price", ".price"]) {
      const n = document.querySelector(sel);
      if (!n) continue;
      const m = n.innerText.match(/\d+(?:\.\d+)?/);
      if (m) return parseFloat(m[0]);
    }
    return 0;
  };

  const extract = () => ({
    source_url: location.href.split("?")[0],
    platform: "1688",
    title_zh: extractTitle(),
    bullets_zh: [],
    description_zh: "",
    price_cny: extractPrice(),
    skus: [],
    main_images: collectImgs([".od-gallery-preview img", ".od-gallery-list img"]).slice(0, 15),
    detail_images: collectImgs([".content-detail img"]),
  });

  const toast = (msg, ok) => {
    const el = document.createElement("div");
    el.textContent = msg;
    el.style.cssText = `position:fixed;bottom:90px;right:24px;z-index:999999;padding:12px 18px;` +
      `border-radius:8px;font-size:14px;color:#fff;background:${ok ? "#16a34a" : "#dc2626"};` +
      `box-shadow:0 4px 12px rgba(0,0,0,.2);`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  };

  const btn = document.createElement("button");
  btn.textContent = "采到 OpenOctopus";
  btn.style.cssText = "position:fixed;bottom:24px;right:24px;z-index:999999;padding:12px 22px;" +
    "border:none;border-radius:8px;font-size:15px;font-weight:700;color:#fff;background:#7c3aed;" +
    "cursor:pointer;box-shadow:0 4px 12px rgba(124,58,237,.4);";
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = "采集中…";
    try {
      const r = await fetch(API, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(extract()),
      });
      const data = await r.json();
      if (data.ok) toast(`已采集 #${data.product_id}，去工作台查看`, true);
      else toast(`失败：${data.error || r.status}`, false);
    } catch (e) {
      toast("连不上本地服务：先启动 OpenOctopus", false);
    }
    btn.disabled = false;
    btn.textContent = "采到 OpenOctopus";
  };
  document.body.appendChild(btn);
})();
