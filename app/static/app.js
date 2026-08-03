// Shared across pages: NFL team brand colors, injury-status definitions,
// and small formatting helpers used by the Dashboard and Player detail
// pages' hover tooltips. Loaded before Alpine so these are plain globals
// any page's Alpine expressions can call by name.

const TEAM_COLORS = {
    ARI: ["#97233F", "#fff"], ATL: ["#A71930", "#fff"], BAL: ["#241773", "#fff"],
    BUF: ["#00338D", "#fff"], CAR: ["#0085CA", "#fff"], CHI: ["#0B162A", "#fff"],
    CIN: ["#FB4F14", "#fff"], CLE: ["#311D00", "#fff"], DAL: ["#041E42", "#fff"],
    DEN: ["#FB4F14", "#fff"], DET: ["#0076B6", "#fff"], GB: ["#203731", "#fff"],
    HOU: ["#03202F", "#fff"], IND: ["#002C5F", "#fff"], JAX: ["#101820", "#fff"],
    KC: ["#E31837", "#fff"], LAC: ["#0080C6", "#fff"], LAR: ["#003594", "#fff"],
    LV: ["#000000", "#fff"], MIA: ["#008E97", "#fff"], MIN: ["#4F2683", "#fff"],
    NE: ["#002244", "#fff"], NO: ["#101820", "#D3BC8D"], NYG: ["#0B2265", "#fff"],
    NYJ: ["#125740", "#fff"], PHI: ["#004C54", "#fff"], PIT: ["#FFB612", "#101820"],
    SEA: ["#002244", "#fff"], SF: ["#AA0000", "#fff"], TB: ["#D50A0A", "#fff"],
    TEN: ["#0C2340", "#fff"], WAS: ["#5A1414", "#fff"],
};

// City + mascot, so the Dashboard search box also matches "san francisco"
// or "49ers" for a player whose team is just the abbreviation "SF".
const TEAM_NAMES = {
    ARI: "Arizona Cardinals", ATL: "Atlanta Falcons", BAL: "Baltimore Ravens",
    BUF: "Buffalo Bills", CAR: "Carolina Panthers", CHI: "Chicago Bears",
    CIN: "Cincinnati Bengals", CLE: "Cleveland Browns", DAL: "Dallas Cowboys",
    DEN: "Denver Broncos", DET: "Detroit Lions", GB: "Green Bay Packers",
    HOU: "Houston Texans", IND: "Indianapolis Colts", JAX: "Jacksonville Jaguars",
    KC: "Kansas City Chiefs", LAC: "Los Angeles Chargers", LAR: "Los Angeles Rams",
    LV: "Las Vegas Raiders", MIA: "Miami Dolphins", MIN: "Minnesota Vikings",
    NE: "New England Patriots", NO: "New Orleans Saints", NYG: "New York Giants",
    NYJ: "New York Jets", PHI: "Philadelphia Eagles", PIT: "Pittsburgh Steelers",
    SEA: "Seattle Seahawks", SF: "San Francisco 49ers", TB: "Tampa Bay Buccaneers",
    TEN: "Tennessee Titans", WAS: "Washington Commanders",
};

const INJURY_DEFINITIONS = {
    Questionable: "Game-status designation: uncertain to play this week due to injury.",
    Doubtful: "Game-status designation: unlikely to play this week due to injury.",
    Out: "Ruled out for this week's game due to injury.",
    IR: "Injured Reserve: sidelined and unavailable, typically for an extended stretch.",
    PUP: "Physically Unable to Perform: started the year hurt and not yet cleared to practice.",
    DNR: "Did Not Report: hasn't reported to the team (often a contract situation), not an on-field injury.",
    NA: "Not on the active roster this week for a non-injury reason (e.g., a roster exemption).",
};

// Short codes for the inline injury tag. Spelling "Questionable" out in a
// table row costs about as much width as the dedicated column it replaced,
// so the tag shows the code and the hover carries the full definition.
const INJURY_CODES = {
    Questionable: "Q",
    Doubtful: "D",
    Out: "OUT",
    IR: "IR",
    PUP: "PUP",
    DNR: "DNR",
    NA: "NA",
};

function injuryCode(status) {
    return INJURY_CODES[status] || status;
}

// The Odds API's raw bookmaker keys, mapped to how each sportsbook actually
// writes its own name. Falls back to a title-cased guess for anything not
// listed here (e.g. a new book The Odds API adds later).
const BOOKMAKER_NAMES = {
    betmgm: "BetMGM",
    betonlineag: "BetOnline.ag",
    betrivers: "BetRivers",
    betus: "BetUS",
    bovada: "Bovada",
    draftkings: "DraftKings",
    espnbet: "ESPN BET",
    fanatics: "Fanatics",
    fanduel: "FanDuel",
    hardrockbet: "Hard Rock Bet",
    lowvig: "LowVig.ag",
    mybookieag: "MyBookie.ag",
    williamhill_us: "Caesars",
    ballybet: "Bally Bet",
    betparx: "betPARX",
    fliff: "Fliff",
    windcreek: "Wind Creek",
    prizepicks: "PrizePicks",
    underdog: "Underdog",
    betr_us_dfs: "Betr",
    pick6: "DraftKings Pick6",
};

function bookName(key) {
    return BOOKMAKER_NAMES[key] || String(key).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function teamStyle(team) {
    const [bg, fg] = TEAM_COLORS[team] || ["#e5e7eb", "#374151"];
    return `background-color: ${bg}; color: ${fg};`;
}

function fmtOdds(o) {
    if (o === null || o === undefined) return '—';
    return (o > 0 ? '+' : '') + o;
}

// Same raw (not de-vigged) conversion the server uses in
// _pooled_survival_curve(): the "Chance of Going Over" percentage shown in
// the main table is literally the average of this value across books, so a
// per-book number here is directly consistent with it, not just a rough echo.
function impliedProbability(americanOdds) {
    if (americanOdds === null || americanOdds === undefined) return null;
    return americanOdds < 0
        ? -americanOdds / (-americanOdds + 100)
        : 100 / (americanOdds + 100);
}

function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

// Builds the "Books Quoting It" tooltip: a small table titled with the prop
// itself (e.g. "Over 14.5 yds") so each book's price reads on its own line
// without needing an "Over" label repeated per row. Shows each book's own
// odds alongside the implied probability those odds represent, so it reads
// consistently with the percentage shown in the main table.
function booksTooltipHtml(books, title) {
    if (!books || !books.length) return '';
    const rows = books.map(b => {
        const pct = impliedProbability(b.odds);
        const pctText = pct == null ? '—' : (pct * 100).toFixed(1) + '%';
        return `<tr><td>${escapeHtml(bookName(b.bookmaker))}</td>`
            + `<td>${escapeHtml(fmtOdds(b.odds))}</td>`
            + `<td>${pctText}</td></tr>`;
    }).join('');
    return `<div class="tooltip-title">${escapeHtml(title)}</div>`
        + `<table class="tooltip-table"><thead><tr><th></th><th>Odds</th><th>Implied</th></tr></thead>`
        + `<tbody>${rows}</tbody></table>`;
}

// Builds a summary-box hover breakdown (e.g. what the Sportsbook Projection
// number is composed of, market by market) with a final row showing how the
// parts resolve to the headline number. totalLabel defaults to "Total" (the
// parts are summed), pass e.g. "Blended" when the parts are averaged
// instead, so the row never implies arithmetic that isn't what happened.
function breakdownTooltipHtml(items, title, total, totalLabel) {
    if (!items || !items.length) return '';
    const rows = items.map(it =>
        `<tr><td>${escapeHtml(it.label)}</td><td>${Number(it.points).toFixed(2)} pts</td></tr>`
    ).join('');
    const totalRow = total == null ? '' :
        `<tr class="tooltip-total"><td>${escapeHtml(totalLabel || 'Total')}</td><td>${Number(total).toFixed(2)} pts</td></tr>`;
    return `<div class="tooltip-title">${escapeHtml(title)}</div>`
        + `<table class="tooltip-table"><tbody>${rows}${totalRow}</tbody></table>`;
}
