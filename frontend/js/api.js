// Thin wrapper around the backend REST API.

async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data && Array.isArray(data.detail)) {
      msg = data.detail.map(d => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    } else if (data && data.detail) {
      msg = String(data.detail);
    }
    throw new Error(msg);
  }
  return data;
}

export const api = {
  pallet: () => request("GET", "/api/pallet"),
  layout: params => request("POST", "/api/layout", params),
  getConfig: () => request("GET", "/api/config"),
  saveRobot: settings => request("PUT", "/api/config/robot", settings),
  saveJob: params => request("PUT", "/api/config/job", params),
  testConnection: () => request("POST", "/api/test-connection"),
  generate: (params, filename) => request("POST", "/api/generate", { params, filename }),
};

export function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function renderLog(ul, steps) {
  ul.innerHTML = "";
  for (const s of steps) {
    const li = document.createElement("li");
    li.className = s.ok ? "ok" : "fail";
    li.textContent = s.name;
    if (s.message) {
      const m = document.createElement("span");
      m.className = "msg";
      m.textContent = s.message;
      li.appendChild(m);
    }
    ul.appendChild(li);
  }
}
