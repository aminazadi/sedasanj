/** Execute trusted script descriptors without eval or inline-CSP exemptions. */
export async function appendSiteScripts(manifest, scope, { document, isActive, reportFailure, timeout = 10000 }) {
  for (const placement of ["head", "body"]) {
    for (const attributes of manifest[placement]) {
      if (!isActive()) return;
      const script = document.createElement("script");
      script.async = false;
      for (const [key, value] of Object.entries(attributes)) script.setAttribute(key, value);
      script.dataset.siteScriptScope = scope;
      let finish;
      const loaded = new Promise(resolve => { finish = resolve; });
      const timer = setTimeout(() => { reportFailure(); finish(); }, timeout);
      script.onload = () => { clearTimeout(timer); finish(); };
      script.onerror = () => { clearTimeout(timer); reportFailure(); finish(); };
      document[placement].appendChild(script);
      if (!script.async) await loaded;
    }
  }
}
