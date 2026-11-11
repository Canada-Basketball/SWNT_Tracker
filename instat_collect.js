// Hudl InStat collector: run in a logged-in InStat tab (app.hudl.com/instat/basketball/...).
// It only records the responses the InStat app loads while it walks each player's Games and
// Field goals pages; it never reads or stores the login. Set the Field goals range to
// "All games of current season" once (the app remembers it), then:
//   await instatRun([2025395, 32638, ...])   // InStat ids from players.json
// and click the red button to copy the JSON; save it as data/instat/2026-27.json
// (on macOS: pbpaste > data/instat/2026-27.json).
(() => {
  const SEASON_ID = 38; // InStat id for 2026-27
  window.__cap = [];
  const of = window.fetch;
  window.fetch = async function (u, o) {
    const r = await of.apply(this, arguments);
    try {
      const url = typeof u === "string" ? u : u.url;
      if (url.includes("instatscout")) window.__cap.push({ body: o && o.body, resp: await r.clone().text() });
    } catch (e) {}
    return r;
  };
  const oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__u = u; return oo.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (b) {
    if ((this.__u || "").includes("instatscout"))
      this.addEventListener("load", () => window.__cap.push({ body: b, resp: String(this.responseText) }));
    return os.apply(this, arguments);
  };

  const go = async (path) => {
    history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
    await new Promise((r) => setTimeout(r, 3500));
  };
  const IDS = [3, 4, 5, 7, 8, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 165]; // PT FG+ FG 3PT+ 3PT FT+ FT OREB DREB REB AST STL BLK TOV F +/-

  function pack(pid) {
    const P = (c) => { try { return JSON.parse(c.body); } catch (e) { return {}; } };
    const D = (c, k) => { try { return JSON.parse(c.resp).data[0][k]; } catch (e) { return null; } };
    const ms = {}, tours = {}, stat = {}, shots = {};
    window.__cap.forEach((c) => {
      const b = P(c), pr = b.params || {};
      if (pr._p_player_id !== pid) return;
      if (b.proc === "scout_uni_advanced_matches_list") {
        const d = D(c, b.proc); if (!d) return;
        (d.tournaments || []).forEach((t) => (tours[t.id] = t.name_eng));
        (d.matches || []).forEach((m) => (ms[m.id] = m));
      }
      if (b.proc === "scout_uni_player_matches_stat") (D(c, b.proc) || []).forEach((s) => (stat[s.match_id] = s));
      if (b.proc === "scout_map_shoot") {
        const d = D(c, b.proc);
        if (d) Object.entries(d.events || {}).forEach(([k, v]) => (shots[k] = v
          .filter((e) => e.player === pid && e.type === 1 && !/F$/.test(e.shot))
          .map((e) => [Math.round(e.x * 10) / 10, Math.round(e.y * 10) / 10, e.shot.includes("+") ? 1 : 0, e.shot[0] === "3" ? 1 : 0])));
      }
    });
    const games = Object.values(ms).filter((m) => m.season_id === SEASON_ID).map((m) => {
      const s = stat[m.id], v = {};
      if (s) s.params.forEach((x) => { if (x.o === 0) v[x.p] = x.v; });
      return [m.id, m.date.slice(0, 10), tours[m.tournament_id] || String(m.tournament_id), m.team.name_eng, m.team.score,
        m.opp_team.name_eng, m.opp_team.score, m.home, s ? Math.round(s.time.total) : null,
        ...(s ? IDS.map((i) => v[i] ?? 0) : []), shots[m.id] ? 1 : 0];
    });
    const keep = new Set(games.map((g) => String(g[0])));
    return { g: games, s: Object.fromEntries(Object.entries(shots).filter(([k]) => keep.has(k))) };
  }

  window.instatRun = async (ids) => {
    const out = {};
    for (const pid of ids) {
      await go(`/instat/basketball/players/${pid}/matches`);
      await go(`/instat/basketball/players/${pid}/fieldgoals`);
      const r = pack(pid);
      if (r.g.length) out[pid] = r;
    }
    window.__out = JSON.stringify(out);
    const b = document.createElement("button");
    b.textContent = "COPY INSTAT DATA";
    b.style.cssText = "position:fixed;top:120px;left:600px;z-index:999999;padding:20px 30px;font-size:20px;background:#ba0c2f;color:#fff";
    b.onclick = async () => { await navigator.clipboard.writeText(window.__out); b.textContent = "COPIED"; setTimeout(() => b.remove(), 1500); };
    document.body.appendChild(b);
    return Object.entries(out).map(([k, v]) => `${k}: ${v.g.length} games`).join("\n");
  };
})();
