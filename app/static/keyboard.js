// On-screen keyboard so the device works by touch alone (no physical keyboard).
// - Every text <input> opens it when tapped.
// - askText(title, value) replaces window.prompt() and resolves to the text or null.
// - askConfirm(text) replaces window.confirm() with big touch-friendly buttons.
"use strict";

const OSK = (() => {
  const row = (str) => [...str];
  const LAYOUTS = {
    abc: [row("qwertyuiop"), row("asdfghjkl"), ["⇧", ...row("zxcvbnm"), "⌫"], ["123", ",", "space", ".", "↵"]],
    ABC: [row("QWERTYUIOP"), row("ASDFGHJKL"), ["⇧", ...row("ZXCVBNM"), "⌫"], ["123", ",", "space", ".", "↵"]],
    sym: [row("1234567890"), row("-/:;()€&@'"), ["+", "=", "°", "?", "!", "%", "*", "#", "⌫"], ["abc", ",", "space", ".", "↵"]],
  };
  const FN = ["⇧", "⌫", "↵", "123", "abc"];
  let layout = "abc", target = null, resolver = null, shiftOnce = false;

  const el = document.createElement("div");
  el.id = "osk";
  el.className = "hidden";
  el.innerHTML = `<div id="osk-top"><span id="osk-title"></span><input id="osk-field" inputmode="none" autocomplete="off">
    <button data-k="cancel" class="osk-x">✕</button></div><div id="osk-keys"></div>`;
  document.body.appendChild(el);
  const field = el.querySelector("#osk-field");
  const title = el.querySelector("#osk-title");

  function render() {
    el.querySelector("#osk-keys").innerHTML = LAYOUTS[layout].map(keys => '<div class="osk-row">' + keys.map(k => {
      const cls = k === "space" ? "space" : FN.includes(k) ? "fn" : "";
      const val = k === "space" ? " " : k;
      return `<button data-k="${val.replace(/"/g, "&quot;")}" class="${cls}">${k}</button>`;
    }).join("") + "</div>").join("");
  }

  function open(opts) {
    target = opts.target || null;
    resolver = opts.resolve || null;
    title.textContent = opts.title || "";
    field.value = opts.value || "";
    layout = "abc"; shiftOnce = !field.value;
    if (shiftOnce) layout = "ABC";
    render();
    el.classList.remove("hidden");
    document.body.classList.add("osk-open");
  }
  function close(ok) {
    el.classList.add("hidden");
    document.body.classList.remove("osk-open");
    const val = field.value;
    if (target) {
      if (ok) {
        target.value = val;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        target.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      }
      target.blur();
    }
    if (resolver) resolver(ok ? val : null);
    target = resolver = null;
  }

  // Press highlights the key, release types it. A resistive screen's first reading of a touch is
  // the least accurate one, so typing on release (where the finger settled) hits the right key
  // more often; sliding off a key before lifting cancels it.
  let pressed = null;
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();  // keep focus, no ghost clicks
    const b = e.target.closest("button");
    if (pressed) pressed.classList.remove("down");
    pressed = b; if (b) b.classList.add("down");
  });
  el.addEventListener("pointermove", (e) => {
    if (!pressed) return;
    const b = document.elementFromPoint(e.clientX, e.clientY);
    const k = b && b.closest && b.closest("#osk button");
    if (k !== pressed) { pressed.classList.remove("down"); pressed = k || null; if (k) k.classList.add("down"); }
  });
  el.addEventListener("pointercancel", () => { if (pressed) pressed.classList.remove("down"); pressed = null; });
  el.addEventListener("pointerup", (e) => {
    const b = pressed; pressed = null;
    if (!b) return;
    b.classList.remove("down");
    e.preventDefault();
    const k = b.dataset.k;
    if (k === "cancel") return close(false);
    if (k === "↵") return close(true);
    if (k === "⌫") field.value = field.value.slice(0, -1);
    else if (k === "⇧") { layout = layout === "ABC" ? "abc" : "ABC"; shiftOnce = layout === "ABC"; render(); return; }
    else if (k === "123") { layout = "sym"; render(); return; }
    else if (k === "abc") { layout = "abc"; render(); return; }
    else {
      field.value += k;
      if (layout === "ABC" && shiftOnce) { layout = "abc"; shiftOnce = false; render(); }
    }
  });
  // a physical keyboard still works if one is plugged in
  field.addEventListener("keydown", (e) => { if (e.key === "Enter") close(true); if (e.key === "Escape") close(false); });

  // attach to every text input on the page
  document.addEventListener("focusin", (e) => {
    const t = e.target;
    if (t === field || t.tagName !== "INPUT" || (t.type && t.type !== "text" && t.type !== "search")) return;
    t.setAttribute("inputmode", "none");
    open({ target: t, title: t.placeholder || "", value: t.value });
  });

  return { open, close };
})();

function askText(title, value) {
  return new Promise((resolve) => OSK.open({ title, value: value || "", resolve }));
}

function askConfirm(text, yes = "Yes", no = "Cancel") {
  return new Promise((resolve) => {
    const d = document.createElement("div");
    d.className = "confirm-sheet";
    d.innerHTML = `<div class="confirm-box"><div class="big"></div><div class="row"><button data-v="0">${no}</button><button data-v="1" class="danger">${yes}</button></div></div>`;
    d.querySelector(".big").textContent = text;
    d.onclick = (e) => { const v = e.target.dataset.v; if (v !== undefined) { d.remove(); resolve(v === "1"); } };
    document.body.appendChild(d);
  });
}
