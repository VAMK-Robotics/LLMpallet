// Robot settings page: every change is saved automatically to config/config.json by the backend.
import { api, debounce, renderLog } from "./api.js";

const form = () => document.getElementById("settings-form");
const status = () => document.getElementById("settings-status");

function fill(robot) {
  for (const el of form().elements) {
    if (!el.name || !(el.name in robot) || el.name === "password") continue;
    if (el.type === "checkbox") el.checked = robot[el.name];
    else el.value = robot[el.name];
  }
  form().elements.password.placeholder = robot.password_set ? "(saved – type to change)" : "(not set)";
}

function collect() {
  const data = {};
  for (const el of form().elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") data[el.name] = el.checked;
    else if (el.type === "number") data[el.name] = Number(el.value);
    else data[el.name] = el.value;
  }
  data.password = data.password === "" ? null : data.password;
  return data;
}

async function save() {
  const st = status();
  try {
    const res = await api.saveRobot(collect());
    const pw = form().elements.password;
    if (pw.value !== "" && document.activeElement !== pw) pw.value = "";
    form().elements.password.placeholder = res.robot.password_set ? "(saved – type to change)" : "(not set)";
    st.className = "status";
    st.textContent = `Saved to config file ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    st.className = "status error";
    st.textContent = `Not saved: ${e.message}`;
  }
}

export function initSettings(robot) {
  fill(robot);
  const saveSoon = debounce(save, 500);
  form().addEventListener("input", e => { if (e.target.name !== "password") saveSoon(); });
  form().addEventListener("change", () => saveSoon());
  document.getElementById("test-connection").addEventListener("click", async () => {
    const log = document.getElementById("test-log");
    log.innerHTML = "<li>Connecting…</li>";
    await save();
    try {
      const res = await api.testConnection();
      renderLog(log, res.steps);
    } catch (e) {
      renderLog(log, [{ name: "Test connection", ok: false, message: e.message }]);
    }
  });
}
