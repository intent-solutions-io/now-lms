/* Show the sticky mobile "Request access" bar only after the hero call to action
   has scrolled out of view. The header already carries the same button, so the bar
   is a convenience for readers deep in the page, not a second button on first view. */
(function () {
    var bar = document.querySelector('.isl-mobile-action');
    var anchor = document.querySelector('.isl-hero .isl-cta-row');
    if (!bar || !anchor || !('IntersectionObserver' in window)) { return; }
    var io = new IntersectionObserver(function (entries) {
        var e = entries[0];
        var pastHero = !e.isIntersecting && e.boundingClientRect.bottom < 0;
        bar.classList.toggle('is-visible', pastHero);
    });
    io.observe(anchor);
})();
