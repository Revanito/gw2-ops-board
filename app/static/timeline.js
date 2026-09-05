(function () {
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach((t) => t.addEventListener("click", () => {
    tabs.forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
  }));

  const bosses = JSON.parse(document.getElementById("boss-data").textContent);
  const zonesByCategory = JSON.parse(document.getElementById("meta-data").textContent);

  const MIN_PER_DAY = 24 * 60;
  const TOTAL_MIN = MIN_PER_DAY * 2;   // two days, so the irregular world-boss pattern never runs dry near midnight
  const PX_PER_MIN = 11;
  const TOTAL_WIDTH = TOTAL_MIN * PX_PER_MIN;
  const WB_BLOCK_MIN = 13;             // nominal visual width for a world-boss block - kept under the 15min grid spacing so same-row blocks never overlap

  // All source data (boss spawns, meta-event offsets) is in UTC. The whole
  // timeline axis is rendered in the *viewer's local time* instead (so "now"
  // on the ruler matches their wall clock) - a fixed UTC->local shift (in
  // minutes) added once to every event's absolute position. The Server
  // (UTC) clock badge still shows the raw UTC time for reference.
  const LOCAL_OFFSET_MIN = -new Date().getTimezoneOffset();

  function fmt(min) {
    const h = Math.floor(((min % MIN_PER_DAY) + MIN_PER_DAY) % MIN_PER_DAY / 60);
    const m = ((min % 60) + 60) % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
  }

  // --- Ruler ---
  const ruler = document.getElementById("ruler");
  const inner = document.getElementById("timeline-inner");
  inner.style.width = TOTAL_WIDTH + "px";
  ruler.style.width = TOTAL_WIDTH + "px";
  for (let m = 0; m < TOTAL_MIN; m += 15) {
    const tick = document.createElement("div");
    tick.className = "tick" + (m % 60 === 0 ? " hour" : "");
    tick.style.left = m * PX_PER_MIN + "px";
    tick.textContent = fmt(m);
    ruler.appendChild(tick);
  }

  function makeBlock(track, startMin, endMin, html, extraClass) {
    const block = document.createElement("div");
    block.className = "boss-block" + (extraClass ? " " + extraClass : "");
    block.style.left = startMin * PX_PER_MIN + "px";
    block.style.width = Math.max(1, endMin - startMin) * PX_PER_MIN - 2 + "px";
    block.dataset.start = startMin;
    block.dataset.end = endMin;
    block.innerHTML = html;
    track.appendChild(block);
    return block;
  }

  // --- Copy-to-clipboard toast ---
  function flashCopied(block) {
    block.classList.add("copied");
    setTimeout(() => block.classList.remove("copied"), 1500);
  }

  // --- World bosses: one shared row, all bosses, real (irregular) spawn times + waypoint codes ---
  // Spawns from different bosses can land close together (e.g. Tequatl 23:55 -> Taidha 00:00,
  // a 5-minute gap), so block width is capped by the gap to the *next* spawn in the merged
  // timeline rather than a fixed width, to guarantee blocks in this row never overlap.
  const wbTrack = document.getElementById("track-worldbosses");
  wbTrack.style.width = TOTAL_WIDTH + "px";

  const wbEvents = [];
  for (let day = 0; day < 2; day++) {
    bosses.forEach((boss) => {
      boss.spawns.forEach((time) => {
        const [hh, mm] = time.split(":").map(Number);
        const startMin = hh * 60 + mm + LOCAL_OFFSET_MIN + day * MIN_PER_DAY;
        wbEvents.push({ boss, startMin });
      });
    });
  }
  wbEvents.sort((a, b) => a.startMin - b.startMin);

  wbEvents.forEach((e, i) => {
    const gapToNext = i + 1 < wbEvents.length ? wbEvents[i + 1].startMin - e.startMin : WB_BLOCK_MIN;
    const width = Math.max(2, Math.min(WB_BLOCK_MIN, gapToNext - 1));
    const boss = e.boss;
    const block = makeBlock(
      wbTrack, e.startMin, e.startMin + width,
      `<div class="inner"><div class="bname">${boss.name}</div><div class="btime">${fmt(e.startMin)} · <span class="tp-code">${boss.waypoint}</span></div></div>`
    );
    block.title = "Click to copy waypoint · " + boss.zone;
    block.addEventListener("click", () => {
      navigator.clipboard.writeText(boss.waypoint).catch(() => {});
      flashCopied(block);
    });
  });

  // --- Meta-event zones: one row per zone, expanding each zone's 2-hour cycle across the full 2-day window ---
  document.querySelectorAll(".track[data-category]").forEach((track) => {
    const cat = track.dataset.category;
    const zone = zonesByCategory[cat][Number(track.dataset.zone)];
    track.style.width = TOTAL_WIDTH + "px";
    for (let cycleStart = 0; cycleStart < TOTAL_MIN; cycleStart += zone.cycle_minutes) {
      zone.intervals.forEach((iv) => {
        const startMin = cycleStart + iv.start + LOCAL_OFFSET_MIN;
        const endMin = cycleStart + iv.end + LOCAL_OFFSET_MIN;
        makeBlock(
          track, startMin, endMin,
          `<div class="inner"><div class="bname">${iv.name}</div><div class="btime">${fmt(startMin)}</div></div>`
        );
      });
    }
  });

  // --- Live NOW line + clocks + past/soon styling ---
  const scrollEl = document.getElementById("timeline-scroll");
  const nowLine = document.getElementById("now-line");
  const clockUtc = document.getElementById("clock-utc");
  const clockLocal = document.getElementById("clock-local");

  function nowMinuteOfDay(now) {
    // Same flat UTC->local shift as every event above, so "now" lines up
    // with the shifted timeline instead of the raw UTC one.
    return now.getUTCHours() * 60 + now.getUTCMinutes() + now.getUTCSeconds() / 60 + LOCAL_OFFSET_MIN;
  }

  function render() {
    const now = new Date();
    const nowMin = nowMinuteOfDay(now);
    const nowPx = nowMin * PX_PER_MIN;

    nowLine.style.left = nowPx + "px";
    scrollEl.scrollLeft = Math.max(0, nowPx - scrollEl.clientWidth / 2);

    clockUtc.textContent = now.toISOString().slice(11, 19);
    clockLocal.textContent = now.toLocaleTimeString();

    document.querySelectorAll(".boss-block").forEach((block) => {
      const start = Number(block.dataset.start);
      const end = Number(block.dataset.end);
      block.classList.toggle("past", end <= nowMin);
      block.classList.toggle("soon", start > nowMin && start - nowMin <= 15);
    });
  }
  render();
  setInterval(render, 1000);

  // --- Category show/hide filters ---
  const filterBox = document.getElementById("cat-filters");
  const toggleAllBtn = document.getElementById("filter-toggle-all");

  function applyFilter(checkbox) {
    const group = document.querySelector('.category-group[data-cat-id="' + checkbox.dataset.target + '"]');
    if (group) group.classList.toggle("cat-hidden", !checkbox.checked);
  }

  filterBox.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    cb.addEventListener("change", () => applyFilter(cb));
  });

  toggleAllBtn.addEventListener("click", () => {
    const checkboxes = filterBox.querySelectorAll('input[type="checkbox"]');
    const anyChecked = Array.from(checkboxes).some((cb) => cb.checked);
    const nextState = !anyChecked; // "Select none" when some checked, else "Select all"
    checkboxes.forEach((cb) => {
      cb.checked = nextState;
      applyFilter(cb);
    });
    toggleAllBtn.textContent = nextState ? "Select none" : "Select all";
  });
})();
