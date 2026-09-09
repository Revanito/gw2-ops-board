(function () {
  const toggleBtn = document.getElementById("exchange-history-toggle");
  const panel = document.getElementById("exchange-history-panel");
  if (!toggleBtn || !panel) return;

  let loaded = false;

  function fmtAxisDate(ts) {
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: "numeric", day: "numeric" });
  }

  function fmtFullDate(ts) {
    return new Date(ts * 1000).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  // Same shape as the echo-watcher ping chart: a canvas drawn manually plus an
  // absolutely-positioned tooltip div that follows the mouse, snapped to the
  // nearest sample so hovering anywhere on the line shows its exact value.
  function setupChart(canvasId, tooltipId, points, getValue, formatValue, color) {
    const canvas = document.getElementById(canvasId);
    const tooltip = document.getElementById(tooltipId);
    const values = points.map(getValue);
    let geom = null;

    function draw() {
      const w = canvas.width = canvas.clientWidth;
      const h = canvas.height = 140;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, w, h);

      if (points.length < 2) {
        ctx.fillStyle = "#9aa1ad";
        ctx.font = "12px sans-serif";
        ctx.fillText("Not enough history yet - check back after a few refreshes.", 10, h / 2);
        geom = null;
        return;
      }

      const minV = Math.min(...values);
      const maxV = Math.max(...values);
      const span = maxV - minV || 1;
      const padL = 8, padR = 8, padT = 10, padB = 20;
      const plotW = w - padL - padR, plotH = h - padT - padB;
      const n = points.length;

      ctx.strokeStyle = "#262b35";
      for (let i = 0; i <= 2; i++) {
        const y = padT + (i / 2) * plotH;
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
      }

      ctx.fillStyle = "#9aa1ad"; ctx.font = "10px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(fmtAxisDate(points[0].ts), padL, h - 4);
      ctx.textAlign = "right";
      ctx.fillText(fmtAxisDate(points[n - 1].ts), w - padR, h - 4);
      ctx.textAlign = "left";

      ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath();
      points.forEach((p, i) => {
        const x = padL + (i / (n - 1)) * plotW;
        const y = padT + plotH - ((getValue(p) - minV) / span) * plotH;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();

      ctx.lineTo(padL + plotW, padT + plotH);
      ctx.lineTo(padL, padT + plotH);
      ctx.closePath();
      ctx.fillStyle = color + "1f";
      ctx.fill();

      geom = { padL, padT, plotW, plotH, minV, span, n };
    }

    function onMove(e) {
      if (!geom) return;
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const { padL, padT, plotW, plotH, minV, span, n } = geom;

      let i = Math.round(((mouseX - padL) / plotW) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      const p = points[i];
      const x = padL + (i / (n - 1)) * plotW;
      const y = padT + plotH - ((getValue(p) - minV) / span) * plotH;

      draw();
      const ctx = canvas.getContext("2d");
      ctx.strokeStyle = "rgba(230,232,236,0.35)"; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();

      tooltip.innerHTML = `<div class="t">${fmtFullDate(p.ts)}</div><div>${formatValue(getValue(p))}</div>`;
      tooltip.hidden = false;
      tooltip.style.top = y + "px";
      tooltip.style.left = x + "px";

      const wrapRect = canvas.parentElement.getBoundingClientRect();
      const tw = tooltip.offsetWidth;
      if (x - tw / 2 < 0) tooltip.style.left = (tw / 2) + "px";
      if (x + tw / 2 > wrapRect.width) tooltip.style.left = (wrapRect.width - tw / 2) + "px";
    }

    function onLeave() {
      tooltip.hidden = true;
      draw();
    }

    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    draw();
    window.addEventListener("resize", draw);
  }

  async function loadHistory() {
    try {
      const res = await fetch("/market/gem-exchange-history", { cache: "no-store" });
      const data = await res.json();
      const points = data.points;

      setupChart(
        "exchange-chart-gems", "exchange-tooltip-gems", points,
        (p) => p.sell_gems_for_coins / 10000,
        (v) => v.toFixed(2) + " gold",
        "#5eead4"
      );
      setupChart(
        "exchange-chart-gold", "exchange-tooltip-gold", points,
        (p) => p.sell_gold_for_gems,
        (v) => Math.round(v) + " gems",
        "#2dd4bf"
      );
    } catch (e) {
      panel.innerHTML = '<p class="dim">Couldn’t load exchange history.</p>';
    }
  }

  toggleBtn.addEventListener("click", async () => {
    const isOpen = !panel.hidden;
    panel.hidden = isOpen;
    toggleBtn.textContent = (isOpen ? "▾" : "▴") + " last 30 days";
    if (!isOpen && !loaded) {
      loaded = true;
      await loadHistory();
    }
  });
})();
