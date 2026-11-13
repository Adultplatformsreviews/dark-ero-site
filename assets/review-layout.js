(function () {
  var links = [].slice.call(document.querySelectorAll(".rv-page .side-toc a"));
  if (!links.length) return;
  var items = links.map(function (link) {
    return { link: link, section: document.getElementById((link.getAttribute("href") || "").slice(1)) };
  }).filter(function (item) { return item.section; });
  if (!items.length) return;
  function mark() {
    var current = items[0].link;
    items.forEach(function (item) {
      if (item.section.getBoundingClientRect().top < 150) current = item.link;
    });
    items.forEach(function (item) { item.link.classList.toggle("is-active", item.link === current); });
  }
  mark();
  document.addEventListener("scroll", mark, { passive: true });
})();
