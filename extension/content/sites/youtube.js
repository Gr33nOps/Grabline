// Grabline Connect — YouTube site module (F1.3, first slice).
//
// A hover ⬇ on video thumbnails (home, search, channels, sidebar, playlists,
// Shorts shelf) so a video can be grabbed without opening it. Clicking hands
// the *watch URL* to the desktop app, which pops its quality panel. The
// shared button (content/sites/button.js) keeps the ⬇ alive while YouTube's
// inline hover-preview player covers the thumbnail.
//
// DELIBERATELY ISOLATED: every selector lives in THUMBNAIL_ANCHORS below.
// When YouTube's DOM churns, this file is the whole blast radius — worst
// case the thumbnail button pauses while right-click and paste still work.

(() => {
  // Anchors that wrap a video thumbnail, oldest → newest YouTube layouts.
  const THUMBNAIL_ANCHORS = [
    "a#thumbnail[href*='/watch']",
    "a.yt-lockup-view-model-wiz__content-image[href*='/watch']",
    "a.yt-simple-endpoint[href^='/shorts/']",
    "a.reel-item-endpoint[href^='/shorts/']",
  ].join(", ");
  // The player on a watch/Shorts page gets the same button — the page URL is
  // the video URL there, and the quality panel beats a blind instant grab.
  const PLAYERS = "#movie_player, .html5-video-player";
  const MEDIA_PAGES = /^\/(watch|shorts\/|live\/)/;

  globalThis.grablineSiteButton({
    qualityPanel: true, // F1.3: pick a quality right in the page
    resolve(target) {
      const anchor = target.closest(THUMBNAIL_ANCHORS);
      const href = anchor?.getAttribute("href");
      if (href) return { anchor, url: new URL(href, location.origin).toString() };
      if (MEDIA_PAGES.test(location.pathname)) {
        const player = target.closest(PLAYERS);
        if (player) return { anchor: player, url: location.href };
      }
      return null;
    },
  });
})();
