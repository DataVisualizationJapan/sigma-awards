/* DVJ analytics specification 1.0.0. Configuration lives in analytics.json. */
(() => {
  "use strict";
  if (window.dvjAnalytics) return;
  const node = document.getElementById("dvj-analytics-config");
  let config;
  try { config = JSON.parse(node?.textContent || "null"); } catch { return; }
  if (!config?.enabled || !/^G-[A-Z0-9]+$/.test(config.measurement_id || "") ||
      location.protocol !== "https:" || !config.production_hosts?.includes(location.hostname)) return;

  // Only campaign parameters survive. Search/filter values and fragments never enter our payloads.
  function cleanUrl(value) {
    try {
      const url = new URL(value, location.href);
      if (!/^https?:$/.test(url.protocol)) return "";
      url.username = ""; url.password = ""; url.hash = "";
      for (const key of [...url.searchParams.keys()]) {
        if (!/^(utm_source|utm_medium|utm_campaign|utm_id|utm_content|utm_term)$/.test(key)) url.searchParams.delete(key);
      }
      return url.href;
    } catch { return ""; }
  }
  window.dataLayer = window.dataLayer || [];
  function tag() { window.dataLayer.push(arguments); }
  window.gtag = tag;
  let currentLocation = cleanUrl(location.href);
  let currentPath = new URL(currentLocation).pathname;
  let currentTitle = document.title;
  tag("js", new Date());
  tag("set", {site_id: config.site_id, analytics_spec_version: "1.0.0"});
  tag("config", config.measurement_id, {
    send_page_view: true,
    cookie_domain: "auto",
    page_location: currentLocation,
    page_referrer: cleanUrl(document.referrer),
    page_title: currentTitle,
  });

  const events = new Set(["filter_apply", "pagination_change", "language_change", "community_click", "registration_click", "video_load"]);
  function event(name, params = {}) {
    if (!events.has(name)) return;
    const safe = {};
    for (const key of ["result_count", "page"]) {
      if (Number.isInteger(params[key]) && params[key] >= 0) safe[key] = params[key];
    }
    if (typeof params.has_search === "boolean") safe.has_search = params.has_search;
    if (["sigma", "dja"].includes(params.catalog)) safe.catalog = params.catalog;
    if (["ja", "src"].includes(params.language)) safe.language = params.language;
    if (["connpass", "facebook", "youtube", "peatix", "google_forms"].includes(params.destination)) safe.destination = params.destination;
    if (/^\d{1,20}$/.test(params.video_id || "")) safe.video_id = params.video_id;
    tag("event", name, safe);
  }

  function pageView(value = location.href, title = document.title) {
    const next = cleanUrl(value);
    if (!next || new URL(next).origin !== location.origin) return;
    const path = new URL(next).pathname;
    if (path === currentPath) return; // Query/filter changes are interactions, not new content.
    const previous = currentLocation;
    currentLocation = next; currentPath = path; currentTitle = title;
    tag("config", config.measurement_id, {
      send_page_view: false, page_location: next, page_referrer: previous, page_title: title,
    });
    tag("event", "page_view", {page_location: next, page_referrer: previous, page_title: title});
  }
  window.dvjAnalytics = Object.freeze({event, pageView});

  document.addEventListener("click", e => {
    const link = e.target.closest?.("a[href]");
    if (!link) return;
    let url;
    try { url = new URL(link.href, location.href); } catch { return; }
    const host = url.hostname;
    if (host === "data-visualization-japan.connpass.com") {
      event(/\/event\/\d+/.test(url.pathname) ? "registration_click" : "community_click", {destination: "connpass"});
    } else if (host === "peatix.com" || host.endsWith(".peatix.com")) {
      event("registration_click", {destination: "peatix"});
    } else if (host === "docs.google.com" && url.pathname.startsWith("/forms/")) {
      event("registration_click", {destination: "google_forms"});
    } else if (host === "www.facebook.com" && url.pathname.startsWith("/groups/datavizjapan")) {
      event("community_click", {destination: "facebook"});
    } else if (["www.youtube.com", "youtube.com"].includes(host) && url.pathname.startsWith("/@datavisualizationjapan")) {
      event("community_click", {destination: "youtube"});
    }
  });
  const script = document.createElement("script");
  script.async = true;
  script.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(config.measurement_id);
  document.head.appendChild(script);
})();
