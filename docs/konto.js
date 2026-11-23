// Konten: Registrierung mit E-Mail-Bestätigungslink, danach Passwort festlegen. Läuft über Google Firebase.
const CFG = window.BB_FIREBASE;
const $ = (id) => document.getElementById(id);
// SHA-256 der Admin-E-Mail (die Rechte selbst prüft Firebase in den Firestore-Regeln)
const ADMIN_HASH = "38d8fd845c8945f4493ba284fccd02990f83ccf67e463e2f22483a0c01e52daf";
const SYNC_KEYS = ["bb-favs", "bb-depot", "bb-alerts"];
const say = (t, cls) => { const m = $("k-status"); m.textContent = t || ""; m.className = "k-msg" + (cls ? " " + cls : ""); };
const showBox = (id) => ["k-off", "k-out", "k-link", "k-in"].forEach((b) => { $(b).hidden = b !== id; });
const ERR = {
  "auth/invalid-email": "Diese E-Mail-Adresse ist ungültig.",
  "auth/invalid-credential": "E-Mail oder Passwort stimmt nicht.",
  "auth/wrong-password": "E-Mail oder Passwort stimmt nicht.",
  "auth/user-not-found": "E-Mail oder Passwort stimmt nicht.",
  "auth/too-many-requests": "Zu viele Versuche. Bitte warte ein paar Minuten.",
  "auth/weak-password": "Das Passwort ist zu schwach, nimm mindestens 8 Zeichen.",
  "auth/invalid-action-code": "Der Link ist abgelaufen oder wurde schon benutzt. Bitte registriere dich noch einmal.",
  "auth/expired-action-code": "Der Link ist abgelaufen. Bitte registriere dich noch einmal.",
  "auth/requires-recent-login": "Bitte melde dich ab und neu an und versuche es dann noch einmal.",
  "auth/network-request-failed": "Keine Verbindung. Prüfe dein Internet.",
  "auth/email-already-in-use": "Für diese E-Mail gibt es schon ein Konto. Melde dich an.",
  "auth/quota-exceeded": "Heute wurden zu viele E-Mails verschickt. Bitte morgen noch einmal versuchen.",
};
const errText = (e) => ERR[e && e.code] || "Das hat nicht geklappt" + (e && e.code ? " (" + e.code + ")" : "") + ".";

async function sha(t) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(t));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

if (!CFG) {
  showBox("k-off");
  window.BB_hefteKey = async () => ({ reason: "off" });
  if (window.BB_onAuth) window.BB_onAuth(false);
} else {
  const V = "10.12.2", base = "https://www.gstatic.com/firebasejs/" + V + "/";
  let mods;
  try { mods = await Promise.all([import(base + "firebase-app.js"), import(base + "firebase-auth.js"), import(base + "firebase-firestore.js")]); }
  catch (er) {
    window.BB_hefteKey = async () => ({ reason: "off" });
    if (window.BB_onAuth) window.BB_onAuth(false);
    showBox("k-off"); $("k-off").querySelector("p").textContent = "Konten sind gerade nicht erreichbar. Prüfe deine Verbindung und lade die Seite neu.";
    throw er;
  }
  const [{ initializeApp }, A, F] = mods;
  const app = initializeApp(CFG);
  const auth = A.getAuth(app);
  auth.languageCode = "de";
  const db = F.getFirestore(app);
  const home = location.origin + location.pathname;
  let me = null, needPw = false, access = false, authReady;
  const ready = new Promise((r) => { authReady = r; });
  // Schlüssel für den gesperrten Bereich: Firebase gibt ihn nur dem Admin und freigeschalteten Konten
  window.BB_hefteKey = async () => {
    await ready;
    if (!me || needPw) return { reason: "login" };
    try {
      const d = await F.getDoc(F.doc(db, "config", "hefte"));
      return d.exists() && d.data().key ? { key: d.data().key } : { reason: "noaccess" };
    } catch (er) { return { reason: er && er.code === "permission-denied" ? "noaccess" : "error" }; }
  };

  // Umschalten Anmelden / Registrieren / Passwort vergessen
  document.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-k]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    ["login", "reg", "reset"].forEach((k) => { $("k-" + k).hidden = k !== b.dataset.k; });
    say("");
  }));

  $("k-login").addEventListener("submit", async (e) => {
    e.preventDefault(); say("Melde an …");
    try { await A.signInWithEmailAndPassword(auth, $("k-l-mail").value.trim(), $("k-l-pw").value); say(""); }
    catch (er) { say(errText(er), "err"); }
  });
  $("k-reg").addEventListener("submit", async (e) => {
    e.preventDefault();
    const mail = $("k-r-mail").value.trim();
    say("Schicke den Link …");
    try {
      await A.sendSignInLinkToEmail(auth, mail, { url: home + "#konto", handleCodeInApp: true });
      localStorage.setItem("bb-reg-email", mail);
      say("📧 Wir haben dir einen Bestätigungs-Link an " + mail + " geschickt. Öffne die E-Mail und tippe auf den Link (schau auch im Spam-Ordner nach).", "ok");
    } catch (er) { say(errText(er), "err"); }
  });
  $("k-reset").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await A.sendPasswordResetEmail(auth, $("k-x-mail").value.trim(), { url: home + "#konto" }); say("📧 Falls ein Konto existiert, ist die E-Mail zum Zurücksetzen unterwegs.", "ok"); }
    catch (er) { say(errText(er), "err"); }
  });

  // Rückkehr über den Bestätigungs-Link
  async function finishLink(mail) {
    say("Bestätige …");
    try {
      await A.signInWithEmailLink(auth, mail, location.href);
      localStorage.removeItem("bb-reg-email");
      history.replaceState(null, "", location.pathname + "#konto");
      needPw = true;
      say("");
    } catch (er) { say(errText(er), "err"); showBox("k-out"); }
  }
  if (A.isSignInWithEmailLink(auth, location.href)) {
    if (location.hash !== "#konto") history.replaceState(null, "", location.pathname + location.search + "#konto");
    const mail = localStorage.getItem("bb-reg-email");
    if (mail) finishLink(mail);
    else { showBox("k-link"); $("k-confirm").hidden = false; $("k-setpw").hidden = true; }
  }
  $("k-confirm").addEventListener("submit", (e) => { e.preventDefault(); finishLink($("k-c-mail").value.trim()); });

  $("k-setpw").addEventListener("submit", async (e) => {
    e.preventDefault();
    const p1 = $("k-p1").value, p2 = $("k-p2").value, name = $("k-name").value.trim();
    if (name.length < 2) { say("Bitte gib einen Namen mit mindestens 2 Zeichen an.", "err"); return; }
    if (p1.length < 8) { say("Das Passwort braucht mindestens 8 Zeichen.", "err"); return; }
    if (p1 !== p2) { say("Die beiden Passwörter sind nicht gleich.", "err"); return; }
    try {
      await A.updatePassword(auth.currentUser, p1);
      await A.updateProfile(auth.currentUser, { displayName: name });
      await F.setDoc(F.doc(db, "users", auth.currentUser.uid), { hasPassword: true, name }, { merge: true });
      if (window.BB_onAuth) window.BB_onAuth(me.emailVerified && (await sha(me.email.toLowerCase())) === ADMIN_HASH);
      needPw = false; $("k-p1").value = $("k-p2").value = "";
      say("✅ Fertig! Dein Konto ist eingerichtet. Ab jetzt meldest du dich mit E-Mail und Passwort an.", "ok");
      showIn();
    } catch (er) { say(errText(er), "err"); }
  });

  // Einstellungen mit dem Konto abgleichen
  const localPrefs = () => { const o = {}; SYNC_KEYS.forEach((k) => { const v = localStorage.getItem(k); if (v != null) o[k] = v; }); return o; };
  let syncT = null;
  window.BB_sync = () => {
    if (!me) return;
    clearTimeout(syncT);
    syncT = setTimeout(() => { F.setDoc(F.doc(db, "users", me.uid), { prefs: localPrefs(), updated: F.serverTimestamp() }, { merge: true }).catch(() => {}); }, 1500);
  };

  async function showIn() {
    showBox("k-in");
    $("k-me").textContent = me.displayName || me.email.split("@")[0];
    $("k-mail").textContent = me.email;
    const admin = me.emailVerified && (await sha(me.email.toLowerCase())) === ADMIN_HASH;
    $("k-admin").hidden = !admin; $("k-adminbox").hidden = !admin;
    if (admin) loadUsers();
  }
  async function loadUsers() {
    try {
      const snap = await F.getDocs(F.collection(db, "users"));
      const rows = []; snap.forEach((d) => rows.push({ id: d.id, ...d.data() }));
      rows.sort((a, b) => ((b.lastLogin && b.lastLogin.seconds) || 0) - ((a.lastLogin && a.lastLogin.seconds) || 0));
      $("k-count").textContent = "(" + rows.length + ")";
      const fmt = (t) => (t && t.seconds ? new Date(t.seconds * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) + " Uhr" : "–");
      const h = (t) => String(t || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
      $("k-users").innerHTML = rows.map((u) => '<div class="k-user"><div><b>' + h(u.name || "ohne Namen") + "</b> " + h(u.email || u.id) + (u.blocked ? " ⛔" : "") +
        "<small>zuletzt eingeloggt " + fmt(u.lastLogin) + " · dabei seit " + fmt(u.created) + (u.hasPassword ? "" : " · noch kein Passwort") +
        (u.id === me.uid ? " · Admin" : u.heftAccess ? " · 🔓 hat Zugang zum gesperrten Bereich" : " · 🔒 kein Zugang") + "</small></div>" +
        (u.id === me.uid ? "" : '<div class="k-acts"><button class="btn' + (u.heftAccess ? " ghost" : "") + '" type="button" data-access="' + u.id + '" data-a="' + (u.heftAccess ? 1 : 0) + '">' + (u.heftAccess ? "Zugang entziehen" : "Zugang geben") + "</button>" +
          '<button class="btn ghost" type="button" data-block="' + u.id + '" data-b="' + (u.blocked ? 1 : 0) + '">' + (u.blocked ? "Entsperren" : "Sperren") + "</button></div>") + "</div>").join("");
    } catch (er) { $("k-users").textContent = "Nutzerliste lässt sich nicht laden (" + (er.code || "Fehler") + ")."; }
  }
  $("k-users").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-block]"); if (!b) return;
    try { await F.updateDoc(F.doc(db, "users", b.dataset.block), { blocked: b.dataset.b !== "1" }); loadUsers(); }
    catch (er) { say(errText(er), "err"); }
  });

  $("k-users").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-access]"); if (!b) return;
    b.disabled = true;
    try { await F.updateDoc(F.doc(db, "users", b.dataset.access), { heftAccess: b.dataset.a !== "1" }); loadUsers(); }
    catch (er) { say(errText(er), "err"); b.disabled = false; }
  });
  $("k-logout").addEventListener("click", () => A.signOut(auth));
  $("k-delete").addEventListener("click", async () => {
    if (!confirm("Konto wirklich löschen? Das kann man nicht rückgängig machen.")) return;
    try { const u = auth.currentUser; await F.deleteDoc(F.doc(db, "users", u.uid)).catch(() => {}); await A.deleteUser(u); say("Dein Konto wurde gelöscht.", "ok"); }
    catch (er) { say(errText(er), "err"); }
  });

  A.onAuthStateChanged(auth, async (u) => {
    me = u;
    authReady();
    if (!u) { access = false; if (window.BB_onAuth) window.BB_onAuth(false); }
    if (!u) { if ($("k-link").hidden || $("k-confirm").hidden) showBox("k-out"); return; }
    const ref = F.doc(db, "users", u.uid);
    let data = {};
    try { const d = await F.getDoc(ref); data = d.exists() ? d.data() : {}; } catch (er) { /* offline */ }
    if (data.blocked) { await A.signOut(auth); say("Dein Konto wurde gesperrt.", "err"); return; }
    const first = !data.created;
    F.setDoc(ref, first ? { email: u.email, created: F.serverTimestamp(), lastLogin: F.serverTimestamp(), hasPassword: !needPw }
      : { email: u.email, lastLogin: F.serverTimestamp() }, { merge: true }).catch(() => {});
    if (needPw || data.hasPassword === false) {
      needPw = true; showBox("k-link"); $("k-confirm").hidden = true; $("k-setpw").hidden = false;
      if (location.hash !== "#konto") location.hash = "#konto";
    } else showIn();
    const admin = u.emailVerified && (await sha((u.email || "").toLowerCase())) === ADMIN_HASH;
    access = !needPw && !data.blocked && (admin || data.heftAccess === true);
    if (window.BB_onAuth) window.BB_onAuth(access);
    // Einstellungen: vom Konto übernehmen, sonst hochladen
    const remote = data.prefs || {};
    const changed = SYNC_KEYS.some((k) => remote[k] != null && remote[k] !== localStorage.getItem(k));
    if (changed && sessionStorage.getItem("bb-synced") !== u.uid) {
      SYNC_KEYS.forEach((k) => { if (remote[k] != null) localStorage.setItem(k, remote[k]); });
      sessionStorage.setItem("bb-synced", u.uid);
      location.reload();
      return;
    }
    sessionStorage.setItem("bb-synced", u.uid);
    if (!Object.keys(remote).length) window.BB_sync();
  });
  window.BB_konto = (v) => { if (v === "konto" && me && !needPw) showIn(); };
}
