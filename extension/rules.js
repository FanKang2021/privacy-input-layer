/* Core rule port for the browser extension (DOM-layer paste masking). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PilayerRules = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const PHONE = /(?<!\d)1[3-9]\d{9}(?!\d)/g;
  const IDCARD = /(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)/g;
  const BANKCARD = /(?<!\d)\d{16,19}(?!\d)/g;
  const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
  const PRIVKEY = /-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----/g;
  const IPV4 = /(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])/g;
  const SECRET_KEY = /\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)[\w.-]*\s*[:=]\s*/gi;
  const TOKEN = /\b(?:sk-[A-Za-z0-9_-]{20,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g;
  const BIN_PREFIXES = ["4", "51", "52", "53", "54", "55", "34", "37", "6011", "65", "644", "645", "646", "647", "648", "649", "3528", "3589", "36", "38", "39"];
  const BIN_RANGES = [[622126, 622925], [621000, 621999], [620000, 620999]];
  const ID_W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
  const ID_C = "10X98765432";

  function idValid(s) {
    let t = 0;
    for (let i = 0; i < 17; i++) t += parseInt(s[i], 10) * ID_W[i];
    return ID_C[t % 11] === s[17].toUpperCase();
  }
  function luhn(s) {
    let sum = 0, alt = false;
    for (let i = s.length - 1; i >= 0; i--) {
      let d = parseInt(s[i], 10);
      if (alt) { d *= 2; if (d > 9) d -= 9; }
      sum += d; alt = !alt;
    }
    return sum % 10 === 0;
  }
  function binKnown(s) {
    if (BIN_PREFIXES.some((p) => s.startsWith(p))) return true;
    const p6 = parseInt(s.slice(0, 6), 10);
    return BIN_RANGES.some(([a, b]) => p6 >= a && p6 <= b);
  }
  function ipValid(s) { return s.split(".").every((o) => +o >= 0 && +o <= 255); }

  function secretSpan(text, pos) {
    const n = text.length;
    while (pos < n && (text[pos] === " " || text[pos] === "\t")) pos++;
    if (pos >= n) return null;
    if (text[pos] === '"' || text[pos] === "'") {
      const q = text[pos];
      const end = text.indexOf(q, pos + 1);
      if (end === -1 || end === pos + 1) return null;
      if (text.startsWith("{{", pos + 1)) return null;
      return [pos + 1, end];
    }
    if (text.startsWith("{{", pos)) return null;
    let end = text.indexOf("\n", pos);
    if (end === -1) end = n;
    while (end > pos && /[\s\r]/.test(text[end - 1])) end--;
    return end === pos ? null : [pos, end];
  }

  function mask(text) {
    const matches = [];
    const push = (kind, start, end) => matches.push({ kind, start, end, text: text.slice(start, end) });
    for (const m of text.matchAll(PRIVKEY)) push("PRIVKEY", m.index, m.index + m[0].length);
    for (const m of text.matchAll(SECRET_KEY)) {
      const sp = secretSpan(text, m.index + m[0].length);
      if (sp) push("SECRET", sp[0], sp[1]);
    }
    for (const m of text.matchAll(TOKEN)) push("TOKEN", m.index, m.index + m[0].length);
    for (const m of text.matchAll(IDCARD)) if (idValid(m[0])) push("IDCARD", m.index, m.index + m[0].length);
    for (const m of text.matchAll(BANKCARD)) if (luhn(m[0]) && binKnown(m[0])) push("BANKCARD", m.index, m.index + m[0].length);
    for (const m of text.matchAll(PHONE)) push("PHONE", m.index, m.index + m[0].length);
    for (const m of text.matchAll(EMAIL)) push("EMAIL", m.index, m.index + m[0].length);
    for (const m of text.matchAll(IPV4)) if (ipValid(m[0])) push("IP", m.index, m.index + m[0].length);
    const prio = { PRIVKEY: 0, SECRET: 1, TOKEN: 2, IDCARD: 3, BANKCARD: 4, PHONE: 5, EMAIL: 6, IP: 7 };
    matches.sort((a, b) => prio[a.kind] - prio[b.kind] || a.start - b.start || (b.end - b.start) - (a.end - a.start));
    const chosen = [], occupied = [];
    for (const m of matches) {
      if (occupied.some(([s, e]) => m.start < e && s < m.end)) continue;
      chosen.push(m); occupied.push([m.start, m.end]);
    }
    chosen.sort((a, b) => a.start - b.start);
    const counters = {};
    const entries = [];
    let out = "", pos = 0;
    for (const m of chosen) {
      counters[m.kind] = (counters[m.kind] || 0) + 1;
      const ph = `[${m.kind}_${counters[m.kind]}]`;
      entries.push({ kind: m.kind, original: m.text, placeholder: ph });
      out += text.slice(pos, m.start) + ph;
      pos = m.end;
    }
    out += text.slice(pos);
    return { text: out, count: chosen.length, kinds: chosen.map((m) => m.kind), entries };
  }

  return { mask };
});