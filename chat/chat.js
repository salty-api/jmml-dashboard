// League chat bubble. Talks to the Cloudflare Worker, which holds the API key.
(function () {
  var WORKER_URL = "https://jmml-bot.fantraxrob.workers.dev"; // paste your Worker address here
  var BOT_NAME = "Jim Murphy";
  var GREETING = "Jim Murphy here. Ask me about standings, matchups, rosters, auction prices, rivalries, or JMML history.";
  var SUGGESTIONS = ["Who's winning this week?", "Who has the most titles?", "Salty vs T-How all time?"];

  var history = [];
  var busy = false;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  var btn = el("button", "lb-launch");
  btn.setAttribute("aria-label", "Open league chat");
  btn.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><path fill="currentColor" d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/></svg>';

  var panel = el("div", "lb-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", BOT_NAME);
  var head = el("div", "lb-head");
  head.appendChild(el("span", "lb-title", BOT_NAME));
  var close = el("button", "lb-close", "×");
  close.setAttribute("aria-label", "Close chat");
  head.appendChild(close);
  var log = el("div", "lb-log");
  log.setAttribute("aria-live", "polite");
  var chips = el("div", "lb-chips");
  var form = el("form", "lb-form");
  var input = el("input", "lb-input");
  input.placeholder = "Ask a question";
  input.maxLength = 500;
  var send = el("button", "lb-send", "Send");
  send.type = "submit";
  form.appendChild(input);
  form.appendChild(send);
  panel.appendChild(head);
  panel.appendChild(log);
  panel.appendChild(chips);
  panel.appendChild(form);

  function add(role, text) {
    var m = el("div", "lb-msg lb-" + role, text);
    log.appendChild(m);
    log.scrollTop = log.scrollHeight;
    return m;
  }

  add("bot", GREETING);
  SUGGESTIONS.forEach(function (s) {
    var c = el("button", "lb-chip", s);
    c.type = "button";
    c.onclick = function () { ask(s); };
    chips.appendChild(c);
  });

  function ask(q) {
    q = (q || "").trim();
    if (!q || busy) return;
    busy = true;
    chips.style.display = "none";
    input.value = "";
    add("user", q);
    var wait = add("bot lb-wait", "Thinking…");
    fetch(WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, history: history })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var a = d.answer || "Sorry, something went wrong.";
        wait.className = "lb-msg lb-bot";
        wait.textContent = a;
        history.push({ role: "user", content: q }, { role: "assistant", content: a });
        history = history.slice(-12);
      })
      .catch(function () {
        wait.className = "lb-msg lb-bot";
        wait.textContent = "I couldn't reach the server. Try again in a moment.";
      })
      .then(function () {
        busy = false;
        log.scrollTop = log.scrollHeight;
        if (!phone.matches) input.focus();
      });
  }

  form.onsubmit = function (e) { e.preventDefault(); ask(input.value); };
  var phone = window.matchMedia("(max-width: 600px), (max-height: 500px)");
  var vv = window.visualViewport;
  // On phones the sheet tracks the visible area so the on-screen keyboard never covers the input
  function fit() {
    if (!phone.matches || !panel.classList.contains("lb-open") || !vv) { panel.style.removeProperty("--lb-h"); panel.style.top = ""; return; }
    panel.style.setProperty("--lb-h", vv.height + "px");
    panel.style.top = vv.offsetTop + "px";
    log.scrollTop = log.scrollHeight;
  }
  if (vv) { vv.addEventListener("resize", fit); vv.addEventListener("scroll", fit); }
  btn.onclick = function () {
    panel.classList.add("lb-open"); btn.classList.add("lb-hide");
    if (phone.matches) document.documentElement.classList.add("lb-lock"); else input.focus();  // no auto-focus on phones: it would pop the keyboard over the greeting
    fit();
  };
  close.onclick = function () {
    panel.classList.remove("lb-open"); btn.classList.remove("lb-hide");
    document.documentElement.classList.remove("lb-lock"); fit();
  };

  document.body.appendChild(btn);
  document.body.appendChild(panel);
})();
