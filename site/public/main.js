// Hark website: install command for this domain, copy buttons, screenshot tabs, hero demo.

(() => {
  // -- The install command points at whatever domain serves this page ------------------
  if (location.protocol.startsWith("http") && !/^(localhost|127\.)/.test(location.hostname)) {
    const cmd = `curl -fsSL ${location.origin}/install.sh | bash`;
    document.querySelectorAll("#install-cmd, #install-cmd-2").forEach((el) => (el.textContent = cmd));
  }

  // -- Copy buttons -------------------------------------------------------------------
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const text = document.querySelector(button.dataset.copy).textContent.trim();
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const range = document.createRange();
        range.selectNodeContents(document.querySelector(button.dataset.copy));
        getSelection().removeAllRanges();
        getSelection().addRange(range);
        document.execCommand("copy");
      }
      const label = button.querySelector("span");
      button.classList.add("done");
      label.textContent = "Copied";
      setTimeout(() => {
        button.classList.remove("done");
        label.textContent = "Copy";
      }, 1600);
    });
  });

  // -- Screenshot tabs ----------------------------------------------------------------
  const shot = document.getElementById("shot");
  const alts = {
    home: "Hark's Home screen: words this week, words per minute, day streak and recent dictations",
    history: "History: search, copy and delete past dictations",
    notes: "Notes: dictate into Hark's notepad, with an AI title and summary",
    style: "Style: cleanup rules, AI cleanup with Ollama, and a box to try it",
    settings: "Settings: shortcut, typing, feedback, privacy and system options",
  };
  document.querySelectorAll("[data-shot]").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-shot]").forEach((t) => t.setAttribute("aria-selected", t === tab));
      const name = tab.dataset.shot;
      shot.classList.add("swap");
      const next = new Image();
      next.onload = () => {
        shot.src = next.src;
        shot.alt = alts[name];
        shot.classList.remove("swap");
      };
      next.src = `/screenshots/${name}.png`;
    });
  });

  // -- Hero demo: hold key → capsule → transcribing → text appears ----------------------
  const examples = [
    {
      app: "Message",
      said: "Hey team, the build is green. We ship at 3 PM.",
      typed: "Hey team, the build is green. We ship at 3 PM.",
    },
    {
      app: "Notes",
      said: '<del>um</del> so <del>I</del> I think we should meet on Tuesday <del>uh</del>',
      typed: "So I think we should meet on Tuesday.",
    },
    {
      app: "Email",
      said: 'Dear Priya <span class="cmd">comma</span> <span class="cmd">new line</span> thanks for the update <span class="cmd">period</span>',
      typed: "Dear Priya,\nThanks for the update.",
    },
  ];
  const $ = (id) => document.getElementById(id);
  const capsule = $("demo-capsule");
  const bars = [...capsule.querySelectorAll(".bars i")];
  const key = $("demo-key");
  const said = $("demo-said");
  const typed = $("demo-typed");
  const timer = $("demo-timer");
  const status = $("demo-status");
  const hint = $("demo-hint");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  if (reduced) {
    $("demo-app").textContent = examples[1].app;
    said.innerHTML = `<span class="label">You said</span>${examples[1].said}`;
    typed.textContent = examples[1].typed;
    return;
  }

  let wave = 0;
  function animateBars() {
    const t = performance.now() / 1000;
    bars.forEach((bar, i) => {
      const level = 0.25 + 0.75 * Math.abs(Math.sin(t * 7.3 + i * 0.9) * Math.sin(t * 2.1 + i * 0.37));
      bar.style.height = `${4 + level * 20}px`;
    });
    wave = requestAnimationFrame(animateBars);
  }

  async function play(example) {
    $("demo-app").textContent = example.app;
    said.innerHTML = "";
    typed.textContent = "";
    hint.textContent = "Hold to talk";
    await sleep(900);

    key.classList.add("down");
    hint.textContent = "Listening…";
    capsule.className = "capsule show";
    animateBars();
    const start = performance.now();
    const tick = setInterval(() => {
      timer.textContent = `0:0${Math.min(9, Math.floor((performance.now() - start) / 1000) + 1)}`;
    }, 200);
    await sleep(2300);

    key.classList.remove("down");
    clearInterval(tick);
    cancelAnimationFrame(wave);
    hint.textContent = "Released";
    capsule.className = "capsule show transcribing";
    status.innerHTML = '<span class="dots"><b></b><b></b><b></b></span>Transcribing';
    await sleep(800);

    said.innerHTML = `<span class="label">You said</span>${example.said}`;
    const span = document.createElement("span");
    span.className = "fresh";
    span.textContent = example.typed;
    typed.appendChild(span);
    requestAnimationFrame(() => setTimeout(() => span.classList.add("settled"), 400));
    capsule.className = "capsule show done";
    status.textContent = "✓ Inserted";
    hint.textContent = "Done";
    await sleep(900);
    capsule.className = "capsule";
    await sleep(2600);
  }

  (async () => {
    for (let i = 0; ; i = (i + 1) % examples.length) {
      await play(examples[i]);
    }
  })();
})();
