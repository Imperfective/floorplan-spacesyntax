// 도면 평가 프로그램 — 구글 로그인 · 허용 이메일 · 활동 기록 API (의존성 없음: Node 22 내장 http · crypto · node:sqlite)
//
//   Caddy(sapcesyntax.com)가 모든 요청을 forward_auth 로 /api/auth/check 에 물어보고, 로그인 안 된 요청은
//   구글 로그인으로 보낸다. 회원가입은 없다 — 관리자가 허용한 이메일(과 관리자)만 들어온다.
//
//   환경 변수
//     GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET   구글 OAuth 클라이언트(웹 애플리케이션). 리디렉션 URI = PUBLIC_ORIGIN/api/auth/callback
//     PUBLIC_ORIGIN    https://sapcesyntax.com
//     ADMIN_EMAILS     관리자 이메일(쉼표로 여럿) — 항상 로그인 가능, 허용 목록·활동 기록 관리
//     DB_PATH          SQLite 파일(기본 /data/floorplan-api.db)
//     PORT             기본 8790
//     DEV_LOGIN=1      로컬 시험용 /api/auth/dev?email= (PUBLIC_ORIGIN이 https면 켜지지 않는다)
import http from "node:http";
import crypto from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import zlib from "node:zlib";

const CFG = {
  clientId: process.env.GOOGLE_CLIENT_ID || "",
  clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
  origin: (process.env.PUBLIC_ORIGIN || "http://localhost:8790").replace(/\/$/, ""),
  admins: (process.env.ADMIN_EMAILS || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean),
  dbPath: process.env.DB_PATH || "/data/floorplan-api.db",
  port: +process.env.PORT || 8790,
};
// 클라이언트 ID는 로그인 주소에 그대로 실리므로 형식이 다르면(예: 보안 비밀번호를 ID 칸에 넣음) 쓰지 않는다 — 비밀이 공개되는 것을 막는다
if (CFG.clientId && !/^[\w-]+\.apps\.googleusercontent\.com$/.test(CFG.clientId)) {
  console.error("GOOGLE_CLIENT_ID 형식이 아닙니다(…apps.googleusercontent.com) — 로그인을 끈 채로 시작합니다");
  CFG.clientId = ""; CFG.clientSecret = "";
}
CFG.devLogin = process.env.DEV_LOGIN === "1" && !CFG.origin.startsWith("https://");
CFG.secure = CFG.origin.startsWith("https://");
const SID = CFG.secure ? "__Host-fp_sid" : "fp_sid", STATE = CFG.secure ? "__Host-fp_state" : "fp_state";
const SESSION_DAYS = 30;

/* ── 저장소 ── */
const db = new DatabaseSync(CFG.dbPath);
db.exec(`PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, note TEXT, added_by TEXT, added_at TEXT, name TEXT, last_login TEXT);
  CREATE TABLE IF NOT EXISTS sessions (sid_hash TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT, created TEXT, expires INTEGER);
  CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, email TEXT, action TEXT NOT NULL, detail TEXT, page TEXT, ip TEXT, ua TEXT);
  CREATE INDEX IF NOT EXISTS events_email ON events(email);
  CREATE INDEX IF NOT EXISTS events_action ON events(action);
  CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, name TEXT, memo TEXT, author TEXT, author_name TEXT, created TEXT, meta TEXT, body BLOB, size INTEGER);`);
const Q = {
  user: db.prepare("SELECT * FROM users WHERE email = ?"),
  users: db.prepare("SELECT u.*, (SELECT COUNT(*) FROM events e WHERE e.email = u.email) AS n_events, (SELECT MAX(ts) FROM events e WHERE e.email = u.email) AS last_event FROM users u ORDER BY u.added_at"),
  addUser: db.prepare("INSERT INTO users (email, note, added_by, added_at) VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET note = excluded.note"),
  delUser: db.prepare("DELETE FROM users WHERE email = ?"),
  touchUser: db.prepare("UPDATE users SET name = ?, last_login = ? WHERE email = ?"),
  session: db.prepare("SELECT * FROM sessions WHERE sid_hash = ? AND expires > ?"),
  addSession: db.prepare("INSERT INTO sessions (sid_hash, email, name, created, expires) VALUES (?, ?, ?, ?, ?)"),
  delSession: db.prepare("DELETE FROM sessions WHERE sid_hash = ?"),
  delSessionsOf: db.prepare("DELETE FROM sessions WHERE email = ?"),
  purge: db.prepare("DELETE FROM sessions WHERE expires <= ?"),
  snaps: db.prepare("SELECT id, name, memo, author, author_name, created, meta, size FROM snapshots ORDER BY created DESC"),
  snap: db.prepare("SELECT * FROM snapshots WHERE id = ?"),
  addSnap: db.prepare("INSERT INTO snapshots (id, name, memo, author, author_name, created, meta, body, size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"),
  delSnap: db.prepare("DELETE FROM snapshots WHERE id = ?"),
  log: db.prepare("INSERT INTO events (ts, email, action, detail, page, ip, ua) VALUES (?, ?, ?, ?, ?, ?, ?)"),
};
const now = () => new Date().toISOString();
const sha = (s) => crypto.createHash("sha256").update(s).digest("hex");
const isAdmin = (email) => CFG.admins.includes(email);
const allowed = (email) => isAdmin(email) || !!Q.user.get(email);
function logEvent(req, email, action, detail = null, page = null) {
  Q.log.run(now(), email, action, detail == null ? null : typeof detail === "string" ? detail : JSON.stringify(detail), page,
    clientIp(req), String(req.headers["user-agent"] || "").slice(0, 300));
}
const clientIp = (req) => String(req.headers["x-forwarded-for"] || req.socket.remoteAddress || "").split(",")[0].trim();

/* ── HTTP 도우미 ── */
function cookies(req) {
  const out = {};
  for (const part of String(req.headers.cookie || "").split(";")) { const i = part.indexOf("="); if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim()); }
  return out;
}
const cookie = (name, value, maxAge) => `${name}=${encodeURIComponent(value)}; Path=/; HttpOnly; SameSite=Lax${CFG.secure ? "; Secure" : ""}; Max-Age=${maxAge}`;
function send(res, code, body, headers = {}) {
  const isObj = typeof body === "object" && body !== null && !Buffer.isBuffer(body);
  res.writeHead(code, { "Cache-Control": "no-store", "Content-Type": isObj ? "application/json; charset=utf-8" : "text/html; charset=utf-8", ...headers });
  res.end(isObj ? JSON.stringify(body) : body);
}
const redirect = (res, to, headers = {}) => send(res, 302, "", { Location: to, ...headers });
async function readBody(req, max) {
  let size = 0; const chunks = [];
  for await (const c of req) { size += c.length; if (size > max) throw Object.assign(new Error("too large"), { code: 413 }); chunks.push(c); }
  return Buffer.concat(chunks);
}
async function readJson(req, max = 64 * 1024) {
  let size = 0; const chunks = [];
  for await (const c of req) { size += c.length; if (size > max) throw Object.assign(new Error("too large"), { code: 413 }); chunks.push(c); }
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"); } catch { throw Object.assign(new Error("bad json"), { code: 400 }); }
}
function currentUser(req) {
  const sid = cookies(req)[SID]; if (!sid) return null;
  const s = Q.session.get(sha(sid), Date.now()); if (!s) return null;
  return { email: s.email, name: s.name, admin: isAdmin(s.email), sidHash: s.sid_hash };
}
/* 쓰기 요청은 같은 사이트에서 온 JSON만 — 다른 사이트가 사용자 쿠키로 보내는 요청(CSRF)을 막는다 */
const sameOrigin = (req) => req.headers.origin === CFG.origin && String(req.headers["content-type"] || "").startsWith("application/json");
const safeNext = (n) => (typeof n === "string" && n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/api/") ? n : "/");

/* ── 로그인 화면(서버가 직접 그린다 — 정적 사이트가 막혀 있을 때 보이는 화면) ── */
const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
function page(title, body) {
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)} · 도면 평가 프로그램</title>
<style>body{margin:0;min-height:100vh;word-break:keep-all;display:grid;place-items:center;background:#F7F8F9;color:#1B1F23;font:14px/1.6 "Pretendard Variable",Pretendard,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;padding:16px;box-sizing:border-box}
.card{background:#fff;border:1px solid #E6E8EB;border-radius:12px;padding:32px;max-width:420px;width:100%;box-sizing:border-box}
h1{font-size:20px;margin:0 0 8px}p{color:#5B6570;margin:0 0 20px}.brand{display:flex;align-items:center;gap:10px;font-weight:700;margin-bottom:24px;color:#004F59}
.mark{width:32px;height:32px;flex:none}.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;width:100%;box-sizing:border-box;height:44px;border-radius:8px;background:#004F59;color:#fff;text-decoration:none;font-weight:600}
.btn.sec{background:#fff;color:#004F59;border:1px solid #C9D3D6;margin-top:8px}.hint{font-size:12px;color:#8A939C;margin-top:16px}code{font-size:12px}</style></head>
<body><main class="card"><div class="brand"><svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#004F59"/><path d="M8 8h16v16H8zM8 16h7M15 8v16M15 19.5h9" fill="none" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/><path d="M11.5 12 19.5 13.5 19.5 21.7M11.5 20.2 19.5 13.5" fill="none" stroke="#F47D30" stroke-width="1.3"/><circle cx="11.5" cy="12" r="1.9" fill="#F47D30"/><circle cx="19.5" cy="13.5" r="1.9" fill="#F47D30"/><circle cx="19.5" cy="21.7" r="1.9" fill="#F47D30"/><circle cx="11.5" cy="20.2" r="1.9" fill="#F47D30"/></svg>도면 평가 프로그램</div>${body}</main></body></html>`;
}
const loginPage = (next, msg = "") => page("로그인", `<h1>로그인</h1><p>${msg || "허용된 구글 계정으로 로그인해 주세요.<br>회원가입은 필요 없습니다."}</p>
  <a class="btn" href="/api/auth/login?next=${encodeURIComponent(next)}">Google 계정으로 로그인</a>
  <div class="hint">이 프로그램은 누가 어떤 작업을 했는지 기록합니다.<br>(로그인 계정 · 시각 · 작업 내용)<br>접근 권한은 관리자에게 요청하세요.</div>`);

/* ── 라우트 ── */
async function handle(req, res) {
  const url = new URL(req.url, CFG.origin), p = url.pathname;

  // Caddy forward_auth — 통과면 200, 아니면 로그인 화면으로
  if (p === "/api/auth/check") {
    const u = currentUser(req);
    if (u) return send(res, 200, "", { "X-Auth-Email": u.email });
    const fwd = String(req.headers["x-forwarded-uri"] || "/");
    const wantsHtml = String(req.headers.accept || "").includes("text/html");
    return wantsHtml ? redirect(res, "/api/auth/signin?next=" + encodeURIComponent(safeNext(fwd))) : send(res, 401, { error: "login required" });
  }
  // 화면이 로그인을 요구할지 — 구글 설정이 들어가기 전에는 사이트를 막지 않는다(앞단 Caddy 관문은 설정 뒤에 켠다)
  if (p === "/api/auth/config") return send(res, 200, { login: !!(CFG.clientId && CFG.clientSecret) || CFG.devLogin });
  if (p === "/api/auth/signin") return send(res, 200, loginPage(safeNext(url.searchParams.get("next"))));
  if (p === "/api/auth/bye") return send(res, 200, page("로그아웃", `<h1>로그아웃했습니다</h1><p>다시 쓰려면 로그인해 주세요.</p><a class="btn" href="/api/auth/login?next=%2F">Google 계정으로 로그인</a>`));

  if (p === "/api/auth/login") {
    if (!CFG.clientId || !CFG.clientSecret) return send(res, 503, page("준비 중", `<h1>로그인 준비 중</h1><p>서버에 구글 로그인 설정(GOOGLE_CLIENT_ID · GOOGLE_CLIENT_SECRET)이 아직 없습니다.</p>`));
    const state = crypto.randomBytes(24).toString("base64url"), next = safeNext(url.searchParams.get("next"));
    const q = new URLSearchParams({ client_id: CFG.clientId, redirect_uri: CFG.origin + "/api/auth/callback", response_type: "code",
      scope: "openid email profile", state, prompt: "select_account" });
    return redirect(res, "https://accounts.google.com/o/oauth2/v2/auth?" + q, { "Set-Cookie": cookie(STATE, state + "|" + next, 600) });
  }
  if (p === "/api/auth/callback") {
    const [state, next] = String(cookies(req)[STATE] || "").split("|");
    const clear = cookie(STATE, "", 0);
    if (!state || state !== url.searchParams.get("state")) return send(res, 400, loginPage("/", "로그인 요청이 만료되었거나 올바르지 않습니다. 다시 시도해 주세요."), { "Set-Cookie": clear });
    if (url.searchParams.get("error")) return send(res, 200, loginPage(safeNext(next), "구글 로그인이 취소되었습니다."), { "Set-Cookie": clear });
    let claims;
    try {
      // 토큰 엔드포인트에서 TLS로 직접 받은 ID 토큰이라 서명 검증 없이 내용을 쓸 수 있다(구글 OpenID Connect 문서). 발급자·대상·만료는 확인한다.
      const r = await fetch("https://oauth2.googleapis.com/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ code: url.searchParams.get("code") || "", client_id: CFG.clientId, client_secret: CFG.clientSecret,
          redirect_uri: CFG.origin + "/api/auth/callback", grant_type: "authorization_code" }) });
      const tok = await r.json();
      if (!r.ok || !tok.id_token) throw new Error(tok.error || "token");
      claims = JSON.parse(Buffer.from(tok.id_token.split(".")[1], "base64url").toString("utf8"));
      if (!["accounts.google.com", "https://accounts.google.com"].includes(claims.iss) || claims.aud !== CFG.clientId || claims.exp * 1000 < Date.now() || !claims.email_verified) throw new Error("claims");
    } catch (e) {
      console.error("callback", e.message);
      return send(res, 502, loginPage("/", "구글 로그인 확인에 실패했습니다. 잠시 뒤 다시 시도해 주세요."), { "Set-Cookie": clear });
    }
    const email = String(claims.email).toLowerCase(), name = String(claims.name || "");
    if (!allowed(email)) {
      logEvent(req, email, "login_denied");
      return send(res, 403, page("접근 권한 없음", `<h1>접근 권한이 없습니다</h1><p><b>${esc(email)}</b> 계정은 허용 목록에 없습니다. 관리자에게 허용을 요청하거나 다른 계정으로 로그인해 주세요.</p>
        <a class="btn" href="/api/auth/login?next=%2F">다른 계정으로 로그인</a>`), { "Set-Cookie": clear });
    }
    const sid = crypto.randomBytes(32).toString("base64url");
    Q.purge.run(Date.now());
    Q.addSession.run(sha(sid), email, name, now(), Date.now() + SESSION_DAYS * 864e5);
    Q.touchUser.run(name, now(), email);
    logEvent(req, email, "login");
    return redirect(res, safeNext(next), { "Set-Cookie": [clear, cookie(SID, sid, SESSION_DAYS * 86400)] });
  }
  if (p === "/api/auth/dev" && CFG.devLogin) {   // 로컬 시험 전용
    const email = String(url.searchParams.get("email") || "").toLowerCase();
    if (!allowed(email)) return send(res, 403, { error: "not allowed", email });
    const sid = crypto.randomBytes(32).toString("base64url");
    Q.addSession.run(sha(sid), email, "dev", now(), Date.now() + 864e5);
    logEvent(req, email, "login", { dev: true });
    return redirect(res, "/", { "Set-Cookie": cookie(SID, sid, 86400) });
  }

  // 여기부터는 로그인한 사용자만
  const u = currentUser(req);
  if (!u) return send(res, 401, { error: "login required" });
  const write = req.method === "POST" || req.method === "DELETE";
  if (write && !sameOrigin(req)) return send(res, 403, { error: "bad origin" });

  if (p === "/api/auth/logout" && req.method === "POST") {
    Q.delSession.run(u.sidHash); logEvent(req, u.email, "logout");
    return send(res, 200, { ok: true }, { "Set-Cookie": cookie(SID, "", 0) });
  }
  if (p === "/api/me") return send(res, 200, { email: u.email, name: u.name, admin: u.admin });
  if (p === "/api/log" && req.method === "POST") {
    const b = await readJson(req);
    const action = String(b.action || "").slice(0, 64);
    if (!/^[a-z][a-z0-9_.-]*$/i.test(action)) return send(res, 400, { error: "bad action" });
    const detail = b.detail == null ? null : JSON.stringify(b.detail).slice(0, 8000);
    logEvent(req, u.email, action, detail, String(b.page || "").slice(0, 200));
    return send(res, 200, { ok: true });
  }

  // 공유 보관 기록 — 로그인한 사람 모두 같은 목록을 본다. 지우기는 만든 사람과 관리자만
  if (p === "/api/snapshots" && req.method === "GET")
    return send(res, 200, { snapshots: Q.snaps.all().map((r) => ({ ...r, meta: JSON.parse(r.meta || "{}") })) });
  if (p === "/api/snapshots" && req.method === "POST") {
    const raw = await readBody(req, 64 * 1024 * 1024);
    let s; try { s = JSON.parse(raw.toString("utf8")); } catch { return send(res, 400, { error: "JSON이 아닙니다" }); }
    if (!s || s.kind !== "aihub-stats" || !s.summary) return send(res, 400, { error: "통계 JSON(kind: aihub-stats)이 아닙니다" });
    const id = "s" + Date.now().toString(36) + crypto.randomBytes(3).toString("hex");
    s.id = id; delete s.builtin;
    const meta = { n_units: s.summary.n_units, n_files: s.summary.n_files, mean: s.summary.score && s.summary.score.mean,
      pass_rate: s.summary.feasibility_pass_rate, n_criteria: ((s.config && s.config.criteria) || []).filter((c) => c.enabled !== false).length, origin: String(s.origin || "").slice(0, 40) };
    const name = String(s.name || "").slice(0, 200), memo = String(s.memo || "").slice(0, 2000), body = zlib.gzipSync(Buffer.from(JSON.stringify(s)));
    Q.addSnap.run(id, name, memo, u.email, u.name || "", s.created || now(), JSON.stringify(meta), body, body.length);
    logEvent(req, u.email, "archive.save", { id, name, units: meta.n_units });
    return send(res, 200, { id });
  }
  const sm = p.match(/^\/api\/snapshots\/([\w-]+)$/);
  if (sm) {
    const row = Q.snap.get(sm[1]); if (!row) return send(res, 404, { error: "기록이 없습니다" });
    if (req.method === "GET") return send(res, 200, zlib.gunzipSync(row.body).toString("utf8"), { "Content-Type": "application/json; charset=utf-8" });
    if (req.method === "DELETE") {
      if (row.author !== u.email && !u.admin) return send(res, 403, { error: "만든 사람이나 관리자만 지울 수 있습니다" });
      Q.delSnap.run(row.id); logEvent(req, u.email, "archive.delete", { id: row.id, name: row.name, author: row.author });
      return send(res, 200, { ok: true });
    }
  }

  // 관리자
  if (p.startsWith("/api/admin/")) {
    if (!u.admin) return send(res, 403, { error: "admin only" });
    if (p === "/api/admin/users" && req.method === "GET")
      return send(res, 200, { admins: CFG.admins, users: Q.users.all() });
    if (p === "/api/admin/users" && req.method === "POST") {
      const b = await readJson(req), email = String(b.email || "").trim().toLowerCase(), note = String(b.note || "").slice(0, 200);
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) return send(res, 400, { error: "이메일 형식이 아닙니다" });
      Q.addUser.run(email, note, u.email, now());
      logEvent(req, u.email, "admin.allow", { email, note });
      return send(res, 200, { ok: true });
    }
    if (p === "/api/admin/users" && req.method === "DELETE") {
      const email = String(url.searchParams.get("email") || "").toLowerCase();
      if (isAdmin(email)) return send(res, 400, { error: "관리자 계정은 뺄 수 없습니다" });
      Q.delUser.run(email); Q.delSessionsOf.run(email);   // 빼면 바로 로그아웃된다
      logEvent(req, u.email, "admin.revoke", { email });
      return send(res, 200, { ok: true });
    }
    if (p === "/api/admin/logs" || p === "/api/admin/logs.csv") {
      const where = [], args = [];
      for (const [k, col] of [["email", "email"], ["action", "action"]]) { const v = url.searchParams.get(k); if (v) { where.push(`${col} = ?`); args.push(v); } }
      const q = url.searchParams.get("q"); if (q) { where.push("(detail LIKE ? OR page LIKE ?)"); args.push(`%${q}%`, `%${q}%`); }
      const from = url.searchParams.get("from"), to = url.searchParams.get("to");
      if (from) { where.push("ts >= ?"); args.push(from); } if (to) { where.push("ts < ?"); args.push(to); }
      const csv = p.endsWith(".csv"), before = +url.searchParams.get("before") || 0;
      if (before && !csv) { where.push("id < ?"); args.push(before); }
      const limit = csv ? 100000 : Math.min(500, +url.searchParams.get("limit") || 100);
      const rows = db.prepare(`SELECT * FROM events ${where.length ? "WHERE " + where.join(" AND ") : ""} ORDER BY id DESC LIMIT ${limit}`).all(...args);
      if (!csv) {
        const actions = db.prepare("SELECT action, COUNT(*) AS n FROM events GROUP BY action ORDER BY n DESC").all();
        return send(res, 200, { rows, next: rows.length === limit ? rows[rows.length - 1].id : null, actions });
      }
      logEvent(req, u.email, "admin.export_logs", { n: rows.length, email: url.searchParams.get("email"), action: url.searchParams.get("action") });
      const cell = (v) => { const s = v == null ? "" : String(v); return /^[=+\-@]/.test(s) ? `"'${s.replace(/"/g, '""')}"` : `"${s.replace(/"/g, '""')}"`; };
      const out = "﻿id,ts,email,action,detail,page,ip,ua\r\n" + rows.map(r => ["id", "ts", "email", "action", "detail", "page", "ip", "ua"].map(k => cell(r[k])).join(",")).join("\r\n");
      return send(res, 200, out, { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": `attachment; filename="activity_${now().slice(0, 10)}.csv"` });
    }
  }
  return send(res, 404, { error: "not found" });
}

http.createServer((req, res) => {
  handle(req, res).catch((e) => { console.error(e); if (!res.headersSent) send(res, e.code || 500, { error: e.code ? e.message : "server error" }); });
}).listen(CFG.port, () => console.log(`floorplan-api :${CFG.port} origin=${CFG.origin} admins=${CFG.admins.join(",")} google=${CFG.clientId ? "on" : "off"}${CFG.devLogin ? " DEV_LOGIN" : ""}`));
