(function () {
  document.querySelectorAll(".ach-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.target);
      const isOpen = !target.hidden;
      target.hidden = isOpen;
      btn.textContent = (isOpen ? "▾ " : "▴ ") + btn.dataset.count + " sub-achievements";
    });
  });
})();
