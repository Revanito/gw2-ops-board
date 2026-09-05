(function () {
  document.querySelectorAll(".recipe-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = document.getElementById(btn.dataset.recipe);
      const isOpen = !row.hidden;
      row.hidden = isOpen;
      btn.classList.toggle("open", !isOpen);
      btn.textContent = isOpen ? "Recipe ▾" : "Recipe ▴";
    });
  });
})();
