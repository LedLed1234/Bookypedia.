const IS_MOBILE_UI = document.documentElement.classList.contains("platform-mobile");
const BOOK_INFO_SYMBOL = document.documentElement.dataset.bookInfoSymbol || "!";

const STATUS_LABELS = {
  unread: "Ungelesen",
  reading: "Lese ich",
  read: "Gelesen",
  want_to_read: "Wunschliste",
};

const VIEW_CONTENT = {
  all: {
    title: "Alle Bücher",
    emptyTitle: "Deine Sammlung ist noch leer.",
    emptyCopy: "Suche oben nach einem Buch und füge es deiner Sammlung hinzu.",
  },
  reading: {
    title: "Lese ich",
    emptyTitle: "Du liest gerade kein Buch.",
    emptyCopy: "Suche oben nach einem Buch und starte deine nächste Lektüre.",
  },
  read: {
    title: "Gelesen",
    emptyTitle: "Du hast noch kein Buch als gelesen markiert.",
    emptyCopy: "Füge bereits gelesene Bücher hinzu und halte deine Bewertung fest.",
  },
  want_to_read: {
    title: "Wunschliste",
    emptyTitle: "Deine Wunschliste ist noch leer.",
    emptyCopy: "Speichere Bücher, die du später lesen möchtest.",
  },
  unread: {
    title: "Ungelesen",
    emptyTitle: "Du hast keine ungelesenen Bücher im Besitz.",
    emptyCopy: "Füge ein Buch hinzu, das dir bereits gehört und noch auf dich wartet.",
  },
  owned: {
    title: "Im Besitz",
    emptyTitle: "Du hast noch keine Bücher im Besitz.",
    emptyCopy: "Bücher aus „Ungelesen“, „Lese ich“ und „Gelesen“ erscheinen hier gemeinsam.",
  },
};

const SORT_OPTIONS = {
  added_desc: "Zuletzt hinzugefügt",
  added_asc: "Zuerst hinzugefügt",
  rating_desc: "Bewertung: hoch",
  rating_asc: "Bewertung: niedrig",
  title_asc: "Titel: A–Z",
  title_desc: "Titel: Z–A",
};
const STATUS_HISTORY = [
  { status: "want_to_read", field: "want_to_read_at", label: "Zur Wunschliste hinzugefügt" },
  { status: "unread", field: "owned_at", label: "Als ungelesen erfasst" },
  { status: "reading", field: "reading_at", label: "Angefangen zu lesen" },
  { status: "read", field: "read_at", label: "Fertig gelesen" },
];
const titleCollator = new Intl.Collator("de", { sensitivity: "base", numeric: true });

const state = {
  books: [],
  filter: "all",
  searchResults: [],
  lastSearchQuery: "",
  suggestions: [],
  remoteSuggestions: [],
  suggestionQuery: "",
  detailBook: null,
  infoBook: null,
  detailMetadataIdentity: null,
  detailMetadata: null,
  detailMetadataLoaded: false,
  detailMetadataUnavailable: false,
  descriptionExpanded: false,
  seriesData: null,
  seriesLoaded: false,
  seriesStatus: null,
  seriesRequestUrl: null,
  libraryMode: "all",
  seriesIndex: new Map(),
  activeSeriesKey: null,
  collectionSeriesExpanded: false,
  detailSeriesExpanded: false,
  reviewCandidate: null,
  seriesIndexLoading: false,
  sort: "added_desc",
  searchResultLimit: 4,
  primaryProvider: "open_library",
  fallbackProvider: "google_books",
  readingHistoryExpanded: false,
  dateFormat: "DD-MM-YYYY",
  reviewMaxLength: 1000,
};
const grid = document.querySelector("#book-grid");
const emptyState = document.querySelector("#empty-state");
const loadingState = document.querySelector("#library-loading");
const searchPanel = document.querySelector("#search-panel");
const searchResults = document.querySelector("#search-results");
const searchForm = document.querySelector("#search-form");
const searchInput = document.querySelector("#search-input");
const searchSuggestions = document.querySelector("#search-suggestions");
const manualDialog = document.querySelector("#manual-dialog");
const reviewDialog = document.querySelector("#review-dialog");
const reviewReaderDialog = document.querySelector("#review-reader-dialog");
const reviewTextarea = document.querySelector('#review-form textarea[name="review"]');
const reviewCharacterCount = document.querySelector("#review-character-count");
const bookDialog = document.querySelector("#book-dialog");
const collectionDialog = document.querySelector("#collection-dialog");
const collectionBookList = document.querySelector("#collection-book-list");
const collectionOtherSeries = document.querySelector("#collection-other-series");
const collectionOtherToggle = document.querySelector("#collection-other-toggle");
const collectionOtherToggleLabel = document.querySelector("#collection-other-toggle-label");
const collectionOtherList = document.querySelector("#collection-other-list");
const groupingButton = document.querySelector("#grouping-button");
const groupingButtonLabel = document.querySelector("#grouping-button-label");
const sortButton = document.querySelector("#sort-button");
const sortButtonLabel = document.querySelector("#sort-button-label");
const sortMenu = document.querySelector("#sort-menu");
const sortOptions = document.querySelectorAll("[data-sort-option]");
const readingHistory = document.querySelector("#reading-history");
const readingHistoryList = document.querySelector("#reading-history-list");
const readingHistoryToggle = document.querySelector("#reading-history-toggle");
const bookDialogMainView = document.querySelector("#book-dialog-main-view");
const bookDialogInfoView = document.querySelector("#book-dialog-info-view");
const bookDialogInfoButton = document.querySelector("#book-dialog-info");
const bookInfoBackButton = document.querySelector("#book-info-back");
const bookInfoGrid = document.querySelector("#book-info-grid");
const bookInfoStatus = document.querySelector("#book-info-status");
const bookInfoSource = document.querySelector("#book-info-source");
const bookDescriptionSection = document.querySelector("#book-description");
const bookDescriptionToggle = document.querySelector("#book-description-toggle");
const seriesHeading = document.querySelector("#series-heading");
const seriesPosition = document.querySelector("#series-position");
const seriesContent = document.querySelector("#series-content");
const seriesNote = document.querySelector("#series-note");
const deleteDialog = document.querySelector("#delete-dialog");
const confirmDeleteButton = document.querySelector("#confirm-delete");
const appearanceButton = document.querySelector("#appearance-button");
const appearanceMenu = document.querySelector("#appearance-menu");
const themeOptions = document.querySelectorAll("[data-theme-option]");
const settingsDialog = document.querySelector("#settings-dialog");
const settingsThemeSelect = document.querySelector("#settings-theme");
const settingsSearchLimitSelect = document.querySelector("#settings-search-limit");
const settingsDateFormatSelect = document.querySelector("#settings-date-format");
const settingsPrimaryProviderSelect = document.querySelector("#settings-primary-provider");
const settingsFallbackProviderSelect = document.querySelector("#settings-fallback-provider");
const settingsStartViewSelect = document.querySelector("#settings-start-view");
const settingsMobileTextSizeSelect = document.querySelector("#settings-mobile-text-size");
const THEME_COLORS = {
  red: "#101512",
  "blue-white": "#101512",
  green: "#101512",
  brown: "#101512",
  cozy: "#101512",
  light: "#f3f1eb",
};
let toastTimer;
let suggestionTimer;
let suggestionController;
let activeSuggestionIndex = -1;
let pendingDelete;
let seriesPollTimer;
let groupingPollTimer;
let metadataPollTimer;
let searchHydrationGeneration = 0;
const searchCache = new Map();
const SEARCH_CACHE_TTL = 10 * 60 * 1000;
// Etwas längeres Debouncing verhindert, dass langsames Tippen auf Mobilgeräten
// mehrere bereits veraltete Open-Library-Anfragen parallel auf dem VPS bindet.
const SUGGESTION_DELAY = 300;
const LANGUAGE_LABELS = {
  eng: "Englisch",
  ger: "Deutsch",
  deu: "Deutsch",
  fre: "Französisch",
  fra: "Französisch",
  spa: "Spanisch",
  ita: "Italienisch",
  jpn: "Japanisch",
  por: "Portugiesisch",
};
const FALLBACK_APP_CONFIG = {
  catalogue: {
    mode: "primary_fallback",
    primaryProvider: "open_library",
    fallbackProvider: "google_books",
  },
  defaults: {
    theme: "blue-white",
    searchResultLimit: 4,
    startView: "all",
    mobileTextSize: 3,
    dateFormat: "DD-MM-YYYY",
    reviewMaxLength: 1000,
  },
  options: {
    themes: [
      { value: "red", label: "Red" },
      { value: "blue-white", label: "Blue-white" },
      { value: "green", label: "Green" },
      { value: "brown", label: "Brown" },
      { value: "cozy", label: "Cozy" },
      { value: "light", label: "Light" },
    ],
    searchResultLimits: [4, 6, 8, 12],
    dateFormats: [
      { value: "DD-MM-YYYY", label: "DD-MM-YYYY" },
      { value: "DD.MM.YYYY", label: "DD.MM.YYYY" },
      { value: "YYYY-MM-DD", label: "YYYY-MM-DD" },
      { value: "MM/DD/YYYY", label: "MM/DD/YYYY" },
    ],
    bookProviders: [
      { value: "open_library", label: "Open Library" },
      { value: "google_books", label: "Google Books" },
    ],
    mobileTextSizes: [
      { value: 1, label: "Stufe 1 – Kompakt" },
      { value: 2, label: "Stufe 2" },
      { value: 3, label: "Stufe 3 – Standard" },
      { value: 4, label: "Stufe 4" },
      { value: 5, label: "Stufe 5 – Groß" },
    ],
    startViews: [
      { value: "all", label: "Alle" },
      { value: "unread", label: "Ungelesen" },
      { value: "reading", label: "Lese ich" },
      { value: "read", label: "Gelesen" },
      { value: "want_to_read", label: "Wunschliste" },
      { value: "owned", label: "Im Besitz" },
    ],
  },
};
let appConfig = FALLBACK_APP_CONFIG;

function populateSelect(select, options) {
  select.replaceChildren(...options.map(({ value, label }) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = label;
    return option;
  }));
}

async function loadAppConfig() {
  try {
    const response = await fetch("/static/config.json", { cache: "no-cache" });
    if (!response.ok) throw new Error("Konfiguration nicht verfügbar");
    const loaded = await response.json();
    appConfig = {
      catalogue: { ...FALLBACK_APP_CONFIG.catalogue, ...(loaded.catalogue || {}) },
      defaults: { ...FALLBACK_APP_CONFIG.defaults, ...(loaded.defaults || {}) },
      options: { ...FALLBACK_APP_CONFIG.options, ...(loaded.options || {}) },
    };
  } catch (_error) {
    appConfig = FALLBACK_APP_CONFIG;
  }
  populateSelect(settingsThemeSelect, appConfig.options.themes);
  populateSelect(
    settingsSearchLimitSelect,
    appConfig.options.searchResultLimits.map((value) => ({ value, label: `${value} Bücher` })),
  );
  populateSelect(settingsDateFormatSelect, appConfig.options.dateFormats);
  populateSelect(settingsStartViewSelect, appConfig.options.startViews);
  populateSelect(settingsMobileTextSizeSelect, appConfig.options.mobileTextSizes);
  populateSelect(settingsPrimaryProviderSelect, appConfig.options.bookProviders);
  populateSelect(settingsFallbackProviderSelect, appConfig.options.bookProviders);
  const configuredReviewMaxLength = Number(appConfig.defaults.reviewMaxLength);
  state.reviewMaxLength = Number.isInteger(configuredReviewMaxLength) && configuredReviewMaxLength > 0
    ? configuredReviewMaxLength
    : 1000;
  reviewTextarea.maxLength = state.reviewMaxLength;
  updateReviewCharacterCount();
}

function setAppearanceMenu(open) {
  appearanceMenu.hidden = !open;
  appearanceButton.setAttribute("aria-expanded", String(open));
}

function setSortMenu(open) {
  sortMenu.hidden = !open;
  sortButton.setAttribute("aria-expanded", String(open));
}

function applySort(sort, persist = true) {
  if (!Object.hasOwn(SORT_OPTIONS, sort)) sort = "added_desc";
  state.sort = sort;
  sortButtonLabel.textContent = SORT_OPTIONS[sort];
  sortOptions.forEach((option) => {
    option.setAttribute("aria-checked", String(option.dataset.sortOption === sort));
  });
  if (persist) {
    try { localStorage.setItem("bookypedia-sort", sort); } catch (_error) {}
  }
  if (loadingState.hidden) renderLibrary();
}

function setLibraryFilter(filter) {
  if (!Object.hasOwn(VIEW_CONTENT, filter)) filter = "all";
  state.filter = filter;
  document.querySelectorAll(".status-tab").forEach((tab) => {
    const active = tab.dataset.filter === filter;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  if (loadingState.hidden) renderLibrary();
}

function applyStartView(filter, persist = true) {
  if (!Object.hasOwn(VIEW_CONTENT, filter)) filter = "all";
  settingsStartViewSelect.value = filter;
  if (persist) {
    try { localStorage.setItem("bookypedia-start-view", filter); } catch (_error) {}
  }
  setLibraryFilter(filter);
}

function applySearchResultLimit(value, persist = true) {
  const configuredLimits = appConfig.options.searchResultLimits.map(Number);
  const defaultLimit = Number(appConfig.defaults.searchResultLimit) || 4;
  const limit = configuredLimits.includes(Number(value)) ? Number(value) : defaultLimit;
  state.searchResultLimit = limit;
  settingsSearchLimitSelect.value = String(limit);
  searchCache.clear();
  if (persist) {
    try { localStorage.setItem("bookypedia-search-limit", String(limit)); } catch (_error) {}
  }
}

function applyBookProviders(primary, fallback, persist = true) {
  const allowed = new Set(appConfig.options.bookProviders.map(({ value }) => String(value)));
  const defaultPrimary = appConfig.catalogue.primaryProvider || "open_library";
  const defaultFallback = appConfig.catalogue.fallbackProvider || defaultPrimary;
  state.primaryProvider = allowed.has(primary) ? primary : defaultPrimary;
  state.fallbackProvider = allowed.has(fallback) ? fallback : defaultFallback;
  settingsPrimaryProviderSelect.value = state.primaryProvider;
  settingsFallbackProviderSelect.value = state.fallbackProvider;
  searchCache.clear();
  if (persist) {
    try {
      localStorage.setItem("bookypedia-primary-provider", state.primaryProvider);
      localStorage.setItem("bookypedia-fallback-provider", state.fallbackProvider);
    } catch (_error) {}
  }
}

function applyMobileTextSize(value, persist = true) {
  const configuredSizes = appConfig.options.mobileTextSizes.map(({ value: size }) => Number(size));
  const defaultSize = Number(appConfig.defaults.mobileTextSize) || 3;
  const size = configuredSizes.includes(Number(value)) ? Number(value) : defaultSize;
  document.documentElement.dataset.mobileTextSize = String(size);
  settingsMobileTextSizeSelect.value = String(size);
  if (persist) {
    try { localStorage.setItem("bookypedia-mobile-text-size", String(size)); } catch (_error) {}
  }
}

function applyDateFormat(value, persist = true) {
  const configuredFormats = new Set(
    appConfig.options.dateFormats.map(({ value: format }) => String(format)),
  );
  const defaultFormat = appConfig.defaults.dateFormat || "DD-MM-YYYY";
  state.dateFormat = configuredFormats.has(value) ? value : defaultFormat;
  settingsDateFormatSelect.value = state.dateFormat;
  if (persist) {
    try { localStorage.setItem("bookypedia-date-format", state.dateFormat); } catch (_error) {}
  }
  if (!loadingState.hidden) renderLibrary();
  if (!searchPanel.hidden) renderSearchResults();
  if (!searchSuggestions.hidden && state.suggestionQuery) renderSuggestions(state.suggestionQuery);
  if (state.seriesLoaded) renderSeriesDetails();
  if (bookDialog.open) {
    renderReadingHistory(findCollectionBook(state.detailBook) || state.detailBook);
    renderBookInfo();
  }
}

function applyTheme(theme, persist = true) {
  if (!Object.hasOwn(THEME_COLORS, theme)) return;
  document.documentElement.dataset.theme = theme;
  settingsThemeSelect.value = theme;
  document.querySelector('meta[name="theme-color"]').content = THEME_COLORS[theme];
  themeOptions.forEach((option) => {
    option.setAttribute("aria-checked", String(option.dataset.themeOption === theme));
  });
  if (persist) {
    try { localStorage.setItem("bookypedia-theme", theme); } catch (_error) {}
  }
}

async function api(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "same-origin",
  });
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

function statusSelect(current) {
  const select = document.createElement("select");
  select.className = "status-select";
  select.setAttribute("aria-label", "Lesestatus ändern");
  for (const [value, label] of Object.entries(STATUS_LABELS)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === current;
    select.append(option);
  }
  return select;
}

function coverElement(book) {
  const wrap = document.createElement("div");
  wrap.className = "book-cover-wrap";
  const coverSource = book.cover_src || book.cover_url;
  if (coverSource) {
    const image = document.createElement("img");
    image.className = "book-cover";
    image.src = coverSource;
    image.alt = `Cover von ${book.title}`;
    image.loading = "lazy";
    image.addEventListener("error", () => {
      image.remove();
      wrap.append(placeholderCover(book.title));
    }, { once: true });
    wrap.append(image);
  } else {
    wrap.append(placeholderCover(book.title));
  }
  return wrap;
}

function placeholderCover(title) {
  const placeholder = document.createElement("div");
  placeholder.className = "book-placeholder";
  placeholder.setAttribute("role", "img");
  placeholder.setAttribute("aria-label", `Kein Cover für ${title}`);
  const monogram = document.createElement("strong");
  monogram.className = "book-placeholder-mark";
  monogram.textContent = bookMonogram(title);
  const label = document.createElement("span");
  label.className = "book-placeholder-label";
  label.textContent = "Kein Cover";
  placeholder.append(monogram, label);
  return placeholder;
}

function bookMonogram(title) {
  const words = String(title || "Buch").trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0]).join("").toLocaleUpperCase("de") || "B";
}

function authorText(book) {
  return book.authors?.length ? book.authors.join(", ") : "Autor unbekannt";
}

function pageCountText(book, fallback = "") {
  const pages = Number(book?.page_count);
  return Number.isInteger(pages) && pages > 0 ? `${pages.toLocaleString("de-DE")} Seiten` : fallback;
}

const DATE_MONTH_NAMES = {
  january: 1, januar: 1,
  february: 2, februar: 2,
  march: 3, märz: 3, maerz: 3,
  april: 4,
  may: 5, mai: 5,
  june: 6, juni: 6,
  july: 7, juli: 7,
  august: 8,
  september: 9,
  october: 10, oktober: 10,
  november: 11,
  december: 12, dezember: 12,
};

function validPublicationDateParts(year, month = null, day = null) {
  if (!Number.isInteger(year) || year < 1) return null;
  if (month == null) return { year, month: null, day: null };
  if (!Number.isInteger(month) || month < 1 || month > 12) return null;
  if (day == null) return { year, month, day: null };
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (!Number.isInteger(day) || day < 1 || day > daysInMonth) return null;
  return { year, month, day };
}

function publicationDateParts(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  let match = text.match(/^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/);
  if (match) {
    return validPublicationDateParts(
      Number(match[1]),
      match[2] ? Number(match[2]) : null,
      match[3] ? Number(match[3]) : null,
    );
  }
  match = text.match(/^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$/);
  if (match) {
    const first = Number(match[1]);
    const second = Number(match[2]);
    const [day, month] = second > 12 && first <= 12 ? [second, first] : [first, second];
    return validPublicationDateParts(Number(match[3]), month, day);
  }
  const normalized = text.toLocaleLowerCase("de").replace(/,/g, " ");
  const monthEntry = Object.entries(DATE_MONTH_NAMES)
    .find(([name]) => new RegExp(`(^|\\s)${name}(\\s|$)`, "u").test(normalized));
  const yearMatch = normalized.match(/\b(\d{4})\b/);
  if (monthEntry && yearMatch) {
    const withoutYear = normalized.replace(yearMatch[0], " ");
    const dayMatch = withoutYear.match(/\b([12]?\d|3[01])\b/);
    return validPublicationDateParts(
      Number(yearMatch[1]),
      monthEntry[1],
      dayMatch ? Number(dayMatch[1]) : null,
    );
  }
  return null;
}

function formatDateParts({ year, month = null, day = null }) {
  const yyyy = String(year).padStart(4, "0");
  if (!month) return yyyy;
  const mm = String(month).padStart(2, "0");
  if (!day) {
    if (state.dateFormat === "YYYY-MM-DD") return `${yyyy}-${mm}`;
    if (state.dateFormat === "MM/DD/YYYY") return `${mm}/${yyyy}`;
    return state.dateFormat === "DD.MM.YYYY" ? `${mm}.${yyyy}` : `${mm}-${yyyy}`;
  }
  const dd = String(day).padStart(2, "0");
  if (state.dateFormat === "DD.MM.YYYY") return `${dd}.${mm}.${yyyy}`;
  if (state.dateFormat === "YYYY-MM-DD") return `${yyyy}-${mm}-${dd}`;
  if (state.dateFormat === "MM/DD/YYYY") return `${mm}/${dd}/${yyyy}`;
  return `${dd}-${mm}-${yyyy}`;
}

function formatPublicationDate(value) {
  const parts = publicationDateParts(value);
  return parts ? formatDateParts(parts) : String(value || "").trim();
}

function publicationDateText(book, withLabel = false) {
  const editionDate = String(book?.publish_date || "").trim();
  if (editionDate) {
    const formatted = formatPublicationDate(editionDate);
    return withLabel ? `Erschienen ${formatted}` : formatted;
  }
  const firstYear = book?.first_publish_year;
  if (!firstYear) return "";
  const formatted = formatPublicationDate(firstYear);
  return withLabel ? `Erstmals erschienen ${formatted}` : formatted;
}

function createBookInfoButton(book, insideBookDialog = false) {
  const button = document.createElement("button");
  button.className = insideBookDialog
    ? "icon-button series-info-button"
    : "icon-button book-card-info";
  button.type = "button";
  button.textContent = BOOK_INFO_SYMBOL;
  button.title = "Weitere Buchinformationen";
  button.setAttribute("aria-label", `Weitere Informationen zu ${book.title} anzeigen`);
  button.addEventListener("click", () => {
    if (insideBookDialog) openBookInfo(book);
    else openBookDetails(book, "info");
  });
  return button;
}

function setRemoveButtonAppearance(button) {
  button.classList.add("remove-book-button");
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("aria-hidden", "true");
  icon.setAttribute("focusable", "false");
  const paths = [
    "M3 6h18",
    "M8 6V4h8v2",
    "M19 6l-1 14H6L5 6",
    "M10 10v6",
    "M14 10v6",
  ];
  paths.forEach((pathData) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pathData);
    icon.append(path);
  });
  button.replaceChildren(icon);
}

function normalizeSearch(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLocaleLowerCase("de")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function editDistance(left, right) {
  const leftCharacters = Array.from(left);
  const rightCharacters = Array.from(right);
  const previous = Array.from({ length: rightCharacters.length + 1 }, (_, index) => index);
  for (let row = 1; row <= leftCharacters.length; row += 1) {
    const current = [row];
    for (let column = 1; column <= rightCharacters.length; column += 1) {
      current[column] = Math.min(
        current[column - 1] + 1,
        previous[column] + 1,
        previous[column - 1] + (leftCharacters[row - 1] === rightCharacters[column - 1] ? 0 : 1),
      );
    }
    previous.splice(0, previous.length, ...current);
  }
  return previous[rightCharacters.length];
}

function fuzzyBookScore(book, query) {
  const needle = normalizeSearch(query);
  const haystack = normalizeSearch(`${book.title} ${authorText(book)} ${book.isbn || ""}`);
  if (!needle || !haystack) return -1;
  if (haystack === needle) return 220;
  if (haystack.startsWith(needle)) return 200;
  const containedAt = haystack.indexOf(needle);
  if (containedAt >= 0) return 180 - Math.min(containedAt, 40);

  const words = haystack.split(" ");
  const queryWords = needle.split(" ");
  let score = 0;
  for (const queryWord of queryWords) {
    let best = -1;
    for (const word of words) {
      if (word.startsWith(queryWord)) best = Math.max(best, 125);
      else if (word.includes(queryWord)) best = Math.max(best, 105);
      else {
        const distance = editDistance(queryWord, word);
        const tolerance = queryWord.length >= 7 ? 2 : 1;
        if (distance <= tolerance) best = Math.max(best, 90 - (distance * 15));
      }
    }
    if (best < 0) return -1;
    score += best;
  }
  return score / queryWords.length;
}

function suggestionIdentity(book) {
  return book.provider_book_id
    ? `${book.provider || "open_library"}:${book.provider_book_id}`
    : book.isbn || normalizeSearch(`${book.title}|${authorText(book)}`);
}

function metadataIdentityForBook(book) {
  if (book.provider_edition_id) {
    return `${book.provider || "open_library"}:${book.provider_edition_id}`;
  }
  return book.isbn || suggestionIdentity(book);
}

function catalogueResultIdentity(book) {
  if (book.provider_edition_id) {
    return `${book.provider || "open_library"}:${book.provider_edition_id}`;
  }
  return book.isbn || suggestionIdentity(book);
}

function booksDescribeSameWork(left, right) {
  if (!left || !right) return false;
  if (sameProviderBook(left, right)) return true;
  if (normalizeSearch(left.title) !== normalizeSearch(right.title)) return false;
  const leftAuthors = new Set((left.authors || []).map(normalizeSearch).filter(Boolean));
  const rightAuthors = (right.authors || []).map(normalizeSearch).filter(Boolean);
  return !leftAuthors.size || !rightAuthors.length || rightAuthors.some((author) => leftAuthors.has(author));
}

function sameProviderBook(left, right) {
  return Boolean(
    left?.provider_book_id
    && right?.provider_book_id
    && (left.provider || "open_library") === (right.provider || "open_library")
    && left.provider_book_id === right.provider_book_id
  );
}

function booksDescribeSameEdition(left, right) {
  const leftEdition = left?.provider_edition_id || "";
  const rightEdition = right?.provider_edition_id || "";
  if (leftEdition || rightEdition) return Boolean(leftEdition && rightEdition && leftEdition === rightEdition);
  const leftIsbn = left?.isbn || "";
  const rightIsbn = right?.isbn || "";
  if (leftIsbn || rightIsbn) return Boolean(leftIsbn && rightIsbn && leftIsbn === rightIsbn);
  return true;
}

function mergeKnownBookMetadata(book, knownBook) {
  if (!knownBook || !booksDescribeSameWork(book, knownBook)) return book;
  const merged = { ...book };
  const workFields = [
    "original_title", "original_authors", "first_publish_year", "description", "subjects",
  ];
  const editionFields = [
    "provider_edition_id", "isbn", "cover_url", "cover_src", "language", "page_count", "publisher",
    "publish_date", "physical_format", "subtitle",
  ];
  const fields = booksDescribeSameEdition(book, knownBook)
    ? [...workFields, ...editionFields]
    : workFields;
  fields.forEach((field) => {
    const current = merged[field];
    const missing = current == null || current === "" || (Array.isArray(current) && current.length === 0);
    if (missing && knownBook[field] != null) merged[field] = knownBook[field];
  });
  if (!(merged.authors || []).length && (knownBook.authors || []).length) merged.authors = knownBook.authors;
  return merged;
}

function mergeLoadedBookMetadata(book, metadata) {
  const loaded = metadata && typeof metadata === "object" ? { ...metadata } : {};
  const currentEdition = book?.provider_edition_id || "";
  const loadedEdition = loaded.provider_edition_id || "";
  if (currentEdition && loadedEdition && currentEdition !== loadedEdition) {
    [
      "provider_edition_id", "isbn", "cover_url", "cover_src", "language", "page_count", "publisher",
      "publish_date", "physical_format", "subtitle",
    ].forEach((field) => delete loaded[field]);
  }

  Object.assign(book, loaded);
  const resolvedEdition = book?.provider_edition_id || loadedEdition;
  // Die Detailabfrage ist ausgabengenauer als Googles Suchliste. Wenn das
  // angeklickte Objekt selbst aus den Suchergebnissen stammt, wurde es bisher
  // zwar aktualisiert, seine bereits gerenderte Karte aber nicht. Dadurch
  // standen z. B. 335 Seiten in der Vorschau und 496 Seiten im Infodialog.
  let searchResultChanged = state.searchResults.includes(book);
  [...state.books, ...state.searchResults, ...state.suggestions, ...state.remoteSuggestions]
    .forEach((candidate) => {
      if (!candidate || candidate === book) return;
      if (!book?.provider_book_id
          || candidate.provider_book_id !== book.provider_book_id
          || (candidate.provider || "open_library") !== (book.provider || "open_library")) return;
      const candidateEdition = candidate.provider_edition_id || "";
      if (candidateEdition && resolvedEdition && candidateEdition !== resolvedEdition) return;
      Object.assign(candidate, loaded);
      if (state.searchResults.includes(candidate)) searchResultChanged = true;
    });
  if (searchResultChanged && !searchPanel.hidden) renderSearchResults();
  return { ...book };
}

function catalogueMetadataUrl(book) {
  return `/api/metadata?provider=${encodeURIComponent(book.provider || "open_library")}`
    + `&provider_book_id=${encodeURIComponent(book.provider_book_id)}`
    + (book.provider_edition_id
      ? `&provider_edition_id=${encodeURIComponent(book.provider_edition_id)}`
      : "");
}

async function hydrateSearchResultMetadata(books, generation) {
  const queue = [];
  const seen = new Set();
  for (const book of books) {
    if (!book?.provider_book_id) continue;
    const identity = metadataIdentityForBook(book);
    if (seen.has(identity)) continue;
    seen.add(identity);
    queue.push(book);
  }
  async function worker() {
    while (queue.length && generation === searchHydrationGeneration) {
      const book = queue.shift();
      try {
        const payload = await api(catalogueMetadataUrl(book));
        if (generation !== searchHydrationGeneration) return;
        book._metadataHydrationPending = false;
        mergeLoadedBookMetadata(book, payload.metadata || {});
      } catch (_error) {
        // Die Suchergebnisse bleiben mit ihren Katalogdaten nutzbar. Ein
        // einzelner fehlgeschlagener Detailabruf darf die Suche nicht leeren.
        book._metadataHydrationPending = false;
        if (!searchPanel.hidden) renderSearchResults();
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, queue.length) }, () => worker()));
}

function enrichKnownBookMetadata(book) {
  const candidates = [
    ...state.books,
    ...state.suggestions,
    ...state.remoteSuggestions,
    ...state.searchResults,
  ].filter((candidate) => candidate !== book && booksDescribeSameWork(book, candidate));
  return candidates.reduce((merged, candidate) => mergeKnownBookMetadata(merged, candidate), book);
}

function combinedSuggestions(query, remoteResults = []) {
  const local = state.books
    .map((book) => ({ book, score: fuzzyBookScore(book, query) }))
    .filter((entry) => entry.score >= 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, 2)
    .map((entry) => ({ ...entry.book, suggestion_source: "collection" }));
  const seen = new Set(local.map(catalogueResultIdentity));
  const combined = [...local];
  for (const book of remoteResults) {
    const identity = catalogueResultIdentity(book);
    if (seen.has(identity)) {
      const localIndex = combined.findIndex((candidate) => catalogueResultIdentity(candidate) === identity);
      const localBook = combined[localIndex];
      combined[localIndex] = {
        ...mergeKnownBookMetadata(book, localBook),
        suggestion_source: localBook.suggestion_source,
      };
      continue;
    }
    seen.add(identity);
    combined.push(book);
    if (combined.length === 6) break;
  }
  return combined;
}

function suggestionCover(book) {
  const coverSource = book.cover_src || book.cover_url;
  if (!coverSource) {
    const placeholder = document.createElement("span");
    placeholder.className = "suggestion-cover suggestion-placeholder";
    placeholder.textContent = bookMonogram(book.title);
    placeholder.setAttribute("aria-hidden", "true");
    return placeholder;
  }
  const image = document.createElement("img");
  image.className = "suggestion-cover";
  image.src = coverSource;
  image.alt = "";
  image.loading = "lazy";
  image.addEventListener("error", () => {
    const placeholder = document.createElement("span");
    placeholder.className = "suggestion-cover suggestion-placeholder";
    placeholder.textContent = bookMonogram(book.title);
    placeholder.setAttribute("aria-hidden", "true");
    image.replaceWith(placeholder);
  }, { once: true });
  return image;
}

function updateActiveSuggestion(index) {
  const rows = [...searchSuggestions.querySelectorAll(".suggestion-row")];
  activeSuggestionIndex = rows.length ? Math.max(-1, Math.min(index, rows.length - 1)) : -1;
  rows.forEach((row, rowIndex) => row.classList.toggle("active", rowIndex === activeSuggestionIndex));
  if (activeSuggestionIndex >= 0) {
    const active = rows[activeSuggestionIndex].querySelector(".suggestion-main");
    searchInput.setAttribute("aria-activedescendant", active.id);
    rows[activeSuggestionIndex].scrollIntoView({ block: "nearest" });
  } else {
    searchInput.removeAttribute("aria-activedescendant");
  }
}

function hideSuggestions() {
  searchSuggestions.hidden = true;
  searchInput.setAttribute("aria-expanded", "false");
  updateActiveSuggestion(-1);
}

function renderSuggestions(query, { loading = false, failed = false } = {}) {
  searchSuggestions.replaceChildren();
  activeSuggestionIndex = -1;

  state.suggestions.forEach((book, index) => {
    const row = document.createElement("div");
    row.className = "suggestion-row";
    const main = document.createElement("button");
    main.className = "suggestion-main";
    main.id = `suggestion-${index}`;
    main.type = "button";
    main.append(suggestionCover(book));

    const copy = document.createElement("span");
    copy.className = "suggestion-copy";
    const title = document.createElement("strong");
    title.className = "suggestion-title";
    title.textContent = book.title;
    const meta = document.createElement("span");
    meta.className = "suggestion-meta";
    const details = [authorText(book), publicationDateText(book), pageCountText(book, "Seitenzahl unbekannt")]
      .filter(Boolean)
      .join(" · ");
    meta.textContent = details;
    if (book.suggestion_source === "collection") {
      const source = document.createElement("span");
      source.className = "suggestion-meta suggestion-source";
      source.textContent = "In deiner Sammlung";
      copy.append(title, meta, source);
    } else {
      copy.append(title, meta);
    }
    main.append(copy);
    main.addEventListener("click", () => selectSuggestion(index));
    main.addEventListener("mouseenter", () => updateActiveSuggestion(index));

    const wishlist = document.createElement("button");
    wishlist.className = "button button-secondary suggestion-wishlist";
    wishlist.type = "button";
    if (isInCollection(book)) {
      wishlist.textContent = "Gespeichert";
      wishlist.disabled = true;
    } else {
      wishlist.textContent = "＋ Wunschliste";
      wishlist.setAttribute("aria-label", `${book.title} zur Wunschliste hinzufügen`);
      wishlist.addEventListener("click", () => addSearchBook(book, "want_to_read", wishlist, true));
    }
    row.append(main, wishlist);
    searchSuggestions.append(row);
  });

  if (!state.suggestions.length) {
    const status = document.createElement("p");
    status.className = "suggestion-status";
    status.textContent = loading
      ? "Vorschläge werden gesucht …"
      : failed ? "Vorschläge sind gerade nicht verfügbar." : "Keine direkten Vorschläge gefunden.";
    searchSuggestions.append(status);
  }

  const all = document.createElement("button");
  all.className = "suggestion-all";
  all.type = "button";
  all.textContent = `Alle Ergebnisse für „${query}“`;
  all.addEventListener("click", () => executeSearch(query));
  searchSuggestions.append(all);
  searchSuggestions.hidden = false;
  searchInput.setAttribute("aria-expanded", "true");
}

async function cachedBookSearch(query, signal, suggestions = false) {
  const resultLimit = suggestions ? 6 : state.searchResultLimit;
  const providers = `${state.primaryProvider}:${state.fallbackProvider}`;
  const key = `${providers}:${suggestions ? "suggest" : "search"}:${resultLimit}:${normalizeSearch(query)}`;
  const cached = searchCache.get(key);
  if (cached && Date.now() - cached.savedAt < SEARCH_CACHE_TTL) return cached.results;
  const mode = suggestions ? "&suggest=1" : "";
  const limit = suggestions ? "" : `&limit=${resultLimit}`;
  const providerQuery = `&primary_provider=${encodeURIComponent(state.primaryProvider)}&fallback_provider=${encodeURIComponent(state.fallbackProvider)}`;
  const payload = await api(`/api/search?q=${encodeURIComponent(query)}${mode}${limit}${providerQuery}`, { signal });
  // Nur echte Treffer cachen. Eine vorübergehend leere Antwort soll beim
  // nächsten Versuch wieder Open Library erreichen.
  if (payload.results.length) searchCache.set(key, { results: payload.results, savedAt: Date.now() });
  else searchCache.delete(key);
  return payload.results;
}

function queueSuggestionSearch() {
  const query = searchInput.value.trim();
  clearTimeout(suggestionTimer);
  suggestionController?.abort();
  state.suggestionQuery = query;
  if (query.length < 3) {
    state.suggestions = [];
    hideSuggestions();
    return;
  }

  const reusableRemote = state.remoteSuggestions.filter((book) => fuzzyBookScore(book, query) >= 0);
  state.suggestions = combinedSuggestions(query, reusableRemote);
  renderSuggestions(query, { loading: true });
  const isbnLike = /^[\dXx\s-]{10,17}$/.test(query);
  suggestionTimer = setTimeout(async () => {
    suggestionController = new AbortController();
    try {
      const remote = await cachedBookSearch(query, suggestionController.signal, true);
      if (searchInput.value.trim() !== query) return;
      state.remoteSuggestions = remote;
      state.suggestions = combinedSuggestions(query, remote);
      renderSuggestions(query);
    } catch (error) {
      if (error.name === "AbortError" || searchInput.value.trim() !== query) return;
      state.suggestions = combinedSuggestions(query, reusableRemote);
      renderSuggestions(query, { failed: true });
    }
  }, isbnLike ? 0 : SUGGESTION_DELAY);
}

function selectSuggestion(index) {
  const book = state.suggestions[index];
  if (!book) return;
  searchInput.value = book.title;
  executeSearch(book.title);
}

function renderLibrary() {
  loadingState.hidden = true;
  grid.replaceChildren();
  const filtered = state.filter === "all"
    ? state.books
    : state.books.filter((book) => (
      state.filter === "owned" ? book.is_owned : book.status === state.filter
    ));
  const visible = sortBooks(filtered);
  updateCounts(visible.length);
  if (state.libraryMode === "series") renderGroupedLibrary(visible);
  else visible.forEach((book) => grid.append(libraryCard(book)));
  emptyState.hidden = visible.length !== 0;
}

function sortBooks(books) {
  return [...books].sort((left, right) => {
    if (state.sort === "rating_desc" || state.sort === "rating_asc") {
      const leftRated = Number.isInteger(left.rating);
      const rightRated = Number.isInteger(right.rating);
      if (leftRated !== rightRated) return leftRated ? -1 : 1;
      const ratingDifference = state.sort === "rating_desc"
        ? (right.rating || 0) - (left.rating || 0)
        : (left.rating || 0) - (right.rating || 0);
      if (ratingDifference) return ratingDifference;
    } else if (state.sort === "title_asc" || state.sort === "title_desc") {
      const titleDifference = titleCollator.compare(left.title, right.title);
      return state.sort === "title_asc" ? titleDifference : -titleDifference;
    } else {
      const newestFirst = (Date.parse(right.created_at || "") || 0) - (Date.parse(left.created_at || "") || 0);
      const dateDifference = state.sort === "added_asc" ? -newestFirst : newestFirst;
      if (dateDifference) return dateDifference;
      return state.sort === "added_asc"
        ? (left.id || 0) - (right.id || 0)
        : (right.id || 0) - (left.id || 0);
    }
    return titleCollator.compare(left.title, right.title);
  });
}

function seriesKeyForBook(book) {
  const series = state.seriesIndex.get(book.id);
  if (!series) return null;
  return series.provider_series_id || `name:${normalizeSearch(series.name)}`;
}

function renderGroupedLibrary(visibleBooks) {
  const renderedSeries = new Set();
  visibleBooks.forEach((book) => {
    const seriesKey = seriesKeyForBook(book);
    if (!seriesKey) {
      grid.append(libraryCard(book));
      return;
    }
    if (renderedSeries.has(seriesKey)) return;
    renderedSeries.add(seriesKey);
    const books = visibleBooks.filter((candidate) => seriesKeyForBook(candidate) === seriesKey);
    grid.append(seriesCollectionCard(seriesKey, books));
  });
  const count = document.querySelector("#view-count");
  const suffix = renderedSeries.size === 1 ? "1 Reihe" : `${renderedSeries.size} Reihen`;
  if (renderedSeries.size) count.textContent = `${visibleBooks.length} ${visibleBooks.length === 1 ? "Buch" : "Bücher"} · ${suffix}`;
}

function seriesCollectionCard(seriesKey, books) {
  const series = state.seriesIndex.get(books[0].id);
  const article = document.createElement("article");
  article.className = "book-card series-collection-card";
  if (IS_MOBILE_UI) article.classList.add("android-open-card");

  const cover = document.createElement("div");
  cover.className = "book-cover-wrap series-cover-stack book-detail-trigger";
  cover.tabIndex = 0;
  cover.setAttribute("role", "button");
  cover.setAttribute("aria-label", `${series.name} öffnen`);
  const coveredBooks = books.filter((book) => book.cover_src || book.cover_url).slice(0, 3);
  if (coveredBooks.length) {
    coveredBooks.forEach((book) => {
      const image = document.createElement("img");
      image.className = "series-stack-cover";
      image.src = book.cover_src || book.cover_url;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => image.remove(), { once: true });
      cover.append(image);
    });
  } else {
    cover.append(placeholderCover(series.name));
  }
  const badge = document.createElement("span");
  badge.className = "series-collection-badge";
  badge.textContent = "Reihe";
  cover.append(badge);

  const open = () => openCollectionDialog(seriesKey);
  cover.addEventListener("click", open);
  cover.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
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
  titleButton.textContent = series.name;
  titleButton.addEventListener("click", open);
  title.append(titleButton);
  const count = document.createElement("p");
  count.className = "book-author";
  count.textContent = `${books.length} ${books.length === 1 ? "gespeichertes Buch" : "gespeicherte Bücher"}`;
  const titles = document.createElement("p");
  titles.className = "series-title-preview";
  titles.textContent = books.map((book) => book.title).join(" · ");
  meta.append(title, count, titles);

  const button = document.createElement("button");
  button.className = "button button-secondary";
  button.type = "button";
  button.textContent = "Bücher anzeigen";
  button.addEventListener("click", open);
  body.append(meta, button);
  article.append(cover, body);
  if (IS_MOBILE_UI) {
    article.addEventListener("click", (event) => {
      if (event.target.closest("button, select, a, input, textarea, .book-detail-trigger")) return;
      open();
    });
  }
  return article;
}

async function ensureSeriesIndex(books) {
  if (state.seriesIndexLoading) return;
  state.seriesIndexLoading = true;
  const unresolved = books.filter((book) => !state.seriesIndex.has(book.id));
  unresolved.filter((book) => !book.provider_book_id).forEach((book) => state.seriesIndex.set(book.id, null));
  const catalogueBooks = unresolved.filter((book) => book.provider_book_id);
  let cursor = 0;
  let failures = 0;
  let pending = 0;
  async function worker() {
    while (cursor < catalogueBooks.length) {
      const book = catalogueBooks[cursor];
      cursor += 1;
      try {
        const payload = await api(`/api/books/${book.id}/series`);
        if (payload.series || payload.status === "no_series") {
          state.seriesIndex.set(book.id, payload.series);
        }
        if (payload.status !== "ready" && payload.status !== "no_series") {
          pending += 1;
        }
      } catch (_error) {
        failures += 1;
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, catalogueBooks.length) }, () => worker()));
  state.seriesIndexLoading = false;
  if (failures) showToast(`${failures} Reihen konnten gerade nicht abgefragt werden.`, true);
  clearTimeout(groupingPollTimer);
  if ((pending || failures) && state.libraryMode === "series") {
    groupingPollTimer = setTimeout(async () => {
      await ensureSeriesIndex(state.books);
      if (state.libraryMode === "series") renderLibrary();
    }, 1600);
  }
}

function openCollectionDialog(seriesKey) {
  state.activeSeriesKey = seriesKey;
  state.collectionSeriesExpanded = false;
  renderCollectionDialog(seriesKey);
  collectionDialog.showModal();
}

function renderCollectionDialog(seriesKey) {
  const books = state.books.filter((book) => seriesKeyForBook(book) === seriesKey);
  if (!books.length) {
    if (collectionDialog.open) collectionDialog.close();
    return;
  }
  const series = state.seriesIndex.get(books[0].id);
  document.querySelector("#collection-dialog-title").textContent = series.name;
  document.querySelector("#collection-dialog-count").textContent = `${books.length} ${books.length === 1 ? "gespeichertes Buch" : "gespeicherte Bücher"}`;
  collectionBookList.replaceChildren(...books.map(collectionBookRow));
  const otherBooks = (series.books || []).filter((book) => !findCollectionBook(book));
  collectionOtherSeries.hidden = otherBooks.length === 0;
  collectionOtherList.replaceChildren(...otherBooks.map(collectionOtherBookRow));
  const volumeLabel = otherBooks.length === 1 ? "1 weiteren Band" : `${otherBooks.length} weitere Bände`;
  collectionOtherToggleLabel.textContent = state.collectionSeriesExpanded
    ? `${volumeLabel} ausblenden`
    : `${volumeLabel} anzeigen`;
  collectionOtherToggle.setAttribute("aria-expanded", String(state.collectionSeriesExpanded));
  collectionOtherToggle.querySelector(".collection-other-chevron").textContent = state.collectionSeriesExpanded ? "⌃" : "⌄";
  collectionOtherList.hidden = !state.collectionSeriesExpanded;
}

function collectionBookRow(book) {
  const row = document.createElement("div");
  row.className = "collection-book-row";
  row.append(suggestionCover(book));

  const copy = document.createElement("div");
  copy.className = "collection-book-copy";
  const title = document.createElement("strong");
  title.textContent = book.title;
  const author = document.createElement("span");
  author.textContent = authorText(book);
  copy.append(title, author);

  const select = statusSelect(book.status);
  select.addEventListener("change", async () => {
    const previous = book.status;
    select.disabled = true;
    try {
      await api(`/api/books/${book.id}`, { method: "PATCH", body: JSON.stringify({ status: select.value }) });
      await loadBooks();
      showToast(`„${book.title}“ ist jetzt in „${STATUS_LABELS[select.value]}“.`);
    } catch (error) {
      select.value = previous;
      select.disabled = false;
      showToast(`Nicht gespeichert: ${error.message}`, true);
    }
  });

  const review = document.createElement("button");
  review.className = "collection-review-button review-book-button";
  if (book.rating) review.classList.add("rated");
  review.type = "button";
  review.textContent = book.rating ? `★ ${book.rating}` : "☆";
  review.title = book.rating || book.review ? "Bewertung bearbeiten" : "Buch bewerten";
  review.setAttribute("aria-label", `${book.title} bewerten`);
  review.addEventListener("click", () => {
    collectionDialog.close();
    openReview(book);
  });

  const remove = document.createElement("button");
  remove.className = "icon-button series-book-delete";
  remove.type = "button";
  setRemoveButtonAppearance(remove);
  remove.title = "Aus Sammlung entfernen";
  remove.setAttribute("aria-label", `${book.title} aus der Sammlung entfernen`);
  remove.addEventListener("click", () => {
    collectionDialog.close();
    deleteBook(book, remove);
  });

  const actions = document.createElement("div");
  actions.className = "collection-book-actions";
  actions.append(select, remove, review, collectionInfoButton(book));
  row.append(copy, actions);
  return row;
}

function collectionInfoButton(book) {
  const info = document.createElement("button");
  info.className = "icon-button series-info-button";
  info.type = "button";
  info.textContent = BOOK_INFO_SYMBOL;
  info.title = "Weitere Buchinformationen";
  info.setAttribute("aria-label", `Weitere Informationen zu ${book.title} anzeigen`);
  info.addEventListener("click", () => {
    collectionDialog.close();
    openBookDetails(book, "info");
  });
  return info;
}

function collectionOtherBookRow(book) {
  const displayBook = enrichKnownBookMetadata(book);
  const row = document.createElement("div");
  row.className = "collection-book-row collection-other-book-row";
  row.append(suggestionCover(displayBook));

  const copy = document.createElement("div");
  copy.className = "collection-book-copy";
  const title = document.createElement("strong");
  title.textContent = displayBook.title;
  const details = document.createElement("span");
  details.textContent = [authorText(displayBook), pageCountText(displayBook, "Seitenzahl unbekannt")].filter(Boolean).join(" · ");
  copy.append(title, details);

  const select = statusSelect("want_to_read");
  const add = document.createElement("button");
  add.className = "button button-secondary collection-book-add";
  add.type = "button";
  add.textContent = "Hinzufügen";
  add.setAttribute("aria-label", `${displayBook.title} zur Sammlung hinzufügen`);
  add.addEventListener("click", () => addSeriesBook(displayBook, select.value, add));

  const review = document.createElement("button");
  review.className = "collection-review-button review-book-button";
  review.type = "button";
  review.textContent = "☆";
  review.title = "Direkt bewerten";
  review.setAttribute("aria-label", `${displayBook.title} direkt bewerten`);
  review.addEventListener("click", () => {
    collectionDialog.close();
    openReview(displayBook);
  });

  const actions = document.createElement("div");
  actions.className = "collection-book-actions";
  actions.append(select, add, review, collectionInfoButton(displayBook));
  row.append(copy, actions);
  return row;
}

function libraryCard(book) {
  const article = document.createElement("article");
  article.className = "book-card";
  if (IS_MOBILE_UI) article.classList.add("android-open-card");
  const cover = coverElement(book);
  cover.classList.add("book-detail-trigger");
  cover.tabIndex = 0;
  cover.setAttribute("role", "button");
  cover.setAttribute("aria-label", `Details und Reihe von ${book.title} anzeigen`);
  cover.addEventListener("click", () => openBookDetails(book));
  cover.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openBookDetails(book);
    }
  });
  article.append(cover);

  const body = document.createElement("div");
  body.className = "book-body";
  const meta = document.createElement("div");
  meta.className = "book-meta";
  const title = document.createElement("h3");
  title.className = "book-title";
  const titleButton = document.createElement("button");
  titleButton.className = "book-title-link";
  titleButton.type = "button";
  titleButton.textContent = book.title;
  titleButton.setAttribute("aria-label", `Details und Reihe von ${book.title} anzeigen`);
  titleButton.addEventListener("click", () => openBookDetails(book));
  title.append(titleButton);
  const author = document.createElement("p");
  author.className = "book-author";
  author.textContent = authorText(book);
  meta.append(title, author);
  const heading = document.createElement("div");
  heading.className = "book-card-heading";
  heading.append(meta, createBookInfoButton(book));
  body.append(heading);

  if (book.rating) {
    const rating = document.createElement("p");
    rating.className = "rating-display";
    rating.textContent = `${"★".repeat(book.rating)}${"☆".repeat(5 - book.rating)}`;
    const hidden = document.createElement("span");
    hidden.textContent = `${book.rating}/5`;
    rating.append(hidden);
    body.append(rating);
  }
  if (book.review) {
    const review = document.createElement("button");
    review.className = "review-excerpt";
    review.type = "button";
    review.textContent = `„${book.review}“`;
    review.title = "Vollständige Bewertung anzeigen";
    review.setAttribute("aria-label", `Vollständige Bewertung zu ${book.title} anzeigen`);
    review.addEventListener("click", () => openReviewReader(book));
    body.append(review);
  }

  const actions = document.createElement("div");
  actions.className = "card-actions";
  const select = statusSelect(book.status);
  select.addEventListener("change", async () => {
    const previous = book.status;
    select.disabled = true;
    try {
      await api(`/api/books/${book.id}`, { method: "PATCH", body: JSON.stringify({ status: select.value }) });
      showToast(`„${book.title}“ ist jetzt in „${STATUS_LABELS[select.value]}“.`);
      await loadBooks();
    } catch (error) {
      select.value = previous;
      showToast(`Nicht gespeichert: ${error.message}`, true);
    } finally { select.disabled = false; }
  });
  const row = document.createElement("div");
  row.className = "card-action-row";
  const reviewButton = document.createElement("button");
  reviewButton.className = "button button-secondary review-book-button";
  reviewButton.type = "button";
  reviewButton.textContent = book.rating || book.review ? "Bewertung bearbeiten" : "Bewerten";
  if (book.rating) {
    reviewButton.classList.add("rated");
    reviewButton.dataset.rating = String(book.rating);
  }
  reviewButton.setAttribute("aria-label", `${book.title} bewerten`);
  reviewButton.title = book.rating || book.review ? "Bewertung bearbeiten" : "Buch bewerten";
  reviewButton.addEventListener("click", () => openReview(book));
  const deleteButton = document.createElement("button");
  deleteButton.className = "icon-button";
  deleteButton.type = "button";
  deleteButton.setAttribute("aria-label", `${book.title} entfernen`);
  deleteButton.title = "Aus Sammlung entfernen";
  setRemoveButtonAppearance(deleteButton);
  deleteButton.addEventListener("click", () => deleteBook(book, deleteButton));
  row.append(reviewButton, deleteButton);
  actions.append(select, row);
  body.append(actions);
  article.append(body);
  if (IS_MOBILE_UI) {
    article.addEventListener("click", (event) => {
      if (event.target.closest("button, select, a, input, textarea, .book-detail-trigger")) return;
      openBookDetails(book);
    });
  }
  return article;
}

function setBookDialogView(view, moveFocus = false) {
  const showInfo = view === "info";
  bookDialogMainView.hidden = showInfo;
  bookDialogInfoView.hidden = !showInfo;
  bookDialogInfoButton.hidden = showInfo;
  document.querySelector("#book-dialog-kicker").textContent = showInfo
    ? "Buchinformationen"
    : "Buchdetails";
  if (showInfo) renderBookInfo();
  if (moveFocus) (showInfo ? bookInfoBackButton : bookDialogInfoButton).focus();
}

function displayLanguage(value) {
  const code = String(value || "").replace(/^\/languages\//, "").toLocaleLowerCase("de");
  return LANGUAGE_LABELS[code] || value;
}

function displayProvider(value) {
  return {
    open_library: "Open Library",
    google_books: "Google Books",
    manual: "Manuell erfasst",
  }[value] || "Unbekannter Katalog";
}

function renderBookInfo() {
  const metadata = state.detailMetadata || state.infoBook || state.detailBook || {};
  const provider = metadata.provider || state.infoBook?.provider || state.detailBook?.provider || "manual";
  const fields = [
    ["ISBN", metadata.isbn],
    ["Verlag", metadata.publisher],
    ["Erscheinungsdatum", formatPublicationDate(metadata.publish_date || metadata.first_publish_year)],
    ["Seitenzahl", pageCountText(metadata)],
    ["Sprache", displayLanguage(metadata.language)],
    ["Format", metadata.physical_format],
    ["Untertitel", metadata.subtitle],
    ["Originaltitel", metadata.original_title],
  ].filter(([, value]) => value);

  bookInfoGrid.replaceChildren();
  fields.forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "book-info-item";
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    item.append(term, description);
    bookInfoGrid.append(item);
  });

  const descriptionCopy = document.querySelector("#book-description-copy");
  descriptionCopy.textContent = metadata.description || "";
  bookDescriptionSection.hidden = !metadata.description;
  updateDescriptionExpansion(metadata.description || "");

  const subjectSection = document.querySelector("#book-subjects");
  const subjectList = document.querySelector("#book-subject-list");
  const subjects = Array.isArray(metadata.subjects) ? metadata.subjects.filter(Boolean) : [];
  subjectList.replaceChildren(...subjects.map((subject) => {
    const chip = document.createElement("span");
    chip.textContent = subject;
    return chip;
  }));
  subjectSection.hidden = subjects.length === 0;

  if (!state.detailMetadataLoaded) {
    bookInfoStatus.textContent = "Weitere Informationen werden geladen …";
  } else if (state.detailMetadataUnavailable) {
    bookInfoStatus.textContent = fields.length || metadata.description
      ? "Weitere Angaben sind momentan nicht erreichbar. Verfügbare Daten werden angezeigt."
      : "Weitere Buchinformationen sind momentan nicht erreichbar.";
  } else if (!fields.length && !metadata.description && !subjects.length) {
    bookInfoStatus.textContent = "Für dieses Buch sind keine zusätzlichen Informationen verfügbar.";
  } else {
    bookInfoStatus.textContent = "";
  }
  bookInfoSource.textContent = `Quelle: ${displayProvider(provider)}`;
}

function updateDescriptionExpansion(description) {
  const copy = document.querySelector("#book-description-copy");
  const canExpand = String(description || "").trim().length > 260;
  copy.classList.toggle("collapsed", canExpand && !state.descriptionExpanded);
  bookDescriptionSection.classList.toggle("expandable", canExpand);
  bookDescriptionToggle.hidden = !canExpand;
  bookDescriptionToggle.textContent = state.descriptionExpanded ? "Weniger anzeigen" : "Mehr anzeigen";
  bookDescriptionToggle.setAttribute("aria-expanded", String(state.descriptionExpanded));
}

async function loadBookMetadata(book, metadataIdentity) {
  clearTimeout(metadataPollTimer);
  state.detailMetadataIdentity = metadataIdentity;
  state.detailMetadata = { ...book };
  state.detailMetadataLoaded = false;
  state.detailMetadataUnavailable = false;
  renderBookInfo();
  if (!book.provider_book_id) {
    state.detailMetadataLoaded = true;
    renderBookInfo();
    return;
  }

  const url = book.id
    ? `/api/books/${book.id}/metadata`
    : `/api/metadata?provider=${encodeURIComponent(book.provider || "open_library")}&provider_book_id=${encodeURIComponent(book.provider_book_id)}${book.provider_edition_id ? `&provider_edition_id=${encodeURIComponent(book.provider_edition_id)}` : ""}`;
  try {
    const payload = await api(url);
    if (metadataIdentityForBook(state.infoBook) !== metadataIdentity) return;
    state.detailMetadata = mergeLoadedBookMetadata(book, payload.metadata || {});
    state.detailMetadataIdentity = metadataIdentityForBook(book);
    if (["pending", "running", "retry"].includes(payload.status)) {
      state.detailMetadataLoaded = false;
      state.detailMetadataUnavailable = false;
      renderBookInfo();
      scheduleMetadataPoll(url, book, state.detailMetadataIdentity, 1);
      return;
    }
    state.detailMetadataLoaded = true;
    state.detailMetadataUnavailable = payload.status === "unavailable";
    renderBookInfo();
  } catch (_error) {
    if (metadataIdentityForBook(state.infoBook) !== metadataIdentity) return;
    state.detailMetadataUnavailable = true;
    state.detailMetadataLoaded = true;
    renderBookInfo();
  }
}

function scheduleMetadataPoll(url, book, metadataIdentity, attempt) {
  clearTimeout(metadataPollTimer);
  const delay = Math.min(5000, 650 + attempt * 250);
  metadataPollTimer = setTimeout(async () => {
    if (!bookDialog.open || metadataIdentityForBook(state.infoBook) !== metadataIdentity) return;
    try {
      const payload = await api(url);
      if (!bookDialog.open || metadataIdentityForBook(state.infoBook) !== metadataIdentity) return;
      state.detailMetadata = mergeLoadedBookMetadata(book, payload.metadata || {});
      state.detailMetadataIdentity = metadataIdentityForBook(book);
      if (["pending", "running", "retry"].includes(payload.status)) {
        renderBookInfo();
        scheduleMetadataPoll(url, book, state.detailMetadataIdentity, attempt + 1);
        return;
      }
      state.detailMetadataLoaded = true;
      state.detailMetadataUnavailable = payload.status === "unavailable";
      renderBookInfo();
    } catch (_error) {
      scheduleMetadataPoll(url, book, metadataIdentity, attempt + 1);
    }
  }, delay);
}

function renderBookDialogHeader(book) {
  document.querySelector("#book-dialog-title").textContent = book.title;
  document.querySelector("#book-dialog-author").textContent = authorText(book);
  const original = document.querySelector("#book-dialog-original");
  const originalParts = [book.original_title, book.original_authors?.[0]].filter(Boolean);
  original.textContent = originalParts.length ? `Original: ${originalParts.join(" · ")}` : "";
  original.hidden = originalParts.length === 0;
}

function openBookInfo(book) {
  const savedBook = findCollectionBook(book);
  const infoBook = savedBook ? mergeKnownBookMetadata(book, savedBook) : book;
  const infoMetadataIdentity = metadataIdentityForBook(infoBook);
  state.infoBook = infoBook;
  renderBookDialogHeader(infoBook);
  if (state.detailMetadataIdentity !== infoMetadataIdentity) {
    state.descriptionExpanded = false;
    loadBookMetadata(infoBook, infoMetadataIdentity);
  }
  setBookDialogView("info", true);
}

function returnToBookDetails() {
  if (!state.detailBook) return;
  state.infoBook = state.detailBook;
  renderBookDialogHeader(state.detailBook);
  setBookDialogView("main", true);
}

async function openBookDetails(book, initialView = "main") {
  const savedBook = findCollectionBook(book);
  const detailBook = savedBook ? mergeKnownBookMetadata(book, savedBook) : book;
  const detailIdentity = suggestionIdentity(detailBook);
  const detailMetadataIdentity = metadataIdentityForBook(detailBook);
  state.detailBook = detailBook;
  state.infoBook = detailBook;
  state.descriptionExpanded = false;
  state.seriesData = null;
  state.seriesLoaded = false;
  state.seriesStatus = null;
  state.detailSeriesExpanded = false;
  state.readingHistoryExpanded = false;
  renderBookDialogHeader(detailBook);
  loadBookMetadata(detailBook, detailMetadataIdentity);
  setBookDialogView(initialView);
  renderReadingHistory(savedBook || detailBook);
  seriesHeading.textContent = "Reiheninformationen";
  seriesPosition.hidden = true;
  seriesNote.textContent = "";
  seriesContent.classList.add("series-loading");
  seriesContent.textContent = "Reiheninformationen werden geladen …";
  bookDialog.showModal();

  try {
    const seriesUrl = detailBook.id
      ? `/api/books/${detailBook.id}/series`
      : `/api/series?provider=${encodeURIComponent(detailBook.provider || "open_library")}&provider_book_id=${encodeURIComponent(detailBook.provider_book_id || "")}${(detailBook.authors || []).map((author) => `&author=${encodeURIComponent(author)}`).join("")}`;
    state.seriesRequestUrl = seriesUrl;
    const payload = await api(seriesUrl);
    if (suggestionIdentity(state.detailBook || {}) !== detailIdentity) return;
    applySeriesPayload(payload, seriesUrl, detailIdentity);
  } catch (error) {
    if (suggestionIdentity(state.detailBook || {}) !== detailIdentity) return;
    state.seriesData = null;
    state.seriesLoaded = true;
    renderSeriesDetails();
    seriesHeading.textContent = "Reihe gerade nicht verfügbar";
    seriesNote.textContent = `${error.message} Das angeklickte Buch kannst du trotzdem bearbeiten.`;
  }
}

function renderReadingHistory(book) {
  readingHistoryList.replaceChildren();
  readingHistory.hidden = !book?.id;
  if (!book?.id) return;

  setReadingHistoryExpanded(state.readingHistoryExpanded);

  STATUS_HISTORY.forEach(({ status, field, label }) => {
    const item = document.createElement("div");
    item.className = "reading-milestone";
    if (book.status === status) {
      item.classList.add("current");
      item.setAttribute("aria-current", "step");
    }
    const header = document.createElement("div");
    header.className = "reading-milestone-header";
    const name = document.createElement("span");
    name.textContent = label;
    header.append(name);
    if (book.status === status) {
      const current = document.createElement("small");
      current.textContent = "Aktuell";
      header.append(current);
    }
    const timestamp = document.createElement("strong");
    timestamp.textContent = formatReadingDate(book[field]);
    item.append(header, timestamp);
    readingHistoryList.append(item);
  });
}

function setReadingHistoryExpanded(expanded) {
  state.readingHistoryExpanded = Boolean(expanded);
  readingHistoryToggle.hidden = false;
  readingHistoryList.hidden = !state.readingHistoryExpanded;
  readingHistoryToggle.setAttribute("aria-expanded", String(state.readingHistoryExpanded));
  readingHistoryToggle.querySelector("span:first-child").textContent = state.readingHistoryExpanded
    ? "Einklappen"
    : "Ausklappen";
  readingHistoryToggle.querySelector(".reading-history-chevron").textContent = state.readingHistoryExpanded
    ? "⌃"
    : "⌄";
}

function formatReadingDate(value) {
  if (!value) return "Nicht erfasst";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Nicht erfasst";
  const formattedDate = formatDateParts({
    year: date.getFullYear(),
    month: date.getMonth() + 1,
    day: date.getDate(),
  });
  const time = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  return `${formattedDate}, ${time}`;
}

function applySeriesPayload(payload, seriesUrl, detailIdentity, attempt = 0) {
  const status = payload.status || (payload.series ? "ready" : "no_series");
  state.seriesData = payload.series;
  state.seriesLoaded = true;
  state.seriesStatus = status;
  renderSeriesDetails();
  if (status === "ready" || status === "no_series") {
    clearTimeout(seriesPollTimer);
    return;
  }

  if (!payload.series) seriesHeading.textContent = "Reihe wird im Hintergrund geladen";
  seriesNote.textContent = status === "retry"
    ? "Die Reihendaten konnten gerade nicht aktualisiert werden. Vorhandene Angaben bleiben sichtbar; ein neuer Versuch läuft automatisch."
    : "Du kannst die App weiter benutzen. Diese Ansicht aktualisiert sich automatisch.";
  scheduleSeriesPoll(seriesUrl, detailIdentity, attempt + 1);
}

function scheduleSeriesPoll(seriesUrl, detailIdentity, attempt) {
  clearTimeout(seriesPollTimer);
  // Dieser Request liest nur SQLite. Externe Wiederholungen übernimmt ausschließlich
  // der Hintergrund-Worker, deshalb kann das geöffnete Fenster günstig weiter pollen.
  const delay = Math.min(5000, 700 + attempt * 250);
  seriesPollTimer = setTimeout(async () => {
    if (!bookDialog.open || suggestionIdentity(state.detailBook || {}) !== detailIdentity) return;
    try {
      const payload = await api(seriesUrl);
      if (!bookDialog.open || suggestionIdentity(state.detailBook || {}) !== detailIdentity) return;
      applySeriesPayload(payload, seriesUrl, detailIdentity, attempt);
    } catch (_error) {
      scheduleSeriesPoll(seriesUrl, detailIdentity, attempt + 1);
    }
  }, delay);
}

function renderSeriesDetails() {
  const series = state.seriesData;
  seriesContent.classList.remove("series-loading");
  seriesContent.replaceChildren();
  seriesPosition.hidden = true;

  if (!series) {
    seriesHeading.textContent = "Keine Reihe gefunden";
    const list = document.createElement("div");
    list.className = "series-list";
    if (state.detailBook) list.append(seriesBookRow(state.detailBook));
    seriesContent.append(list);
    seriesNote.textContent = "Bei manuell angelegten Büchern und einigen Katalogeinträgen fehlen diese Daten.";
    return;
  }

  seriesHeading.textContent = series.name;
  if (series.current_position) {
    seriesPosition.textContent = `Band ${series.current_position}`;
    seriesPosition.hidden = false;
  }

  const books = [...series.books];
  const includesCurrent = books.some((book) => sameProviderBook(book, state.detailBook));
  if (!includesCurrent && state.detailBook) books.unshift(state.detailBook);
  const isCurrentBook = (book) => sameProviderBook(book, state.detailBook);
  const visibleBooks = books.filter((book) => findCollectionBook(book) || isCurrentBook(book));
  const otherBooks = books.filter((book) => !findCollectionBook(book) && !isCurrentBook(book));
  const list = document.createElement("div");
  list.className = "series-list";
  visibleBooks.forEach((book) => list.append(seriesBookRow(book)));
  seriesContent.append(list);

  if (otherBooks.length) {
    const more = document.createElement("section");
    more.className = "series-other-books";
    const toggle = document.createElement("button");
    toggle.className = "series-other-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(state.detailSeriesExpanded));
    const volumeLabel = otherBooks.length === 1 ? "1 weiteren Band" : `${otherBooks.length} weitere Bände`;
    const toggleLabel = document.createElement("span");
    toggleLabel.textContent = `${volumeLabel} ${state.detailSeriesExpanded ? "ausblenden" : "anzeigen"}`;
    const toggleChevron = document.createElement("span");
    toggleChevron.setAttribute("aria-hidden", "true");
    toggleChevron.textContent = state.detailSeriesExpanded ? "⌃" : "⌄";
    toggle.append(toggleLabel, toggleChevron);
    const otherList = document.createElement("div");
    otherList.className = "series-list series-other-list";
    otherList.hidden = !state.detailSeriesExpanded;
    otherBooks.forEach((book) => otherList.append(seriesBookRow(book)));
    toggle.addEventListener("click", () => {
      state.detailSeriesExpanded = !state.detailSeriesExpanded;
      renderSeriesDetails();
    });
    more.append(toggle, otherList);
    seriesContent.append(more);
  }

  if (series.source === "google_title") {
    seriesNote.textContent = "";
  } else if (series.source === "google_structured") {
    seriesNote.textContent = "Google Books liefert die Reihenzuordnung strukturiert; einzelne Ausgaben können trotzdem fehlen.";
  } else if (series.source === "subject") {
    seriesNote.textContent = "Hinweis: Diese Zuordnung stammt aus Schlagwörtern und kann unvollständig sein.";
  } else {
    seriesNote.textContent = "Reihendaten aus dem Buchkatalog. Einzelne Ausgaben oder Sonderbände können fehlen.";
  }
}

function seriesBookRow(book) {
  const isCurrent = sameProviderBook(book, state.detailBook);
  const saved = findCollectionBook(book);
  const knownBook = saved || (isCurrent ? state.detailBook : null);
  const displayBook = enrichKnownBookMetadata(
    knownBook ? mergeKnownBookMetadata(book, knownBook) : book,
  );
  const row = document.createElement("div");
  row.className = "series-book";
  if (isCurrent) row.classList.add("current");
  row.append(suggestionCover(book));

  const copy = document.createElement("div");
  copy.className = "series-book-copy";
  const position = document.createElement("span");
  position.className = "series-book-position";
  position.textContent = book.series_position
    ? `Band ${book.series_position}`
    : (!state.seriesData && isCurrent ? "Dieses Buch" : "Reihenzuordnung");
  const title = document.createElement("strong");
  title.textContent = book.title;
  const meta = document.createElement("span");
  meta.textContent = [
    authorText(displayBook),
    publicationDateText(displayBook),
    pageCountText(displayBook, "Seitenzahl unbekannt"),
  ].filter(Boolean).join(" · ");
  copy.append(position, title, meta);

  row.append(copy, seriesBookActions(displayBook));
  return row;
}

function seriesBookActions(book) {
  const actions = document.createElement("div");
  actions.className = "series-book-actions";
  const saved = findCollectionBook(book);
  if (!saved) {
    const select = statusSelect("want_to_read");
    select.classList.add("series-status-select");
    const add = document.createElement("button");
    add.className = "button button-secondary series-book-action";
    add.type = "button";
    add.textContent = "Hinzufügen";
    add.setAttribute("aria-label", `${book.title} zur Sammlung hinzufügen`);
    add.addEventListener("click", () => addSeriesBook(book, select.value, add));
    const review = document.createElement("button");
    review.className = "collection-review-button series-review-button review-book-button";
    review.type = "button";
    review.textContent = "☆";
    review.title = "Direkt bewerten";
    review.setAttribute("aria-label", `${book.title} direkt bewerten`);
    review.addEventListener("click", () => openReview(book));
    actions.append(select, add, review, createBookInfoButton(book, true));
    return actions;
  }

  const select = statusSelect(saved.status);
  select.classList.add("series-status-select");
  select.addEventListener("change", async () => {
    const previous = saved.status;
    select.disabled = true;
    try {
      await api(`/api/books/${saved.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: select.value }),
      });
      await loadBooks();
      showToast(`„${saved.title}“ ist jetzt in „${STATUS_LABELS[select.value]}“.`);
    } catch (error) {
      select.value = previous;
      select.disabled = false;
      showToast(`Nicht gespeichert: ${error.message}`, true);
    }
  });
  const review = document.createElement("button");
  review.className = "collection-review-button series-review-button review-book-button";
  if (saved.rating) review.classList.add("rated");
  review.type = "button";
  review.textContent = saved.rating ? `★ ${saved.rating}` : "☆";
  review.title = saved.rating || saved.review ? "Bewertung bearbeiten" : "Buch bewerten";
  review.setAttribute("aria-label", `${saved.title} bewerten`);
  review.addEventListener("click", () => openReview(saved));
  const remove = document.createElement("button");
  remove.className = "icon-button series-book-delete";
  remove.type = "button";
  setRemoveButtonAppearance(remove);
  remove.title = "Aus Sammlung entfernen";
  remove.setAttribute("aria-label", `${saved.title} aus der Sammlung entfernen`);
  remove.addEventListener("click", () => {
    bookDialog.close();
    deleteBook(saved, remove);
  });
  // Die Reihenfolge entspricht der visuellen Bedienung in der Detailansicht:
  // Status ändern, entfernen, bewerten und zuletzt die Metadaten öffnen.
  actions.append(select, remove, review, createBookInfoButton(saved, true));
  return actions;
}

async function addSeriesBook(book, status, button) {
  button.disabled = true;
  button.textContent = "Wird gespeichert …";
  try {
    await api("/api/books", {
      method: "POST",
      body: JSON.stringify({ ...book, status }),
    });
    await loadBooks();
    showToast(`„${book.title}“ wurde zu „${STATUS_LABELS[status]}“ hinzugefügt.`);
  } catch (error) {
    if (error.status === 409) await loadBooks();
    showToast(error.status === 409 ? "Dieses Buch ist bereits gespeichert." : `Nicht gespeichert: ${error.message}`, true);
  }
}

function renderSearchResults() {
  searchResults.replaceChildren();
  if (!state.searchResults.length) {
    const message = document.createElement("div");
    message.className = "empty-state";
    const heading = document.createElement("h3");
    heading.textContent = "Keine passenden Bücher gefunden";
    const copy = document.createElement("p");
    copy.textContent = "Die Buchkataloge liefern manchmal kurzzeitig keine Treffer. Versuche es erneut oder lege das Buch selbst an.";
    message.append(heading, copy);
    const actions = document.createElement("div");
    actions.className = "empty-state-actions";
    const retry = document.createElement("button");
    retry.className = "button button-secondary";
    retry.type = "button";
    retry.textContent = "Noch einmal suchen";
    retry.addEventListener("click", () => executeSearch(state.lastSearchQuery));
    const manual = document.createElement("button");
    manual.className = "button button-primary";
    manual.type = "button";
    manual.textContent = "Buch selbst anlegen";
    manual.addEventListener("click", () => manualDialog.showModal());
    actions.append(retry, manual);
    message.append(actions);
    searchResults.append(message);
    return;
  }
  state.searchResults.forEach((book) => searchResults.append(searchCard(book)));
}

function searchCard(book) {
  const article = document.createElement("article");
  article.className = "book-card search-card";
  const cover = coverElement(book);
  cover.classList.add("book-detail-trigger");
  cover.tabIndex = 0;
  cover.setAttribute("role", "button");
  cover.setAttribute("aria-label", `Details und Reihe von ${book.title} anzeigen`);
  cover.addEventListener("click", () => openBookDetails(book));
  cover.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openBookDetails(book);
    }
  });
  article.append(cover);
  const body = document.createElement("div");
  body.className = "book-body";
  const meta = document.createElement("div");
  meta.className = "book-meta";
  const title = document.createElement("h3");
  title.className = "book-title";
  const titleButton = document.createElement("button");
  titleButton.className = "book-title-link";
  titleButton.type = "button";
  titleButton.textContent = book.title;
  titleButton.setAttribute("aria-label", `Details und Reihe von ${book.title} anzeigen`);
  titleButton.addEventListener("click", () => openBookDetails(book));
  title.append(titleButton);
  const author = document.createElement("p");
  author.className = "book-author";
  author.textContent = authorText(book);
  meta.append(title, author);
  const publicationDetails = book._metadataHydrationPending
    ? ["Buchdaten werden geprüft …"]
    : [
      publicationDateText(book, true),
      pageCountText(book, "Seitenzahl unbekannt"),
    ].filter(Boolean);
  if (publicationDetails.length) {
    const year = document.createElement("p");
    year.className = "book-year";
    year.textContent = publicationDetails.join(" · ");
    meta.append(year);
  }
  const heading = document.createElement("div");
  heading.className = "book-card-heading";
  heading.append(meta, createBookInfoButton(book));
  body.append(heading);

  if (isInCollection(book)) {
    const added = document.createElement("div");
    added.className = "added-label";
    added.textContent = "✓ Bereits gespeichert";
    body.append(added);
  } else {
    const select = statusSelect("want_to_read");
    const add = document.createElement("button");
    add.className = "button button-primary";
    add.type = "button";
    add.textContent = "Hinzufügen";
    add.addEventListener("click", () => addSearchBook(book, select.value, add));
    const actions = document.createElement("div");
    actions.className = "card-actions";
    actions.append(select, add);
    body.append(actions);
  }
  article.append(body);
  return article;
}

function isInCollection(candidate) {
  return Boolean(findCollectionBook(candidate));
}

function findCollectionBook(candidate) {
  if (!candidate) return null;
  const identity = `${candidate.title}|${authorText(candidate)}`.toLocaleLowerCase("de");
  return state.books.find((book) =>
    (candidate.provider_book_id
      && (book.provider || "open_library") === (candidate.provider || "open_library")
      && book.provider_book_id === candidate.provider_book_id) ||
    (candidate.isbn && book.isbn === candidate.isbn) ||
    `${book.title}|${authorText(book)}`.toLocaleLowerCase("de") === identity
  ) || null;
}

async function addSearchBook(book, status, button, fromSuggestions = false) {
  button.disabled = true;
  button.textContent = "Wird gespeichert …";
  try {
    await api("/api/books", { method: "POST", body: JSON.stringify({ ...book, status }) });
    await loadBooks();
    if (!searchPanel.hidden) renderSearchResults();
    if (fromSuggestions && !searchSuggestions.hidden) renderSuggestions(state.suggestionQuery);
    showToast(`„${book.title}“ wurde zu „${STATUS_LABELS[status]}“ hinzugefügt.`);
  } catch (error) {
    showToast(error.status === 409 ? "Dieses Buch ist bereits gespeichert." : `Nicht gespeichert: ${error.message}`, true);
    if (error.status === 409) await loadBooks();
    if (!searchPanel.hidden) renderSearchResults();
    if (fromSuggestions && !searchSuggestions.hidden) renderSuggestions(state.suggestionQuery);
  }
}

function deleteBook(book, button) {
  pendingDelete = { book, button };
  document.querySelector("#delete-dialog-title").textContent = `„${book.title}“ entfernen?`;
  confirmDeleteButton.disabled = false;
  confirmDeleteButton.textContent = "Buch entfernen";
  deleteDialog.showModal();
}

async function confirmDelete() {
  if (!pendingDelete) return;
  const { book, button } = pendingDelete;
  button.disabled = true;
  confirmDeleteButton.disabled = true;
  confirmDeleteButton.textContent = "Wird entfernt …";
  try {
    await api(`/api/books/${book.id}`, { method: "DELETE" });
    await loadBooks();
    renderSearchResults();
    deleteDialog.close();
    showToast(`„${book.title}“ wurde entfernt.`);
  } catch (error) {
    showToast(`Nicht entfernt: ${error.message}`, true);
    button.disabled = false;
    confirmDeleteButton.disabled = false;
    confirmDeleteButton.textContent = "Buch entfernen";
  }
}

function openReview(book) {
  const form = document.querySelector("#review-form");
  const saved = findCollectionBook(book);
  const candidate = saved || book;
  state.reviewCandidate = candidate;
  form.reset();
  form.elements.book_id.value = saved?.id || "";
  form.elements.review.value = candidate.review || "";
  updateReviewCharacterCount();
  if (candidate.rating) form.querySelector(`[name="rating"][value="${candidate.rating}"]`).checked = true;
  document.querySelector("#review-book-title").textContent = candidate.title;
  document.querySelector("#delete-review").hidden = !saved;
  reviewDialog.showModal();
}

function updateReviewCharacterCount() {
  const length = reviewTextarea.value.length;
  reviewCharacterCount.textContent = `${length.toLocaleString("de-DE")} / ${state.reviewMaxLength.toLocaleString("de-DE")} Zeichen`;
  reviewCharacterCount.classList.toggle("limit-near", length >= state.reviewMaxLength * 0.9);
}

function openReviewReader(book) {
  document.querySelector("#review-reader-title").textContent = book.title;
  document.querySelector("#review-reader-author").textContent = authorText(book);
  const rating = document.querySelector("#review-reader-rating");
  const ratingValue = Number(book.rating);
  const validRating = Number.isInteger(ratingValue) && ratingValue >= 1 && ratingValue <= 5
    ? ratingValue
    : null;
  rating.textContent = validRating ? `${"★".repeat(validRating)} ${validRating}/5` : "";
  rating.hidden = !validRating;
  document.querySelector("#review-reader-copy").textContent = book.review || "";
  reviewReaderDialog.showModal();
}

function updateCounts(visibleCount) {
  const counts = {
    all: state.books.length,
    unread: 0,
    reading: 0,
    read: 0,
    want_to_read: 0,
    owned: 0,
  };
  state.books.forEach((book) => {
    counts[book.status] += 1;
    if (book.is_owned) counts.owned += 1;
  });
  for (const [key, value] of Object.entries(counts)) document.querySelector(`#count-${key}`).textContent = value;
  const content = VIEW_CONTENT[state.filter];
  document.querySelector("#library-heading").textContent = content.title;
  document.querySelector("#empty-title").textContent = content.emptyTitle;
  document.querySelector("#empty-copy").textContent = content.emptyCopy;
  document.querySelector("#view-count").textContent = `${visibleCount} ${visibleCount === 1 ? "Buch" : "Bücher"}`;
}

async function loadBooks() {
  const payload = await api("/api/books");
  state.books = payload.books;
  if (state.libraryMode === "series") await ensureSeriesIndex(state.books);
  renderLibrary();
  if (collectionDialog.open && state.activeSeriesKey) renderCollectionDialog(state.activeSeriesKey);
  if (bookDialog.open && state.detailBook) {
    const savedBook = findCollectionBook(state.detailBook);
    state.detailBook = savedBook
      ? mergeKnownBookMetadata(state.detailBook, savedBook)
      : state.detailBook;
    renderReadingHistory(savedBook || state.detailBook);
    if (state.seriesLoaded) renderSeriesDetails();
  }
}

function canonicalSearchQuery(query) {
  const normalizedQuery = normalizeSearch(query);
  if (normalizedQuery.length < 4) return query;
  const candidates = state.suggestions
    .map((book) => ({ book, title: normalizeSearch(book.title) }))
    .filter(({ title }) => title === normalizedQuery || title.startsWith(`${normalizedQuery} `))
    .sort((left, right) => fuzzyBookScore(right.book, query) - fuzzyBookScore(left.book, query));
  if (!candidates.length) return query;
  const best = candidates[0];
  const isNearlyComplete = editDistance(normalizedQuery, best.title) <= 2;
  const hasPartialLastWord = normalizedQuery.includes(" ");
  return isNearlyComplete || hasPartialLastWord ? best.book.title : query;
}

async function executeSearch(query) {
  if (query.length < 2) return;
  if (query.length > searchInput.maxLength) {
    showToast(`Die Suche darf höchstens ${searchInput.maxLength} Zeichen lang sein.`, true);
    return;
  }
  const hydrationGeneration = ++searchHydrationGeneration;
  const providerQuery = canonicalSearchQuery(query);
  state.lastSearchQuery = providerQuery;
  clearTimeout(suggestionTimer);
  suggestionController?.abort();
  hideSuggestions();
  const button = searchForm.querySelector('[type="submit"]');
  button.disabled = true;
  button.textContent = "Suche …";
  searchPanel.hidden = false;
  const loadingState = document.createElement("div");
  loadingState.className = "loading-state";
  loadingState.textContent = "Buchkatalog wird durchsucht …";
  searchResults.replaceChildren(loadingState);
  searchPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const results = await cachedBookSearch(providerQuery);
    state.searchResults = results.map((book) => {
      const enriched = enrichKnownBookMetadata(book);
      enriched._metadataHydrationPending = Boolean(enriched.provider_book_id);
      return enriched;
    });
    renderSearchResults();
    hydrateSearchResultMetadata(state.searchResults, hydrationGeneration);
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
    retry.addEventListener("click", () => executeSearch(providerQuery));
    message.append(heading, copy, retry);
    searchResults.append(message);
  } finally {
    button.disabled = false;
    button.textContent = "Suchen";
  }
}

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  executeSearch(searchInput.value.trim());
});

searchInput.addEventListener("input", queueSuggestionSearch);
searchInput.addEventListener("focus", () => {
  const query = searchInput.value.trim();
  if (query.length >= 3 && state.suggestionQuery === query) renderSuggestions(query);
});
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !searchSuggestions.hidden) {
    event.preventDefault();
    hideSuggestions();
    return;
  }
  if (searchSuggestions.hidden || !state.suggestions.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    updateActiveSuggestion((activeSuggestionIndex + 1) % state.suggestions.length);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    updateActiveSuggestion(activeSuggestionIndex <= 0 ? state.suggestions.length - 1 : activeSuggestionIndex - 1);
  } else if (event.key === "Enter" && activeSuggestionIndex >= 0) {
    event.preventDefault();
    selectSuggestion(activeSuggestionIndex);
  }
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".search-box")) hideSuggestions();
});

document.querySelector("#manual-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]');
  const data = Object.fromEntries(new FormData(form));
  data.page_count = data.page_count ? Number(data.page_count) : null;
  data.subjects = String(data.subjects || "")
    .split(",")
    .map((subject) => subject.trim())
    .filter(Boolean)
    .slice(0, 10);
  submit.disabled = true;
  try {
    await api("/api/books", { method: "POST", body: JSON.stringify(data) });
    form.reset();
    manualDialog.close();
    await loadBooks();
    showToast(`„${data.title}“ wurde gespeichert.`);
  } catch (error) {
    showToast(error.status === 409 ? "Dieses Buch ist bereits gespeichert." : `Nicht gespeichert: ${error.message}`, true);
  } finally { submit.disabled = false; }
});

document.querySelector("#review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const submit = form.querySelector('[type="submit"]');
  const rating = data.get("rating") ? Number(data.get("rating")) : null;
  const review = String(data.get("review") || "").trim();
  if (review.length > state.reviewMaxLength) {
    showToast(`Der Bewertungstext darf höchstens ${state.reviewMaxLength.toLocaleString("de-DE")} Zeichen lang sein.`, true);
    return;
  }
  const saved = data.get("book_id") ? findCollectionBook(state.reviewCandidate) : null;
  const hasReview = Boolean(rating || review);
  if (!saved && !hasReview) {
    showToast("Wähle Sterne oder schreibe einen Bewertungstext.", true);
    return;
  }
  submit.disabled = true;
  try {
    if (saved) {
      await api(`/api/books/${saved.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: hasReview ? "read" : saved.status,
          rating,
          review,
        }),
      });
    } else {
      await api("/api/books", {
        method: "POST",
        body: JSON.stringify({ ...state.reviewCandidate, status: "read", rating, review }),
      });
    }
    reviewDialog.close();
    await loadBooks();
    showToast(
      hasReview
        ? "Deine Bewertung wurde gespeichert. Das Buch ist jetzt unter „Gelesen“."
        : "Die Bewertung wurde entfernt.",
    );
  } catch (error) {
    showToast(`Nicht gespeichert: ${error.message}`, true);
  } finally { submit.disabled = false; }
});

document.querySelector("#delete-review").addEventListener("click", async () => {
  const form = document.querySelector("#review-form");
  const button = document.querySelector("#delete-review");
  button.disabled = true;
  try {
    await api(`/api/books/${form.elements.book_id.value}`, { method: "PATCH", body: JSON.stringify({ rating: null, review: "" }) });
    reviewDialog.close();
    await loadBooks();
    showToast("Die Bewertung wurde gelöscht.");
  } catch (error) {
    showToast(`Nicht gelöscht: ${error.message}`, true);
  } finally { button.disabled = false; }
});

reviewTextarea.addEventListener("input", updateReviewCharacterCount);

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

function initializeAndroidInteractions() {
  if (!IS_MOBILE_UI) return;

  const activationSelector = "button, a, select, [role='button'], .android-open-card";
  let touchActivation = null;
  let clearTouchActivationTimer;
  const movementLimit = 10;
  const holdLimit = 650;

  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch" || event.button !== 0) return;
    const target = event.target.closest(activationSelector);
    if (!target) return;
    clearTimeout(clearTouchActivationTimer);
    touchActivation = {
      pointerId: event.pointerId,
      target,
      startedAt: Date.now(),
      startX: event.clientX,
      startY: event.clientY,
      cancelled: false,
    };
  }, true);

  document.addEventListener("pointermove", (event) => {
    if (!touchActivation || event.pointerId !== touchActivation.pointerId) return;
    const distance = Math.hypot(
      event.clientX - touchActivation.startX,
      event.clientY - touchActivation.startY,
    );
    if (distance > movementLimit) touchActivation.cancelled = true;
  }, true);

  document.addEventListener("pointercancel", (event) => {
    if (!touchActivation || event.pointerId !== touchActivation.pointerId) return;
    touchActivation.cancelled = true;
    clearTouchActivationTimer = setTimeout(() => { touchActivation = null; }, 1000);
  }, true);

  document.addEventListener("pointerup", (event) => {
    if (!touchActivation || event.pointerId !== touchActivation.pointerId) return;
    if (Date.now() - touchActivation.startedAt > holdLimit) touchActivation.cancelled = true;
    clearTouchActivationTimer = setTimeout(() => { touchActivation = null; }, 1000);
  }, true);

  document.addEventListener("click", (event) => {
    if (!touchActivation) return;
    const sameTarget = touchActivation.target === event.target || touchActivation.target.contains(event.target);
    const heldTooLong = Date.now() - touchActivation.startedAt > holdLimit;
    if (sameTarget && (touchActivation.cancelled || heldTooLong)) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    }
    clearTimeout(clearTouchActivationTimer);
    touchActivation = null;
  }, true);
}

confirmDeleteButton.addEventListener("click", confirmDelete);
deleteDialog.addEventListener("close", () => {
  if (pendingDelete?.button) pendingDelete.button.disabled = false;
  pendingDelete = undefined;
  confirmDeleteButton.disabled = false;
  confirmDeleteButton.textContent = "Buch entfernen";
});
bookDialog.addEventListener("close", () => {
  clearTimeout(seriesPollTimer);
  clearTimeout(metadataPollTimer);
  state.detailBook = null;
  state.infoBook = null;
  state.detailMetadataIdentity = null;
  state.detailMetadata = null;
  state.detailMetadataLoaded = false;
  state.detailMetadataUnavailable = false;
  state.descriptionExpanded = false;
  state.seriesData = null;
  state.seriesLoaded = false;
  state.seriesStatus = null;
  state.seriesRequestUrl = null;
  setBookDialogView("main");
});
reviewDialog.addEventListener("close", () => {
  state.reviewCandidate = null;
  document.querySelector("#delete-review").hidden = false;
});
collectionDialog.addEventListener("close", () => {
  state.activeSeriesKey = null;
  state.collectionSeriesExpanded = false;
});
collectionOtherToggle.addEventListener("click", () => {
  state.collectionSeriesExpanded = !state.collectionSeriesExpanded;
  if (state.activeSeriesKey) renderCollectionDialog(state.activeSeriesKey);
});

document.querySelector(".clear-rating").addEventListener("click", () => {
  document.querySelectorAll('[name="rating"]').forEach((radio) => { radio.checked = false; });
});
appearanceButton.addEventListener("click", () => setAppearanceMenu(appearanceMenu.hidden));
themeOptions.forEach((option) => option.addEventListener("click", () => {
  applyTheme(option.dataset.themeOption);
  setAppearanceMenu(false);
  appearanceButton.focus();
}));
document.querySelector("#open-settings").addEventListener("click", () => settingsDialog.showModal());
settingsThemeSelect.addEventListener("change", () => applyTheme(settingsThemeSelect.value));
settingsSearchLimitSelect.addEventListener("change", () => {
  applySearchResultLimit(settingsSearchLimitSelect.value);
  showToast(`Künftig werden ${state.searchResultLimit} Suchergebnisse angezeigt.`);
});
settingsDateFormatSelect.addEventListener("change", () => {
  applyDateFormat(settingsDateFormatSelect.value);
  showToast(`Datumsformat: ${state.dateFormat}`);
});
function updateBookProviderSettings() {
  applyBookProviders(settingsPrimaryProviderSelect.value, settingsFallbackProviderSelect.value);
  const fallbackText = state.primaryProvider === state.fallbackProvider
    ? "Fallback deaktiviert."
    : `${settingsPrimaryProviderSelect.selectedOptions[0].textContent} → ${settingsFallbackProviderSelect.selectedOptions[0].textContent}`;
  showToast(`Buchsuche: ${fallbackText}`);
}
settingsPrimaryProviderSelect.addEventListener("change", updateBookProviderSettings);
settingsFallbackProviderSelect.addEventListener("change", updateBookProviderSettings);
settingsStartViewSelect.addEventListener("change", () => applyStartView(settingsStartViewSelect.value));
settingsMobileTextSizeSelect.addEventListener("change", () => {
  applyMobileTextSize(settingsMobileTextSizeSelect.value);
  showToast(`Mobile Textgröße: Stufe ${settingsMobileTextSizeSelect.value}.`);
});
sortButton.addEventListener("click", () => setSortMenu(sortMenu.hidden));
sortOptions.forEach((option) => option.addEventListener("click", () => {
  applySort(option.dataset.sortOption);
  setSortMenu(false);
  sortButton.focus();
}));
document.addEventListener("click", (event) => {
  if (!event.target.closest(".appearance-picker")) setAppearanceMenu(false);
  if (!event.target.closest(".sort-picker")) setSortMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !appearanceMenu.hidden) {
    setAppearanceMenu(false);
    appearanceButton.focus();
  }
  if (event.key === "Escape" && !sortMenu.hidden) {
    setSortMenu(false);
    sortButton.focus();
  }
});
document.querySelector("#open-manual").addEventListener("click", () => manualDialog.showModal());
document.querySelector("#empty-search").addEventListener("click", () => document.querySelector("#search-input").focus());
document.querySelector("#close-search").addEventListener("click", () => { searchPanel.hidden = true; });
bookDialogInfoButton.addEventListener("click", () => openBookInfo(state.detailBook));
bookInfoBackButton.addEventListener("click", returnToBookDetails);
bookDescriptionSection.addEventListener("click", () => {
  if (bookDescriptionToggle.hidden) return;
  state.descriptionExpanded = !state.descriptionExpanded;
  updateDescriptionExpansion(state.detailMetadata?.description || "");
});
groupingButton.addEventListener("click", async () => {
  groupingButton.disabled = true;
  if (state.libraryMode === "series") {
    clearTimeout(groupingPollTimer);
    state.libraryMode = "all";
    groupingButton.setAttribute("aria-pressed", "false");
    groupingButtonLabel.textContent = "Reihen gruppieren";
    renderLibrary();
  } else {
    state.libraryMode = "series";
    groupingButton.setAttribute("aria-pressed", "true");
    groupingButtonLabel.textContent = "Reihen werden geladen …";
    grid.setAttribute("aria-busy", "true");
    try {
      // Die bestehende Bücherliste bleibt während des ersten Ladens stehen.
      // Dadurch kollabiert die Seite nicht und die Scrollposition bleibt stabil.
      await ensureSeriesIndex(state.books);
      renderLibrary();
    } finally {
      grid.removeAttribute("aria-busy");
      groupingButtonLabel.textContent = "Alle anzeigen";
    }
  }
  groupingButton.disabled = false;
});
document.querySelectorAll(".dialog-close").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
}));
document.querySelectorAll(".status-tab").forEach((button) => button.addEventListener("click", () => {
  setLibraryFilter(button.dataset.filter);
}));
readingHistoryToggle.addEventListener("click", () => {
  setReadingHistoryExpanded(!state.readingHistoryExpanded);
});

initializeDialogScrollLock();
initializeAndroidInteractions();

async function initializeApp() {
  await loadAppConfig();
  let storedTheme = appConfig.defaults.theme;
  let storedSort = "added_desc";
  let storedSearchLimit = appConfig.defaults.searchResultLimit;
  let storedPrimaryProvider = appConfig.catalogue.primaryProvider;
  let storedFallbackProvider = appConfig.catalogue.fallbackProvider;
  let storedStartView = appConfig.defaults.startView;
  let storedMobileTextSize = appConfig.defaults.mobileTextSize;
  let storedDateFormat = appConfig.defaults.dateFormat;
  try {
    storedTheme = localStorage.getItem("bookypedia-theme") || storedTheme;
    storedSort = localStorage.getItem("bookypedia-sort") || storedSort;
    storedSearchLimit = localStorage.getItem("bookypedia-search-limit") || storedSearchLimit;
    storedPrimaryProvider = localStorage.getItem("bookypedia-primary-provider") || storedPrimaryProvider;
    storedFallbackProvider = localStorage.getItem("bookypedia-fallback-provider") || storedFallbackProvider;
    storedStartView = localStorage.getItem("bookypedia-start-view") || storedStartView;
    storedMobileTextSize = localStorage.getItem("bookypedia-mobile-text-size") || storedMobileTextSize;
    storedDateFormat = localStorage.getItem("bookypedia-date-format") || storedDateFormat;
  } catch (_error) {}
  applyTheme(storedTheme, false);
  applySort(storedSort, false);
  applySearchResultLimit(storedSearchLimit, false);
  applyBookProviders(storedPrimaryProvider, storedFallbackProvider, false);
  applyStartView(storedStartView, false);
  applyMobileTextSize(storedMobileTextSize, false);
  applyDateFormat(storedDateFormat, false);

  try {
    await loadBooks();
  } catch (error) {
    loadingState.textContent = `Die Sammlung konnte nicht geladen werden: ${error.message}`;
    showToast("Keine Verbindung zur lokalen App.", true);
  }
}

initializeApp();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
}

