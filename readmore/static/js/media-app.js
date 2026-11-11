const STATUS_LABELS = {
  watchlist: "Watchlist",
  watching: "Watching",
  completed: "Completed",
  dropped: "Dropped",
};

const VIEW_CONTENT = {
  all: {
    title: "Alle Titel",
    emptyTitle: "Deine Sammlung ist noch leer.",
    emptyCopy: "Suche oben nach einem Film oder einer Serie und füge den Titel deiner Watchlist hinzu.",
  },
  watchlist: {
    title: "Watchlist",
    emptyTitle: "Deine Watchlist ist leer.",
    emptyCopy: "Speichere Filme und Serien, die du später ansehen möchtest.",
  },
  watching: {
    title: "Watching",
    emptyTitle: "Du schaust gerade nichts.",
    emptyCopy: "Verschiebe eine Serie oder einen Film auf Watching, sobald du beginnst.",
  },
  completed: {
    title: "Completed",
    emptyTitle: "Noch nichts abgeschlossen.",
    emptyCopy: "Fertige Filme und Serien erscheinen hier.",
  },
  dropped: {
    title: "Dropped",
    emptyTitle: "Keine abgebrochenen Titel.",
    emptyCopy: "Titel, die du nicht weiterschauen möchtest, kannst du hier sammeln.",
  },
};

const SORT_LABELS = {
  added_desc: "Zuletzt hinzugefügt",
  added_asc: "Zuerst hinzugefügt",
  title_asc: "Titel: A–Z",
  title_desc: "Titel: Z–A",
  rating_desc: "Bewertung: hoch",
  rating_asc: "Bewertung: niedrig",
};

const MEDIA_TYPE_LABELS = {
  all: "Alle Titel",
  movie: "Filme",
  tv: "Serien",
};

const THEME_COLORS = {
  red: "#101512",
  "blue-white": "#101512",
  green: "#101512",
  brown: "#101512",
  cozy: "#101512",
  light: "#f3f1eb",
};

const state = {
  media: [],
  seasons: [],
  searchResults: [],
  filter: "all",
  mediaType: "all",
  showSeasons: false,
  libraryMode: "all",
  movieCollectionIndex: new Map(),
  movieCollectionLoading: false,
  activeCollectionKey: null,
  expandedMissingCollectionKeys: new Set(),
  sort: "added_desc",
  searchLimit: 4,
  lastSearchQuery: "",
  pendingDelete: null,
  previewMedia: null,
  previewItem: null,
  previewSeason: null,
  ratingMedia: null,
  previewSeasonNumber: null,
};

const searchForm = document.querySelector("#search-form");
const searchInput = document.querySelector("#search-input");
const searchPanel = document.querySelector("#search-panel");
const searchResults = document.querySelector("#search-results");
const mediaGrid = document.querySelector("#media-grid");
const loadingState = document.querySelector("#library-loading");
const emptyState = document.querySelector("#empty-state");
const appearanceButton = document.querySelector("#appearance-button");
const appearanceMenu = document.querySelector("#appearance-menu");
const themeOptions = document.querySelectorAll("[data-theme-option]");
const settingsDialog = document.querySelector("#settings-dialog");
const settingsTheme = document.querySelector("#settings-theme");
const settingsSearchLimit = document.querySelector("#settings-search-limit");
const settingsStartView = document.querySelector("#settings-start-view");
const sortButton = document.querySelector("#sort-button");
const sortButtonLabel = document.querySelector("#sort-button-label");
const sortMenu = document.querySelector("#sort-menu");
const mediaTypeButton = document.querySelector("#media-type-button");
const mediaTypeButtonLabel = document.querySelector("#media-type-button-label");
const mediaTypeMenu = document.querySelector("#media-type-menu");
const collectionGroupingButton = document.querySelector("#collection-grouping-button");
const collectionGroupingButtonLabel = document.querySelector("#collection-grouping-button-label");
const seasonVisibilityButton = document.querySelector("#season-visibility-button");
const deleteDialog = document.querySelector("#delete-dialog");
const confirmDeleteButton = document.querySelector("#confirm-delete");
const previewDialog = document.querySelector("#media-preview-dialog");
const previewAddButton = document.querySelector("#media-preview-add");
const previewStatus = document.querySelector("#media-preview-status");
const previewRateButton = document.querySelector("#media-preview-rate");
const previewRemoveButton = document.querySelector("#media-preview-remove");
const mobileMediaLayout = window.matchMedia("(max-width: 680px)");
const seasonDialog = document.querySelector("#media-season-dialog");
const seasonDialogContent = document.querySelector("#media-season-dialog-content");
const libraryCollectionDialog = document.querySelector("#media-library-collection-dialog");
const libraryCollectionSavedList = document.querySelector("#media-library-collection-saved");
const libraryCollectionMissing = document.querySelector("#media-library-collection-missing");
const libraryCollectionMissingList = document.querySelector("#media-library-collection-missing-list");
const ratingDialog = document.querySelector("#media-rating-dialog");
const ratingForm = document.querySelector("#media-rating-form");
const reviewInput = document.querySelector("#media-review");
const searchCache = new Map();
const collectionCache = new Map();
const seriesCache = new Map();
const seasonCache = new Map();
const SEARCH_CACHE_TTL = 10 * 60 * 1000;
const COLLECTION_CACHE_TTL = 30 * 60 * 1000;
const SERIES_CACHE_TTL = 30 * 60 * 1000;
const titleCollator = new Intl.Collator("de", { sensitivity: "base", numeric: true });
let toastTimer;

async function api(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(url, { ...options, headers, credentials: "same-origin" });
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    throw new Error("Bitte melde dich erneut an.");
  }
  const payload = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload?.error || "Die Anfrage ist fehlgeschlagen.");
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function showToast(message, isError = false) {
  const toast = document.querySelector("#toast");
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3300);
}

function normalizeSearch(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLocaleLowerCase("de")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function mediaIdentity(media) {
  if (media.item_type === "season") {
    return `season:${media.tv_tmdb_id}:${media.season_number}`;
  }
  return `${media.media_type}:${media.tmdb_id}`;
}

function savedMedia(candidate) {
  const identity = mediaIdentity(candidate);
  return state.media.find((media) => mediaIdentity(media) === identity) || null;
}

function savedSeason(tvTmdbId, seasonNumber) {
  return state.seasons.find((season) => (
    Number(season.tv_tmdb_id) === Number(tvTmdbId)
    && Number(season.season_number) === Number(seasonNumber)
  )) || null;
}

function posterElement(media, { thumbnail = false, fallbackCover = null } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "book-cover-wrap media-poster-wrap";
  const sources = [];
  for (const poster of [media.cover_url, fallbackCover, media.series_cover_url]) {
    if (!poster) continue;
    if (thumbnail) {
      sources.push(poster.replace(/^https:\/\/image\.tmdb\.org\/t\/p\/(?:w500|w780|original)\//, "https://image.tmdb.org/t/p/w342/"));
    }
    sources.push(poster);
  }
  if (media.backdrop_url) sources.push(media.backdrop_url);
  const [source, ...fallbacks] = new Set(sources);
  if (!source) {
    wrap.append(posterPlaceholder(media.title));
    return wrap;
  }

  const image = document.createElement("img");
  image.className = "book-cover media-poster";
  image.alt = `Poster von ${media.title}`;
  image.loading = "lazy";
  image.addEventListener("error", () => {
    const next = fallbacks.shift();
    if (next) {
      image.src = next;
    } else {
      image.remove();
      wrap.append(posterPlaceholder(media.title));
    }
  });
  image.src = source;
  wrap.append(image);
  return wrap;
}

function posterPlaceholder(title) {
  const placeholder = document.createElement("div");
  placeholder.className = "book-placeholder";
  placeholder.setAttribute("role", "img");
  placeholder.setAttribute("aria-label", `Kein Poster für ${title}`);
  const mark = document.createElement("strong");
  mark.className = "book-placeholder-mark";
  mark.textContent = String(title || "?").trim().split(/\s+/).slice(0, 2)
    .map((word) => word[0]).join("").toLocaleUpperCase("de");
  const label = document.createElement("span");
  label.className = "book-placeholder-label";
  label.textContent = "Kein Poster";
  placeholder.append(mark, label);
  return placeholder;
}

function mediaTypeBadge(media) {
  const badge = document.createElement("span");
  badge.className = "media-type-badge";
  badge.textContent = media.item_type === "season"
    ? "Staffel"
    : media.media_type === "movie" ? "Film" : "Serie";
  return badge;
}

function mediaMeta(media) {
  const meta = document.createElement("div");
  meta.className = "book-meta";
  const title = document.createElement("h3");
  title.className = "book-title";
  title.textContent = media.item_type === "season" ? media.season_title : media.title;
  meta.append(mediaTypeBadge(media), title);
  if (media.item_type === "season") {
    const parent = document.createElement("p");
    parent.className = "season-parent-title";
    parent.textContent = media.series_title;
    meta.append(parent);
  }
  const details = [media.release_year, media.original_title ? `Original: ${media.original_title}` : null].filter(Boolean);
  if (media.item_type === "season" && media.episode_count) {
    details.push(`${media.episode_count} ${media.episode_count === 1 ? "Episode" : "Episoden"}`);
  }
  if (details.length) {
    const detailLine = document.createElement("p");
    detailLine.className = "book-year";
    detailLine.textContent = details.join(" · ");
    meta.append(detailLine);
  }
  const voteAverage = Number(media.vote_average);
  if (Number(media.vote_count) > 0 && Number.isFinite(voteAverage)) {
    const rating = document.createElement("p");
    rating.className = "media-rating";
    rating.textContent = `★ ${voteAverage.toFixed(1)}/10 · ${Number(media.vote_count).toLocaleString("de-DE")} Stimmen`;
    meta.append(rating);
  }
  return meta;
}

function mediaOverview(media) {
  const overview = document.createElement("p");
  overview.className = "media-overview";
  overview.textContent = media.overview || "Für diesen Titel ist noch keine deutsche Beschreibung verfügbar.";
  return overview;
}

function compactMediaCard(media, open, { type, detail = media.release_year, fallbackCover } = {}) {
  const article = document.createElement("article");
  article.className = "book-card compact-media-card";
  const poster = posterElement(media, { thumbnail: true, fallbackCover });
  poster.setAttribute("aria-hidden", "true");

  const copy = document.createElement("div");
  copy.className = "compact-media-copy";
  const badge = mediaTypeBadge(media);
  if (type) badge.textContent = type;
  const heading = document.createElement("h3");
  const trigger = document.createElement("button");
  trigger.className = "book-title-link compact-media-trigger";
  trigger.type = "button";
  trigger.setAttribute("aria-haspopup", "dialog");
  const title = document.createElement("span");
  title.textContent = media.title;
  trigger.append(title);
  trigger.addEventListener("click", open);
  heading.append(trigger);
  copy.append(badge, heading);

  const rating = Number(media.vote_average);
  const meta = document.createElement("p");
  meta.className = "compact-media-meta";
  if (detail) {
    const text = document.createElement("span");
    text.textContent = detail;
    meta.append(text);
  }
  if (Number(media.vote_count) > 0 && Number.isFinite(rating)) {
    const score = document.createElement("span");
    score.className = "compact-media-score";
    score.textContent = `★ ${rating.toFixed(1)}/10`;
    score.setAttribute("aria-label", `TMDB-Bewertung: ${rating.toFixed(1)} von 10`);
    meta.append(score);
  }
  if (meta.childElementCount) copy.append(meta);
  article.append(poster, copy);
  return article;
}

function personalRating(media) {
  const rating = Number(media.rating);
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) return null;
  const display = document.createElement("p");
  display.className = "media-personal-rating";
  display.setAttribute("aria-label", `Deine Bewertung: ${rating} von 5 Sternen`);
  display.textContent = `Deine Bewertung  ${"★".repeat(rating)}${"☆".repeat(5 - rating)}`;
  return display;
}

function statusSelect(media) {
  const select = document.createElement("select");
  select.className = "status-select";
  select.setAttribute("aria-label", `Status von ${media.title} ändern`);
  Object.entries(STATUS_LABELS).forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === media.status;
    select.append(option);
  });
  select.addEventListener("change", async () => {
    const previousStatus = media.status;
    select.disabled = true;
    try {
      const endpoint = media.item_type === "season"
        ? `/api/media/seasons/${media.id}`
        : `/api/media/${media.id}`;
      const payload = await api(endpoint, {
        method: "PATCH",
        body: JSON.stringify({ status: select.value }),
      });
      Object.assign(media, media.item_type === "season" ? payload.season : payload.media);
      renderLibrary();
      if (libraryCollectionDialog.open && state.activeCollectionKey) {
        renderLibraryCollectionDialog(state.activeCollectionKey);
      }
      if (!searchPanel.hidden) renderSearchResults();
      showToast(`„${media.title}“ ist jetzt unter „${STATUS_LABELS[media.status]}“.`);
    } catch (error) {
      select.value = previousStatus;
      showToast(`Status nicht geändert: ${error.message}`, true);
    } finally {
      select.disabled = false;
    }
  });
  return select;
}

function parentMediaForSeason(season) {
  return {
    provider: "tmdb",
    tmdb_id: season.tv_tmdb_id,
    media_type: "tv",
    title: season.series_title,
    overview: season.series_overview,
    release_year: season.release_year,
    original_language: season.original_language,
    cover_url: season.series_cover_url || season.cover_url,
    backdrop_url: season.backdrop_url,
    vote_average: null,
    vote_count: 0,
  };
}

function seasonLibraryCard(season) {
  if (usesMobileMediaLayout()) {
    return compactMediaCard(season, () => openMediaPreview(season, true, season.season_number));
  }
  const article = document.createElement("article");
  article.className = "book-card media-library-card season-library-card";
  const poster = posterElement(season);
  poster.classList.add("media-info-trigger");
  poster.tabIndex = 0;
  poster.setAttribute("role", "button");
  poster.setAttribute("aria-label", `${season.title} öffnen`);
  const open = () => openMediaPreview(parentMediaForSeason(season), true, season.season_number);
  poster.addEventListener("click", open);
  poster.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    open();
  });
  article.append(poster);
  const info = document.createElement("button");
  info.className = "icon-button media-info-button";
  info.type = "button";
  info.textContent = document.documentElement.dataset.bookInfoSymbol || "!";
  info.setAttribute("aria-label", `${season.title} öffnen`);
  info.addEventListener("click", open);
  article.append(info);
  const body = document.createElement("div");
  body.className = "book-body";
  body.append(mediaMeta(season), mediaOverview(season));
  const actions = document.createElement("div");
  actions.className = "media-library-actions";
  actions.append(statusSelect(season));
  const remove = document.createElement("button");
  remove.className = "icon-button remove-book-button";
  remove.type = "button";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `${season.title} aus der Sammlung entfernen`);
  remove.addEventListener("click", () => openDeleteDialog(season));
  actions.append(remove);
  body.append(actions);
  article.append(body);
  return article;
}

function searchCard(media) {
  if (usesMobileMediaLayout()) {
    return compactMediaCard(media, () => openMediaPreview(media));
  }
  const article = document.createElement("article");
  article.className = "book-card search-card media-search-card";
  article.dataset.tmdbId = String(media.tmdb_id);
  article.dataset.mediaType = media.media_type;
  article.append(posterElement(media));
  const body = document.createElement("div");
  body.className = "book-body";
  body.append(mediaMeta(media), mediaOverview(media));
  const actions = document.createElement("div");
  actions.className = "media-search-actions";
  const preview = document.createElement("button");
  preview.className = "button button-secondary";
  preview.type = "button";
  preview.textContent = "Vorschau";
  preview.addEventListener("click", () => openMediaPreview(media));
  actions.append(preview);
  const saved = savedMedia(media);
  if (saved) {
    const added = document.createElement("div");
    added.className = "added-label";
    added.textContent = `✓ ${STATUS_LABELS[saved.status]}`;
    actions.append(added);
  } else {
    const add = document.createElement("button");
    add.className = "button button-primary";
    add.type = "button";
    add.textContent = "＋ Watchlist";
    add.addEventListener("click", () => addToWatchlist(media, add));
    actions.append(add);
  }
  body.append(actions);
  article.append(body);
  return article;
}

function libraryCard(media) {
  if (media.item_type === "season") return seasonLibraryCard(media);
  if (usesMobileMediaLayout()) {
    return compactMediaCard(media, () => openMediaPreview(media, true));
  }
  const article = document.createElement("article");
  article.className = "book-card media-library-card";
  const poster = posterElement(media);
  poster.classList.add("media-info-trigger");
  poster.tabIndex = 0;
  poster.setAttribute("role", "button");
  poster.setAttribute("aria-label", `Informationen zu ${media.title}`);
  poster.addEventListener("click", () => openMediaPreview(media, true));
  poster.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openMediaPreview(media, true);
  });
  article.append(poster);
  const info = document.createElement("button");
  info.className = "icon-button media-info-button";
  info.type = "button";
  info.textContent = document.documentElement.dataset.bookInfoSymbol || "!";
  info.setAttribute("aria-label", `Informationen zu ${media.title}`);
  info.title = "Informationen anzeigen";
  info.addEventListener("click", () => openMediaPreview(media, true));
  article.append(info);
  const body = document.createElement("div");
  body.className = "book-body";
  body.append(mediaMeta(media), mediaOverview(media));
  const rating = personalRating(media);
  if (rating) body.append(rating);
  if (media.review) {
    const review = document.createElement("p");
    review.className = "media-review-excerpt";
    review.textContent = media.review;
    body.append(review);
  }
  const actions = document.createElement("div");
  actions.className = "media-library-actions";
  actions.append(statusSelect(media));
  const rate = document.createElement("button");
  rate.className = "icon-button media-rate-button";
  rate.type = "button";
  rate.textContent = media.rating ? "★" : "☆";
  rate.classList.toggle("rated", Boolean(media.rating));
  rate.setAttribute("aria-label", `${media.title} bewerten`);
  rate.title = media.rating || media.review ? "Bewertung bearbeiten" : "Titel bewerten";
  rate.addEventListener("click", () => openRatingDialog(media));
  actions.append(rate);
  const remove = document.createElement("button");
  remove.className = "icon-button remove-book-button";
  remove.type = "button";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `${media.title} aus der Sammlung entfernen`);
  remove.addEventListener("click", () => openDeleteDialog(media));
  actions.append(remove);
  body.append(actions);
  article.append(body);
  return article;
}

function movieCollectionFor(media) {
  if (!media || media.media_type !== "movie") return null;
  return state.movieCollectionIndex.get(media.id) || null;
}

function movieCollectionKey(media) {
  const collection = movieCollectionFor(media);
  return collection?.tmdb_id ? String(collection.tmdb_id) : null;
}

function movieCollectionCard(collection, movies) {
  const collectionKey = String(collection.tmdb_id);
  const open = () => openLibraryCollectionDialog(collectionKey);
  const savedCount = collection.parts.filter((part) => savedMedia(part)).length;
  const countLabel = `${savedCount} von ${collection.parts.length} gespeichert`;
  if (usesMobileMediaLayout()) {
    return compactMediaCard({
      ...collection,
      title: collection.name,
    }, open, {
      type: "Filmreihe",
      detail: countLabel,
      fallbackCover: movies.find((movie) => movie.cover_url)?.cover_url,
    });
  }
  const article = document.createElement("article");
  article.className = "book-card media-library-card movie-collection-card series-collection-card";

  const cover = document.createElement("div");
  cover.className = "book-cover-wrap series-cover-stack media-info-trigger";
  cover.tabIndex = 0;
  cover.setAttribute("role", "button");
  cover.setAttribute("aria-label", `${collection.name} öffnen`);
  const coveredMovies = movies.filter((movie) => movie.cover_url).slice(0, 3);
  if (coveredMovies.length) {
    coveredMovies.forEach((movie) => {
      const image = document.createElement("img");
      image.className = "series-stack-cover";
      image.src = movie.cover_url;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => image.remove(), { once: true });
      cover.append(image);
    });
  } else {
    cover.append(posterPlaceholder(collection.name));
  }
  const badge = document.createElement("span");
  badge.className = "series-collection-badge";
  badge.textContent = "Filmreihe";
  cover.append(badge);

  cover.addEventListener("click", open);
  cover.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    open();
  });

  const body = document.createElement("div");
  body.className = "book-body";
  const meta = document.createElement("div");
  meta.className = "book-meta";
  const title = document.createElement("h3");
  title.className = "book-title";
  const titleButton = document.createElement("button");
  titleButton.className = "book-title-link";
  titleButton.type = "button";
  titleButton.textContent = collection.name;
  titleButton.addEventListener("click", open);
  title.append(titleButton);
  const count = document.createElement("p");
  count.className = "book-author";
  count.textContent = countLabel;
  const titles = document.createElement("p");
  titles.className = "series-title-preview";
  const scope = state.filter === "all" ? "in deiner Sammlung" : `unter ${STATUS_LABELS[state.filter]}`;
  titles.textContent = `${movies.length} ${movies.length === 1 ? "Film" : "Filme"} ${scope}`;
  meta.append(title, count, titles);
  const button = document.createElement("button");
  button.className = "button button-secondary";
  button.type = "button";
  button.textContent = "Filmreihe öffnen";
  button.addEventListener("click", open);
  body.append(meta, button);
  article.append(cover, body);
  return article;
}

function collectionMovieRow(movie) {
  const row = document.createElement("div");
  row.className = "media-library-collection-row";
  const poster = posterElement(movie);
  poster.classList.add("media-library-collection-poster", "media-info-trigger");
  poster.tabIndex = 0;
  poster.setAttribute("role", "button");
  poster.setAttribute("aria-label", `Informationen zu ${movie.title}`);
  const openInfo = () => {
    libraryCollectionDialog.close();
    openMediaPreview(movie, true);
  };
  poster.addEventListener("click", openInfo);
  poster.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openInfo();
  });

  const copy = document.createElement("div");
  copy.className = "media-library-collection-copy";
  const title = document.createElement("strong");
  title.textContent = movie.title;
  const details = document.createElement("span");
  details.textContent = [movie.release_year, movie.rating ? `Deine Wertung: ${movie.rating}/5` : null]
    .filter(Boolean).join(" · ") || "Film";
  copy.append(title, details);

  const actions = document.createElement("div");
  actions.className = "media-library-collection-actions";
  actions.append(statusSelect(movie));
  const rate = document.createElement("button");
  rate.className = "icon-button media-rate-button";
  rate.classList.toggle("rated", Boolean(movie.rating));
  rate.type = "button";
  rate.textContent = movie.rating ? "★" : "☆";
  rate.setAttribute("aria-label", `${movie.title} bewerten`);
  rate.addEventListener("click", () => {
    libraryCollectionDialog.close();
    openRatingDialog(movie);
  });
  const info = document.createElement("button");
  info.className = "icon-button";
  info.type = "button";
  info.textContent = document.documentElement.dataset.bookInfoSymbol || "!";
  info.setAttribute("aria-label", `Informationen zu ${movie.title}`);
  info.addEventListener("click", openInfo);
  const remove = document.createElement("button");
  remove.className = "icon-button remove-book-button";
  remove.type = "button";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `${movie.title} aus der Sammlung entfernen`);
  remove.addEventListener("click", () => {
    libraryCollectionDialog.close();
    openDeleteDialog(movie);
  });
  actions.append(rate, info, remove);
  row.append(poster, copy, actions);
  return row;
}

function collectionPartRow(part) {
  const saved = savedMedia(part);
  if (saved) return collectionMovieRow(saved);

  const row = document.createElement("div");
  row.className = "media-library-collection-row unsaved";
  const poster = posterElement(part);
  poster.classList.add("media-library-collection-poster", "media-info-trigger");
  poster.tabIndex = 0;
  poster.setAttribute("role", "button");
  poster.setAttribute("aria-label", `Informationen zu ${part.title}`);
  const openInfo = () => {
    libraryCollectionDialog.close();
    openMediaPreview(part);
  };
  poster.addEventListener("click", openInfo);
  poster.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openInfo();
  });

  const copy = document.createElement("div");
  copy.className = "media-library-collection-copy";
  const title = document.createElement("strong");
  title.textContent = part.title;
  const details = document.createElement("span");
  details.textContent = [
    part.collection_position ? `Film ${part.collection_position}` : null,
    part.release_year || "Jahr unbekannt",
    "Noch nicht gespeichert",
  ].filter(Boolean).join(" · ");
  copy.append(title, details);

  const actions = document.createElement("div");
  actions.className = "media-library-collection-actions unsaved-actions";
  const add = document.createElement("button");
  add.className = "button button-primary media-collection-add";
  add.type = "button";
  add.textContent = "＋ Watchlist";
  add.addEventListener("click", async () => {
    await addToWatchlist(part, add);
    if (libraryCollectionDialog.open && state.activeCollectionKey) {
      renderLibraryCollectionDialog(state.activeCollectionKey);
    }
  });
  const info = document.createElement("button");
  info.className = "icon-button";
  info.type = "button";
  info.textContent = document.documentElement.dataset.bookInfoSymbol || "!";
  info.setAttribute("aria-label", `Informationen zu ${part.title}`);
  info.addEventListener("click", openInfo);
  actions.append(add, info);
  row.append(poster, copy, actions);
  return row;
}

function movieCollectionByKey(collectionKey) {
  for (const collection of state.movieCollectionIndex.values()) {
    if (collection?.tmdb_id && String(collection.tmdb_id) === collectionKey) return collection;
  }
  return null;
}

function renderLibraryCollectionDialog(collectionKey) {
  const collection = movieCollectionByKey(collectionKey);
  if (!collection) {
    if (libraryCollectionDialog.open) libraryCollectionDialog.close();
    return;
  }
  const saved = [];
  const missing = [];
  collection.parts.forEach((part) => {
    const stored = savedMedia(part);
    if (stored) saved.push(stored);
    else missing.push(part);
  });
  document.querySelector("#media-library-collection-title").textContent = collection.name;
  document.querySelector("#media-library-collection-count").textContent = `${saved.length} von ${collection.parts.length} gespeichert`;
  libraryCollectionSavedList.replaceChildren(...saved.map(collectionMovieRow));
  document.querySelector("#media-library-collection-missing-label").textContent = missing.length === 1
    ? "1 Film noch nicht gespeichert"
    : `${missing.length} Filme noch nicht gespeichert`;
  libraryCollectionMissing.hidden = missing.length === 0;
  libraryCollectionMissing.open = missing.length > 0
    && state.expandedMissingCollectionKeys.has(collectionKey);
  libraryCollectionMissingList.replaceChildren(...missing.map(collectionPartRow));
}

function openLibraryCollectionDialog(collectionKey) {
  state.activeCollectionKey = collectionKey;
  renderLibraryCollectionDialog(collectionKey);
  if (!libraryCollectionDialog.open) libraryCollectionDialog.showModal();
}

function renderSearchResults() {
  searchResults.replaceChildren();
  if (!state.searchResults.length) {
    const message = document.createElement("div");
    message.className = "empty-state";
    const heading = document.createElement("h3");
    heading.textContent = "Keine passenden Filme oder Serien gefunden";
    const copy = document.createElement("p");
    copy.textContent = "TMDB hat für diesen Suchbegriff keine passenden Titel geliefert.";
    const retry = document.createElement("button");
    retry.className = "button button-secondary";
    retry.type = "button";
    retry.textContent = "Noch einmal suchen";
    retry.addEventListener("click", () => executeSearch(state.lastSearchQuery));
    message.append(heading, copy, retry);
    searchResults.append(message);
    return;
  }
  state.searchResults.forEach((media) => searchResults.append(searchCard(media)));
}

function filteredAndSortedMedia() {
  const collectionItems = [
    ...state.media,
    ...(state.showSeasons && state.mediaType !== "movie" ? state.seasons : []),
  ];
  let filtered = state.filter === "all"
    ? collectionItems
    : collectionItems.filter((media) => media.status === state.filter);
  if (state.mediaType !== "all") {
    filtered = filtered.filter((media) => media.media_type === state.mediaType);
  }
  return filtered.sort((left, right) => {
    if (state.sort === "rating_desc" || state.sort === "rating_asc") {
      const leftRating = Number(left.rating) || 0;
      const rightRating = Number(right.rating) || 0;
      const difference = state.sort === "rating_desc"
        ? rightRating - leftRating
        : leftRating - rightRating;
      if (difference) return difference;
    }
    if (state.sort === "title_asc") return titleCollator.compare(left.title, right.title);
    if (state.sort === "title_desc") return titleCollator.compare(right.title, left.title);
    const order = String(left.created_at).localeCompare(String(right.created_at)) || left.id - right.id;
    return state.sort === "added_asc" ? order : -order;
  });
}

function renderGroupedLibrary(visible) {
  const groupedMovies = new Map();
  visible.forEach((media) => {
    const collectionKey = movieCollectionKey(media);
    if (!collectionKey) return;
    if (!groupedMovies.has(collectionKey)) groupedMovies.set(collectionKey, []);
    groupedMovies.get(collectionKey).push(media);
  });

  const renderedCollections = new Set();
  visible.forEach((media) => {
    const collectionKey = movieCollectionKey(media);
    if (!collectionKey) {
      mediaGrid.append(libraryCard(media));
      return;
    }
    if (renderedCollections.has(collectionKey)) return;
    renderedCollections.add(collectionKey);
    mediaGrid.append(movieCollectionCard(movieCollectionFor(media), groupedMovies.get(collectionKey)));
  });
  return renderedCollections.size;
}

async function ensureMovieCollectionIndex(movies) {
  if (state.movieCollectionLoading) return;
  const savedByTmdbId = new Map(
    state.media.filter((media) => media.media_type === "movie")
      .map((media) => [Number(media.tmdb_id), media]),
  );
  const knownCollections = new Map();
  state.movieCollectionIndex.forEach((collection) => {
    if (collection?.tmdb_id) knownCollections.set(String(collection.tmdb_id), collection);
  });
  knownCollections.forEach((collection) => {
    collection.parts.forEach((part) => {
      const stored = savedByTmdbId.get(Number(part.tmdb_id));
      if (stored) state.movieCollectionIndex.set(stored.id, collection);
    });
  });
  const unresolved = movies.filter((movie) => (
    movie.media_type === "movie" && !state.movieCollectionIndex.has(movie.id)
  ));
  if (!unresolved.length) return;
  state.movieCollectionLoading = true;
  let cursor = 0;
  const failedMovies = [];

  async function worker() {
    while (cursor < unresolved.length) {
      const movie = unresolved[cursor];
      cursor += 1;
      if (state.movieCollectionIndex.has(movie.id)) continue;
      try {
        const payload = await api(`/api/media/${movie.id}/collection`);
        const collection = payload.collection || null;
        state.movieCollectionIndex.set(movie.id, collection);
        collectionCache.set(mediaIdentity(movie), { collection, savedAt: Date.now() });
        if (!collection) continue;
        collection.parts.forEach((part) => {
          const stored = savedByTmdbId.get(Number(part.tmdb_id));
          if (!stored) return;
          state.movieCollectionIndex.set(stored.id, collection);
          collectionCache.set(mediaIdentity(stored), { collection, savedAt: Date.now() });
        });
      } catch (_error) {
        failedMovies.push(movie);
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(3, unresolved.length) }, () => worker()));
  state.movieCollectionLoading = false;
  const failures = failedMovies.filter((movie) => !state.movieCollectionIndex.has(movie.id)).length;
  if (failures) {
    showToast(`${failures} ${failures === 1 ? "Filmreihe konnte" : "Filmreihen konnten"} gerade nicht abgefragt werden.`, true);
  }
}

async function setCollectionGrouping(grouped) {
  state.libraryMode = grouped ? "collections" : "all";
  collectionGroupingButton.setAttribute("aria-pressed", String(grouped));
  if (!grouped) {
    collectionGroupingButton.disabled = false;
    collectionGroupingButtonLabel.textContent = "Filmreihen gruppieren";
    renderLibrary();
    return;
  }
  collectionGroupingButton.disabled = true;
  collectionGroupingButtonLabel.textContent = "Filmreihen werden geladen …";
  await ensureMovieCollectionIndex(state.media);
  collectionGroupingButton.disabled = false;
  collectionGroupingButtonLabel.textContent = "Filme einzeln anzeigen";
  renderLibrary();
}

function savedPreviewItem() {
  const item = state.previewItem;
  if (!item) return null;
  return item.item_type === "season"
    ? savedSeason(item.tv_tmdb_id, item.season_number)
    : savedMedia(item);
}

function renderPreviewActions() {
  const saved = savedPreviewItem();
  previewAddButton.hidden = Boolean(saved);
  previewAddButton.disabled = false;
  previewAddButton.textContent = "＋ Watchlist";
  previewStatus.hidden = !saved;
  previewStatus.replaceChildren(...(saved ? [statusSelect(saved)] : []));
  previewRateButton.hidden = !saved || saved.item_type === "season";
  previewRateButton.textContent = saved?.rating ? `★ ${saved.rating}/5` : "Bewerten";
  previewRateButton.classList.toggle("rated", Boolean(saved?.rating));
  previewRateButton.setAttribute("aria-label", saved?.rating || saved?.review ? "Bewertung bearbeiten" : "Bewerten");
  previewRemoveButton.hidden = !saved;
}

function openMediaPreview(media, infoOnly = false, seasonNumber = null) {
  const isSeason = media.item_type === "season";
  const source = isSeason ? parentMediaForSeason(media) : media;
  state.previewItem = media;
  state.previewMedia = source;
  state.previewSeasonNumber = seasonNumber;
  document.querySelector(".media-preview-close").setAttribute(
    "aria-label",
    infoOnly ? "Infoansicht schließen" : "Vorschau schließen",
  );
  const backdrop = document.querySelector("#media-preview-backdrop");
  backdrop.style.backgroundImage = media.backdrop_url ? `url("${media.backdrop_url}")` : "none";
  backdrop.classList.toggle("has-image", Boolean(media.backdrop_url));
  const poster = document.querySelector("#media-preview-poster");
  poster.replaceChildren(posterElement(media));
  document.querySelector("#media-preview-type").textContent = mediaTypeBadge(media).textContent;
  document.querySelector("#media-preview-title").textContent = media.title;
  const meta = [
    media.release_year,
    media.original_language ? String(media.original_language).toUpperCase() : null,
    media.original_title && media.original_title !== media.title ? `Original: ${media.original_title}` : null,
  ].filter(Boolean);
  document.querySelector("#media-preview-meta").textContent = meta.join(" · ");
  const publicRating = document.querySelector("#media-preview-rating");
  publicRating.hidden = isSeason;
  const voteAverage = Number(media.vote_average);
  publicRating.textContent = Number(media.vote_count) > 0 && Number.isFinite(voteAverage)
    ? `TMDB ★ ${voteAverage.toFixed(1)}/10 · ${Number(media.vote_count).toLocaleString("de-DE")} Stimmen`
    : "Noch keine TMDB-Wertung";
  document.querySelector("#media-preview-overview").textContent = media.overview
    || "Für diesen Titel ist noch keine deutsche Beschreibung verfügbar.";
  document.querySelector("#media-preview-description").open = false;
  renderPreviewActions();
  const collectionSection = document.querySelector("#media-collection-section");
  collectionSection.hidden = true;
  document.querySelector("#media-collection-list").replaceChildren();
  const seriesSection = document.querySelector("#media-series-section");
  seriesSection.hidden = true;
  document.querySelector("#media-season-tabs").replaceChildren();
  const episodesPanel = document.querySelector("#media-episodes-panel");
  episodesPanel.hidden = true;
  episodesPanel.removeAttribute("data-request-key");
  document.querySelector("#media-episodes-list").replaceChildren();
  if (!previewDialog.open) previewDialog.showModal();
  previewDialog.scrollTop = 0;
  if (source.media_type === "movie") loadMovieCollection(source);
  if (source.media_type === "tv") loadSeriesSeasons(source);
}

function collectionPartCard(part, currentMedia) {
  const article = document.createElement("article");
  article.className = "media-collection-part";
  article.classList.toggle("current", Number(part.tmdb_id) === Number(currentMedia.tmdb_id));
  if (part.cover_url) {
    const poster = document.createElement("img");
    poster.src = part.cover_url;
    poster.alt = `Poster von ${part.title}`;
    poster.loading = "lazy";
    article.append(poster);
  } else {
    const placeholder = posterPlaceholder(part.title);
    placeholder.classList.add("media-collection-placeholder");
    article.append(placeholder);
  }
  const copy = document.createElement("div");
  copy.className = "media-collection-part-copy";
  const position = document.createElement("span");
  position.className = "media-collection-position";
  position.textContent = `Film ${part.collection_position}`;
  const title = document.createElement("h4");
  title.textContent = part.title;
  const meta = document.createElement("p");
  meta.textContent = part.release_year || "Jahr unbekannt";
  copy.append(position, title, meta);
  const saved = savedMedia(part);
  if (Number(part.tmdb_id) === Number(currentMedia.tmdb_id)) {
    const current = document.createElement("span");
    current.className = "media-collection-state";
    current.textContent = "Aktueller Film";
    copy.append(current);
  } else if (saved) {
    const stored = document.createElement("span");
    stored.className = "media-collection-state";
    stored.textContent = `✓ ${STATUS_LABELS[saved.status]}`;
    copy.append(stored);
  } else {
    const add = document.createElement("button");
    add.className = "button button-secondary media-collection-add";
    add.type = "button";
    add.textContent = "＋ Watchlist";
    add.addEventListener("click", async () => {
      await addToWatchlist(part, add);
      renderMovieCollection(state.previewMedia?.collection, currentMedia);
    });
    copy.append(add);
  }
  article.append(copy);
  return article;
}

function renderMovieCollection(collection, currentMedia) {
  const section = document.querySelector("#media-collection-section");
  const status = document.querySelector("#media-collection-status");
  const list = document.querySelector("#media-collection-list");
  list.replaceChildren();
  section.hidden = false;
  if (!collection) {
    document.querySelector("#media-collection-title").textContent = "Keine Filmreihe";
    document.querySelector("#media-collection-count").textContent = "";
    status.textContent = "TMDB ordnet diesen Film aktuell keiner Filmreihe zu.";
    return;
  }
  state.previewMedia.collection = collection;
  document.querySelector("#media-collection-title").textContent = collection.name;
  document.querySelector("#media-collection-count").textContent = `${collection.parts.length} Teile`;
  status.textContent = collection.overview || "Alle bei TMDB hinterlegten Filme dieser Reihe.";
  collection.parts.forEach((part) => list.append(collectionPartCard(part, currentMedia)));
}

async function loadMovieCollection(media) {
  const section = document.querySelector("#media-collection-section");
  const status = document.querySelector("#media-collection-status");
  section.hidden = false;
  document.querySelector("#media-collection-title").textContent = "Filmreihe wird geladen …";
  document.querySelector("#media-collection-count").textContent = "";
  status.textContent = "TMDB wird nach weiteren Teilen durchsucht.";
  const identity = mediaIdentity(media);
  const cached = collectionCache.get(identity);
  if (cached && Date.now() - cached.savedAt < COLLECTION_CACHE_TTL) {
    renderMovieCollection(cached.collection, media);
    return;
  }
  try {
    const stored = savedMedia(media);
    const endpoint = stored
      ? `/api/media/${stored.id}/collection`
      : `/api/media/movie/${media.tmdb_id}/collection`;
    const payload = await api(endpoint);
    if (!previewDialog.open || mediaIdentity(state.previewMedia) !== identity) return;
    collectionCache.set(identity, { collection: payload.collection, savedAt: Date.now() });
    renderMovieCollection(payload.collection, media);
  } catch (error) {
    if (!previewDialog.open || mediaIdentity(state.previewMedia) !== identity) return;
    document.querySelector("#media-collection-title").textContent = "Filmreihe nicht verfügbar";
    document.querySelector("#media-collection-count").textContent = "";
    status.textContent = error.message;
  }
}

function episodeRatingControl(episode, media, seasonNumber) {
  const control = document.createElement("div");
  control.className = "episode-rating";
  const label = document.createElement("span");
  label.className = "episode-rating-label";
  label.textContent = "Deine Wertung:";
  control.append(label);

  const save = async (rating) => {
    control.classList.add("episode-rating-saving");
    try {
      const payload = await api(
        `/api/media/tv/${media.tmdb_id}/seasons/${seasonNumber}/episodes/${episode.episode_number}/rating`,
        { method: "PATCH", body: JSON.stringify({ rating }) },
      );
      episode.user_rating = payload.rating;
      control.replaceWith(episodeRatingControl(episode, media, seasonNumber));
      showToast(payload.rating ? `${payload.rating} Sterne gespeichert.` : "Episodenbewertung entfernt.");
    } catch (error) {
      control.classList.remove("episode-rating-saving");
      showToast(error.message, true);
    }
  };

  for (let rating = 1; rating <= 5; rating += 1) {
    const star = document.createElement("button");
    star.className = "episode-rating-star";
    star.classList.toggle("selected", Number(episode.user_rating) >= rating);
    star.type = "button";
    star.textContent = "★";
    star.title = `${rating} ${rating === 1 ? "Stern" : "Sterne"}`;
    star.setAttribute("aria-label", `${episode.name} mit ${rating} ${rating === 1 ? "Stern" : "Sternen"} bewerten`);
    star.setAttribute("aria-pressed", String(Number(episode.user_rating) === rating));
    star.addEventListener("click", () => save(rating));
    control.append(star);
  }
  if (episode.user_rating) {
    const clear = document.createElement("button");
    clear.className = "text-button episode-rating-clear";
    clear.type = "button";
    clear.textContent = "Entfernen";
    clear.addEventListener("click", () => save(null));
    control.append(clear);
  }
  return control;
}

function episodeCard(episode, media, seasonNumber) {
  const article = document.createElement("article");
  article.className = "media-episode";
  if (episode.still_url) {
    const still = document.createElement("img");
    still.className = "media-episode-still";
    still.src = episode.still_url;
    still.alt = "";
    still.loading = "lazy";
    article.append(still);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "media-episode-placeholder";
    placeholder.textContent = `S${seasonNumber}E${episode.episode_number}`;
    article.append(placeholder);
  }
  const copy = document.createElement("div");
  copy.className = "media-episode-copy";
  const heading = document.createElement("div");
  heading.className = "media-episode-heading";
  const title = document.createElement("h5");
  title.textContent = episode.name;
  const number = document.createElement("span");
  number.textContent = `S${String(seasonNumber).padStart(2, "0")}E${String(episode.episode_number).padStart(2, "0")}`;
  heading.append(title, number);
  const meta = document.createElement("p");
  meta.className = "media-episode-meta";
  const metaParts = [episode.air_date, episode.runtime ? `${episode.runtime} Min.` : null].filter(Boolean);
  meta.textContent = metaParts.join(" · ") || "Keine Ausstrahlungsdaten";
  copy.append(heading, meta);
  if (episode.overview) {
    const overview = document.createElement("p");
    overview.className = "media-episode-overview";
    overview.textContent = episode.overview;
    copy.append(overview);
  }
  copy.append(episodeRatingControl(episode, media, seasonNumber));
  article.append(copy);
  return article;
}

function usesMobileMediaLayout() {
  return document.documentElement.classList.contains("platform-mobile")
    || mobileMediaLayout.matches;
}

function activateSeasonTab(tabs, activeTab) {
  tabs.querySelectorAll(".media-season-tab").forEach((candidate) => {
    const selected = candidate === activeTab;
    candidate.classList.toggle("active", selected);
    candidate.setAttribute("aria-selected", String(selected));
  });
}

function restoreEpisodesPanel() {
  const panel = document.querySelector("#media-episodes-panel");
  const section = document.querySelector("#media-series-section");
  panel.hidden = true;
  panel.removeAttribute("data-request-key");
  if (panel.parentElement !== section) section.append(panel);
}

function renderMobileSeasonHeader(media, season) {
  const title = season.name || `Staffel ${season.season_number}`;
  const poster = {
    ...season,
    title,
    cover_url: season.cover_url || media.cover_url,
  };
  document.querySelector("#media-season-dialog-poster").replaceChildren(posterElement(poster));
  document.querySelector("#media-season-dialog-series").textContent = media.title;
  document.querySelector("#media-season-dialog-title").textContent = title;
  const episodeCount = Number(season.episode_count || season.episodes?.length || 0);
  const year = String(season.air_date || "").slice(0, 4);
  document.querySelector("#media-season-dialog-meta").textContent = [
    year || null,
    episodeCount ? `${episodeCount} ${episodeCount === 1 ? "Episode" : "Episoden"}` : null,
  ].filter(Boolean).join(" · ");
  document.querySelector("#media-season-dialog-overview").textContent = season.overview
    || "Für diese Staffel ist noch keine Beschreibung verfügbar.";
}

function openMobileSeasonDialog(media, season) {
  state.previewSeason = season;
  renderMobileSeasonHeader(media, season);
  document.querySelector("#media-season-dialog-description").open = false;
  const panel = document.querySelector("#media-episodes-panel");
  seasonDialogContent.append(panel);
  if (!seasonDialog.open) seasonDialog.showModal();
  seasonDialog.scrollTop = 0;
  loadSeasonEpisodes(media, season);
}

function renderSeasonEpisodes(season, media) {
  const panel = document.querySelector("#media-episodes-panel");
  const list = document.querySelector("#media-episodes-list");
  panel.hidden = false;
  document.querySelector("#media-episodes-title").textContent = seasonDialog.open
    ? "Episoden"
    : (season.name || `Staffel ${season.season_number}`);
  document.querySelector("#media-episodes-count").textContent = `${season.episodes.length} ${season.episodes.length === 1 ? "Episode" : "Episoden"}`;
  document.querySelector("#media-episodes-status").textContent = season.overview || "Wähle Sterne, um einzelne Episoden persönlich zu bewerten.";
  if (seasonDialog.open) renderMobileSeasonHeader(media, season);
  configureSeasonAddButton(media, season);
  list.replaceChildren(...season.episodes.map((episode) => episodeCard(episode, media, season.season_number)));
  list.scrollTop = 0;
}

async function loadSeasonEpisodes(media, season) {
  const panel = document.querySelector("#media-episodes-panel");
  const list = document.querySelector("#media-episodes-list");
  const requestKey = `${mediaIdentity(media)}:${season.season_number}`;
  panel.hidden = false;
  panel.dataset.requestKey = requestKey;
  document.querySelector("#media-episodes-title").textContent = seasonDialog.open
    ? "Episoden"
    : `Staffel ${season.season_number}`;
  document.querySelector("#media-episodes-count").textContent = "";
  document.querySelector("#media-episodes-status").textContent = "Episoden werden geladen …";
  configureSeasonAddButton(media, season);
  list.replaceChildren();
  const cached = seasonCache.get(requestKey);
  if (cached && Date.now() - cached.savedAt < SERIES_CACHE_TTL) {
    renderSeasonEpisodes(cached.season, media);
    return;
  }
  try {
    const payload = await api(`/api/media/tv/${media.tmdb_id}/seasons/${season.season_number}`);
    if (!previewDialog.open || panel.dataset.requestKey !== requestKey) return;
    seasonCache.set(requestKey, { season: payload.season, savedAt: Date.now() });
    renderSeasonEpisodes(payload.season, media);
  } catch (error) {
    if (!previewDialog.open || panel.dataset.requestKey !== requestKey) return;
    document.querySelector("#media-episodes-status").textContent = error.message;
  }
}

function configureSeasonAddButton(media, season) {
  const button = document.querySelector("#media-season-add");
  const stored = savedSeason(media.tmdb_id, season.season_number);
  button.onclick = null;
  button.disabled = Boolean(stored);
  button.classList.toggle("saved", Boolean(stored));
  button.textContent = stored ? "✓ Staffel gespeichert" : "＋ Staffel hinzufügen";
  if (!stored) button.onclick = () => addSeasonToCollection(media, season, button);
}

async function addSeasonToCollection(media, season, button) {
  button.disabled = true;
  button.textContent = "Wird gespeichert …";
  try {
    const payload = await api("/api/media/seasons", {
      method: "POST",
      body: JSON.stringify({
        tv_tmdb_id: media.tmdb_id,
        season_number: season.season_number,
        series_title: media.title,
        season_title: season.name || `Staffel ${season.season_number}`,
        series_overview: media.overview,
        season_overview: season.overview,
        air_date: season.air_date,
        original_language: media.original_language,
        cover_url: season.cover_url,
        series_cover_url: media.cover_url,
        backdrop_url: media.backdrop_url,
        episode_count: season.episode_count || season.episodes?.length || 0,
        status: "watchlist",
      }),
    });
    state.seasons = [payload.season, ...state.seasons];
    applySeasonVisibility(true);
    configureSeasonAddButton(media, season);
    showToast(`„${payload.season.title}“ wurde zur Watchlist hinzugefügt.`);
  } catch (error) {
    if (error.status === 409) await loadMedia();
    configureSeasonAddButton(media, season);
    showToast(
      error.status === 409 ? "Diese Staffel ist bereits gespeichert." : `Nicht gespeichert: ${error.message}`,
      true,
    );
  }
}

function renderSeriesSeasons(series, media) {
  const section = document.querySelector("#media-series-section");
  const tabs = document.querySelector("#media-season-tabs");
  const episodesPanel = document.querySelector("#media-episodes-panel");
  section.hidden = false;
  tabs.replaceChildren();
  episodesPanel.hidden = true;
  document.querySelector("#media-series-title").textContent = series.name || media.title;
  document.querySelector("#media-series-count").textContent = `${series.seasons.length} ${series.seasons.length === 1 ? "Staffel" : "Staffeln"}`;
  const mobileSeasonFlow = usesMobileMediaLayout();
  document.querySelector("#media-series-status").textContent = series.seasons.length
    ? (mobileSeasonFlow
      ? "Wähle eine Staffel, um ihre Staffelansicht zu öffnen."
      : "Wähle eine Staffel, um ihre Episoden zu öffnen.")
    : "TMDB führt für diese Serie noch keine regulären Staffeln.";
  let requestedTab = null;
  let seasonOneTab = null;
  series.seasons.forEach((season) => {
    const tab = document.createElement("button");
    tab.className = "media-season-tab";
    tab.type = "button";
    tab.role = "tab";
    tab.textContent = `Staffel ${season.season_number}`;
    tab.setAttribute("aria-selected", "false");
    tab.setAttribute("aria-controls", mobileSeasonFlow ? "media-season-dialog" : "media-episodes-panel");
    if (mobileSeasonFlow) tab.setAttribute("aria-haspopup", "dialog");
    tab.addEventListener("click", () => {
      activateSeasonTab(tabs, tab);
      if (usesMobileMediaLayout()) {
        openMobileSeasonDialog(media, season);
      } else {
        restoreEpisodesPanel();
        loadSeasonEpisodes(media, season);
      }
    });
    tabs.append(tab);
    if (Number(state.previewSeasonNumber) === Number(season.season_number)) requestedTab = tab;
    if (Number(season.season_number) === 1) seasonOneTab = tab;
  });
  const initialTab = requestedTab || seasonOneTab || tabs.querySelector(".media-season-tab");
  if (initialTab) {
    state.previewSeasonNumber = null;
    if (mobileSeasonFlow) activateSeasonTab(tabs, initialTab);
    else initialTab.click();
  }
}

async function loadSeriesSeasons(media) {
  const section = document.querySelector("#media-series-section");
  section.hidden = false;
  document.querySelector("#media-series-title").textContent = "Staffeln werden geladen …";
  document.querySelector("#media-series-count").textContent = "";
  document.querySelector("#media-series-status").textContent = "TMDB wird nach Staffeln durchsucht.";
  const identity = mediaIdentity(media);
  const cached = seriesCache.get(identity);
  if (cached && Date.now() - cached.savedAt < SERIES_CACHE_TTL) {
    renderSeriesSeasons(cached.series, media);
    return;
  }
  try {
    const payload = await api(`/api/media/tv/${media.tmdb_id}/seasons`);
    if (!previewDialog.open || mediaIdentity(state.previewMedia) !== identity) return;
    seriesCache.set(identity, { series: payload.series, savedAt: Date.now() });
    renderSeriesSeasons(payload.series, media);
  } catch (error) {
    if (!previewDialog.open || mediaIdentity(state.previewMedia) !== identity) return;
    document.querySelector("#media-series-title").textContent = "Staffeln nicht verfügbar";
    document.querySelector("#media-series-status").textContent = error.message;
  }
}

function updateReviewCount() {
  const count = document.querySelector("#media-review-count");
  count.textContent = `${reviewInput.value.length} / ${reviewInput.maxLength}`;
  count.classList.toggle("limit-near", reviewInput.value.length > reviewInput.maxLength * 0.9);
}

function openRatingDialog(media) {
  state.ratingMedia = media;
  ratingForm.reset();
  document.querySelector("#media-rating-title").textContent = `„${media.title}“ bewerten`;
  const selected = ratingForm.querySelector(`[name="media-rating"][value="${media.rating}"]`);
  if (selected) selected.checked = true;
  reviewInput.value = media.review || "";
  updateReviewCount();
  ratingDialog.showModal();
}

async function saveRating(event) {
  event.preventDefault();
  const media = state.ratingMedia;
  if (!media) return;
  const submit = document.querySelector("#save-media-rating");
  const selected = ratingForm.querySelector('[name="media-rating"]:checked');
  submit.disabled = true;
  submit.textContent = "Wird gespeichert …";
  try {
    const payload = await api(`/api/media/${media.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        rating: selected ? Number(selected.value) : null,
        review: reviewInput.value.trim(),
      }),
    });
    Object.assign(media, payload.media);
    ratingDialog.close();
    state.ratingMedia = null;
    renderLibrary();
    if (previewDialog.open) renderPreviewActions();
    showToast(`Bewertung für „${media.title}“ gespeichert.`);
  } catch (error) {
    showToast(`Bewertung nicht gespeichert: ${error.message}`, true);
  } finally {
    submit.disabled = false;
    submit.textContent = "Bewertung speichern";
  }
}

function updateCounts(visibleCount) {
  const collectionItems = [
    ...state.media,
    ...(state.showSeasons && state.mediaType !== "movie" ? state.seasons : []),
  ];
  const typeScoped = state.mediaType === "all"
    ? collectionItems
    : collectionItems.filter((media) => media.media_type === state.mediaType);
  const counts = { all: typeScoped.length, watchlist: 0, watching: 0, completed: 0, dropped: 0 };
  typeScoped.forEach((media) => { counts[media.status] += 1; });
  Object.entries(counts).forEach(([status, count]) => {
    document.querySelector(`#count-${status}`).textContent = count;
  });
  const content = VIEW_CONTENT[state.filter];
  const typeLabel = MEDIA_TYPE_LABELS[state.mediaType];
  document.querySelector("#library-heading").textContent = state.filter === "all"
    ? typeLabel
    : `${content.title}${state.mediaType === "all" ? "" : ` · ${typeLabel}`}`;
  document.querySelector("#empty-title").textContent = state.mediaType === "all"
    ? content.emptyTitle
    : `Keine ${typeLabel.toLocaleLowerCase("de")} in dieser Ansicht.`;
  document.querySelector("#empty-copy").textContent = content.emptyCopy;
  document.querySelector("#view-count").textContent = `${visibleCount} ${visibleCount === 1 ? "Titel" : "Titel"}`;
}

function renderLibrary() {
  const visible = filteredAndSortedMedia();
  mediaGrid.replaceChildren();
  let collectionCount = 0;
  if (state.libraryMode === "collections") {
    collectionCount = renderGroupedLibrary(visible);
  } else {
    visible.forEach((media) => mediaGrid.append(libraryCard(media)));
  }
  loadingState.hidden = true;
  mediaGrid.hidden = visible.length === 0;
  emptyState.hidden = visible.length !== 0;
  updateCounts(visible.length);
  if (collectionCount) {
    const suffix = collectionCount === 1 ? "1 Filmreihe" : `${collectionCount} Filmreihen`;
    document.querySelector("#view-count").textContent = `${visible.length} Titel · ${suffix}`;
  }
}

async function loadMedia() {
  const [mediaPayload, seasonPayload] = await Promise.all([
    api("/api/media"),
    api("/api/media/seasons"),
  ]);
  state.media = mediaPayload.media;
  state.seasons = seasonPayload.seasons;
  renderLibrary();
  if (state.libraryMode === "collections") {
    collectionGroupingButton.disabled = true;
    collectionGroupingButtonLabel.textContent = "Filmreihen werden geladen …";
    await ensureMovieCollectionIndex(state.media);
    collectionGroupingButton.disabled = false;
    collectionGroupingButtonLabel.textContent = "Filme einzeln anzeigen";
    renderLibrary();
  }
}

async function addToWatchlist(media, button) {
  button.disabled = true;
  button.textContent = "Wird gespeichert …";
  try {
    await api("/api/media", {
      method: "POST",
      body: JSON.stringify({ ...media, status: "watchlist" }),
    });
    await loadMedia();
    renderSearchResults();
    showToast(`„${media.title}“ wurde zur Watchlist hinzugefügt.`);
  } catch (error) {
    if (error.status === 409) await loadMedia();
    renderSearchResults();
    showToast(error.status === 409 ? "Dieser Titel ist bereits gespeichert." : `Nicht gespeichert: ${error.message}`, true);
  }
}

async function executeSearch(query) {
  if (query.length < 2) return;
  if (query.length > searchInput.maxLength) {
    showToast(`Die Suche darf höchstens ${searchInput.maxLength} Zeichen lang sein.`, true);
    return;
  }
  state.lastSearchQuery = query;
  const button = searchForm.querySelector('[type="submit"]');
  button.disabled = true;
  button.textContent = "Suche …";
  searchPanel.hidden = false;
  const loading = document.createElement("div");
  loading.className = "loading-state";
  loading.textContent = "TMDB wird nach Filmen und Serien durchsucht …";
  searchResults.replaceChildren(loading);
  searchPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  const key = `${state.searchLimit}:${normalizeSearch(query)}`;
  try {
    const cached = searchCache.get(key);
    if (cached && Date.now() - cached.savedAt < SEARCH_CACHE_TTL) {
      state.searchResults = cached.results;
    } else {
      const payload = await api(`/api/media/search?q=${encodeURIComponent(query)}&limit=${state.searchLimit}`);
      state.searchResults = payload.results;
      if (payload.results.length) searchCache.set(key, { results: payload.results, savedAt: Date.now() });
      else searchCache.delete(key);
    }
    renderSearchResults();
  } catch (error) {
    searchResults.replaceChildren();
    const message = document.createElement("div");
    message.className = "empty-state";
    const heading = document.createElement("h3");
    heading.textContent = "Die Suche ist gerade nicht verfügbar";
    const copy = document.createElement("p");
    copy.textContent = `${error.message} Es wurde nichts gespeichert.`;
    const retry = document.createElement("button");
    retry.className = "button button-primary";
    retry.type = "button";
    retry.textContent = "Noch einmal suchen";
    retry.addEventListener("click", () => executeSearch(query));
    message.append(heading, copy, retry);
    searchResults.append(message);
  } finally {
    button.disabled = false;
    button.textContent = "Suchen";
  }
}

function setFilter(filter, persist = true) {
  if (!(filter in VIEW_CONTENT)) filter = "all";
  state.filter = filter;
  document.querySelectorAll(".status-tab").forEach((tab) => {
    const selected = tab.dataset.filter === filter;
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-pressed", String(selected));
  });
  settingsStartView.value = filter;
  if (persist) localStorage.setItem("moviepedia-start-view", filter);
  renderLibrary();
}

function applySort(sort, persist = true) {
  if (!(sort in SORT_LABELS)) sort = "added_desc";
  state.sort = sort;
  sortButtonLabel.textContent = SORT_LABELS[sort];
  document.querySelectorAll("[data-sort-option]").forEach((option) => {
    option.setAttribute("aria-checked", String(option.dataset.sortOption === sort));
  });
  if (persist) localStorage.setItem("moviepedia-sort", sort);
  renderLibrary();
}

function applyTheme(theme, persist = true) {
  if (!(theme in THEME_COLORS)) theme = "blue-white";
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').content = THEME_COLORS[theme];
  themeOptions.forEach((option) => option.setAttribute("aria-checked", String(option.dataset.themeOption === theme)));
  settingsTheme.value = theme;
  if (persist) localStorage.setItem("moviepedia-theme", theme);
}

function setAppearanceMenu(open) {
  appearanceMenu.hidden = !open;
  appearanceButton.setAttribute("aria-expanded", String(open));
}

function setSortMenu(open) {
  sortMenu.hidden = !open;
  sortButton.setAttribute("aria-expanded", String(open));
}

function setMediaTypeMenu(open) {
  mediaTypeMenu.hidden = !open;
  mediaTypeButton.setAttribute("aria-expanded", String(open));
}

function applyMediaType(mediaType, persist = true) {
  if (!(mediaType in MEDIA_TYPE_LABELS)) mediaType = "all";
  state.mediaType = mediaType;
  mediaTypeButtonLabel.textContent = MEDIA_TYPE_LABELS[mediaType];
  collectionGroupingButton.hidden = mediaType === "tv";
  seasonVisibilityButton.hidden = mediaType === "movie";
  document.querySelectorAll("[data-media-type-option]").forEach((option) => {
    option.setAttribute("aria-checked", String(option.dataset.mediaTypeOption === mediaType));
  });
  if (persist) localStorage.setItem("moviepedia-media-type", mediaType);
  renderLibrary();
}

function applySeasonVisibility(show, persist = true) {
  state.showSeasons = Boolean(show);
  seasonVisibilityButton.setAttribute("aria-pressed", String(state.showSeasons));
  seasonVisibilityButton.title = state.showSeasons
    ? "Gespeicherte Staffeln in der Auflistung ausblenden"
    : "Gespeicherte Staffeln in der Auflistung anzeigen";
  if (persist) localStorage.setItem("moviepedia-show-seasons", String(state.showSeasons));
  renderLibrary();
}

function populateSettings() {
  const themes = [
    ["red", "Red"], ["blue-white", "Blue-white"], ["green", "Green"],
    ["brown", "Brown"], ["cozy", "Cozy"], ["light", "Light"],
  ];
  themes.forEach(([value, label]) => settingsTheme.add(new Option(label, value)));
  [4, 6, 8, 12].forEach((limit) => settingsSearchLimit.add(new Option(String(limit), String(limit))));
  [["all", "Alle"], ...Object.entries(STATUS_LABELS)]
    .forEach(([value, label]) => settingsStartView.add(new Option(label, value)));
}

function openDeleteDialog(media) {
  state.pendingDelete = media;
  document.querySelector("#delete-dialog-title").textContent = `„${media.title}“ entfernen?`;
  deleteDialog.showModal();
}

async function confirmDelete() {
  const media = state.pendingDelete;
  if (!media) return;
  confirmDeleteButton.disabled = true;
  confirmDeleteButton.textContent = "Wird entfernt …";
  try {
    const endpoint = media.item_type === "season"
      ? `/api/media/seasons/${media.id}`
      : `/api/media/${media.id}`;
    await api(endpoint, { method: "DELETE" });
    deleteDialog.close();
    if (previewDialog.open && state.previewItem
      && mediaIdentity(state.previewItem) === mediaIdentity(media)) {
      previewDialog.close();
    }
    state.pendingDelete = null;
    await loadMedia();
    if (!searchPanel.hidden) renderSearchResults();
    showToast(`„${media.title}“ wurde entfernt.`);
  } catch (error) {
    showToast(`Nicht entfernt: ${error.message}`, true);
  } finally {
    confirmDeleteButton.disabled = false;
    confirmDeleteButton.textContent = "Titel entfernen";
  }
}

let dialogLockedScrollY = 0;

function syncDialogScrollLock() {
  const hasOpenDialog = [...document.querySelectorAll("dialog")].some((dialog) => dialog.open);
  const root = document.documentElement;
  const body = document.body;
  const locked = root.classList.contains("dialog-scroll-locked");
  if (hasOpenDialog && !locked) {
    dialogLockedScrollY = window.scrollY;
    root.classList.add("dialog-scroll-locked");
    body.style.position = "fixed";
    body.style.top = `-${dialogLockedScrollY}px`;
    body.style.width = "100%";
    return;
  }
  if (!hasOpenDialog && locked) {
    root.classList.remove("dialog-scroll-locked");
    body.style.position = "";
    body.style.top = "";
    body.style.width = "";
    const previousScrollBehavior = root.style.scrollBehavior;
    root.style.scrollBehavior = "auto";
    window.scrollTo(0, dialogLockedScrollY);
    root.style.scrollBehavior = previousScrollBehavior;
  }
}

function initializeDialogScrollLock() {
  const dialogObserver = new MutationObserver(syncDialogScrollLock);
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialogObserver.observe(dialog, { attributes: true, attributeFilter: ["open"] });
    dialog.addEventListener("close", syncDialogScrollLock);
  });
}

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  executeSearch(searchInput.value.trim());
});
document.querySelector("#close-search").addEventListener("click", () => { searchPanel.hidden = true; });
document.querySelector("#empty-search").addEventListener("click", () => {
  searchInput.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
});
document.querySelectorAll(".status-tab").forEach((button) => button.addEventListener("click", () => setFilter(button.dataset.filter)));
appearanceButton.addEventListener("click", () => setAppearanceMenu(appearanceMenu.hidden));
themeOptions.forEach((option) => option.addEventListener("click", () => {
  applyTheme(option.dataset.themeOption);
  setAppearanceMenu(false);
}));
sortButton.addEventListener("click", () => setSortMenu(sortMenu.hidden));
mediaTypeButton.addEventListener("click", () => setMediaTypeMenu(mediaTypeMenu.hidden));
seasonVisibilityButton.addEventListener("click", () => applySeasonVisibility(!state.showSeasons));
collectionGroupingButton.addEventListener("click", () => {
  setCollectionGrouping(state.libraryMode !== "collections");
});
document.querySelectorAll("[data-media-type-option]").forEach((option) => option.addEventListener("click", () => {
  applyMediaType(option.dataset.mediaTypeOption);
  setMediaTypeMenu(false);
}));
document.querySelectorAll("[data-sort-option]").forEach((option) => option.addEventListener("click", () => {
  applySort(option.dataset.sortOption);
  setSortMenu(false);
}));
document.querySelector("#open-settings").addEventListener("click", () => settingsDialog.showModal());
settingsTheme.addEventListener("change", () => applyTheme(settingsTheme.value));
settingsSearchLimit.addEventListener("change", () => {
  state.searchLimit = Number(settingsSearchLimit.value);
  localStorage.setItem("moviepedia-search-limit", String(state.searchLimit));
  showToast(`Künftig werden ${state.searchLimit} Suchergebnisse angezeigt.`);
});
settingsStartView.addEventListener("change", () => setFilter(settingsStartView.value));
confirmDeleteButton.addEventListener("click", confirmDelete);
previewAddButton.addEventListener("click", async () => {
  const item = state.previewItem;
  if (!item) return;
  await addToWatchlist(item, previewAddButton);
  if (previewDialog.open && state.previewItem === item) {
    renderPreviewActions();
    (previewAddButton.hidden ? previewRateButton : previewAddButton).focus();
  }
});
previewRateButton.addEventListener("click", () => {
  const saved = savedPreviewItem();
  if (saved) openRatingDialog(saved);
});
previewRemoveButton.addEventListener("click", () => {
  const saved = savedPreviewItem();
  if (saved) openDeleteDialog(saved);
});
ratingForm.addEventListener("submit", saveRating);
reviewInput.addEventListener("input", updateReviewCount);
document.querySelector("#clear-media-rating").addEventListener("click", () => {
  ratingForm.querySelectorAll('[name="media-rating"]').forEach((input) => { input.checked = false; });
});
deleteDialog.addEventListener("close", () => { state.pendingDelete = null; });
previewDialog.addEventListener("close", () => {
  if (seasonDialog.open) seasonDialog.close();
  state.previewMedia = null;
  state.previewItem = null;
  state.previewSeason = null;
  state.previewSeasonNumber = null;
});
seasonDialog.addEventListener("close", () => {
  state.previewSeason = null;
  restoreEpisodesPanel();
});
libraryCollectionDialog.addEventListener("close", () => { state.activeCollectionKey = null; });
libraryCollectionMissing.addEventListener("toggle", () => {
  if (!state.activeCollectionKey) return;
  if (libraryCollectionMissing.open) state.expandedMissingCollectionKeys.add(state.activeCollectionKey);
  else state.expandedMissingCollectionKeys.delete(state.activeCollectionKey);
});
ratingDialog.addEventListener("close", () => { state.ratingMedia = null; });
document.querySelectorAll(".dialog-close").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
}));
document.addEventListener("click", (event) => {
  if (!event.target.closest(".appearance-picker")) setAppearanceMenu(false);
  if (!event.target.closest(".sort-picker")) setSortMenu(false);
  if (!event.target.closest(".media-type-picker")) setMediaTypeMenu(false);
});

async function initializeApp() {
  initializeDialogScrollLock();
  populateSettings();
  const storedTheme = localStorage.getItem("moviepedia-theme") || localStorage.getItem("bookypedia-theme") || "blue-white";
  const storedSort = localStorage.getItem("moviepedia-sort") || "added_desc";
  const storedFilter = localStorage.getItem("moviepedia-start-view") || "all";
  const storedMediaType = localStorage.getItem("moviepedia-media-type") || "all";
  const storedShowSeasons = localStorage.getItem("moviepedia-show-seasons") === "true";
  const storedLimit = Number(localStorage.getItem("moviepedia-search-limit") || 4);
  state.searchLimit = [4, 6, 8, 12].includes(storedLimit) ? storedLimit : 4;
  settingsSearchLimit.value = String(state.searchLimit);
  applyTheme(storedTheme, false);
  applySort(storedSort, false);
  applyMediaType(storedMediaType, false);
  applySeasonVisibility(storedShowSeasons, false);
  setFilter(storedFilter, false);
  try {
    await loadMedia();
  } catch (error) {
    loadingState.textContent = `Die Sammlung konnte nicht geladen werden: ${error.message}`;
    showToast("Keine Verbindung zur lokalen App.", true);
  }
}

initializeApp();

mobileMediaLayout.addEventListener("change", () => {
  renderLibrary();
  if (!searchPanel.hidden) renderSearchResults();
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
}
