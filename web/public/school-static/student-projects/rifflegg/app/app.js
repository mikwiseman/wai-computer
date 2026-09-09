var DB_URL = '/school-data/rifflegg/matches';
var IGNORE_NICKS = [
    "Test1", "Test2", "TestQA_161", 'EdgeTest297', 'Alice193', 'Bob193',
    'Carl321', 'Dave321', 'Bratan1', "Dragon_QA", "test_bot",
    'FixTest136', 'CancelChk217', 'CancelDbg251'
];
var IGNORE_PREFIXES = ['Final', 'Bro', 'Slow', 'CancelChk', 'CancelDbg', 'FixTest', 'EdgeTest'];
function isIgnoredNick(nick) {
    if (IGNORE_NICKS.indexOf(nick) !== -1)
        return true;
    return IGNORE_PREFIXES.some(function (p) { return nick && nick.indexOf(p) === 0; });
}
var mode = '1×1';
var players = 2;
var matchDuration = 900;
var activeMatches = [];
var finishedMatches = [];
var liveStartCache = {};
var shotCache = {};
function getNick() { return localStorage.getItem('rifflegg_nick') || ''; }
function getBalance() { return Number(localStorage.getItem('rifflegg_balance') || 0); }
function setBalance(v) { localStorage.setItem('rifflegg_balance', v); }
function getCredited() {
    try {
        return JSON.parse(localStorage.getItem('rifflegg_credited') || '[]');
    }
    catch (e) {
        return [];
    }
}
function addCredited(id) {
    var c = getCredited();
    c.push(id);
    localStorage.setItem('rifflegg_credited', JSON.stringify(c));
}
function sendEvent(payload) {
    fetch(DB_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nick: getNick(), payload: payload })
    }).then(function () { refreshFromDB(); })
        .catch(function () { alert("Database unavailable — check your connection"); });
}
function foldEvents(items) {
    var events = items.slice().reverse();
    var map = {};
    events.forEach(function (it) {
        var p = it.payload || {};
        if (!p.type || !p.matchId)
            return;
        if (isIgnoredNick(it.nick))
            return;
        if (p.type === 'cancel') {
            var toCancel = map[p.matchId];
            if (toCancel && it.nick === toCancel.creator && !toCancel.opponent) {
                delete map[p.matchId];
            }
            return;
        }
        if (p.type === 'create' && !map[p.matchId]) {
            var stake = Number(p.stake);
            var pl = Number(p.players);
            if (!isFinite(stake) || !Number.isInteger(stake) || stake < 150 || stake > 100000)
                return;
            if (pl !== 2 && pl !== 4 && pl !== 6)
                return;
            var dur = Number(p.duration);
            map[p.matchId] = {
                id: p.matchId,
                mode: String(p.mode || '?'),
                players: pl,
                stake: stake,
                bank: stake * pl,
                win: Math.round(stake * pl * 0.9),
                duration: (isFinite(dur) && dur > 0) ? dur : 900,
                creator: it.nick || "Anonymous",
                opponent: null,
                ready1: false, ready2: false,
                ready1At: null, ready2At: null,
                result1: null, result2: null,
                createdAt: it.created_at || ''
            };
            return;
        }
        var m = map[p.matchId];
        if (!m)
            return;
        if (p.type === 'join' && !m.opponent && it.nick && it.nick !== m.creator) {
            m.opponent = it.nick;
        }
        if (p.type === 'ready') {
            if (it.nick === m.creator) {
                m.ready1 = true;
                if (!m.ready1At)
                    m.ready1At = it.created_at || '';
            }
            if (it.nick === m.opponent) {
                m.ready2 = true;
                if (!m.ready2At)
                    m.ready2At = it.created_at || '';
            }
        }
        if (p.type === 'result' && (p.winner === '1' || p.winner === '2')) {
            if (it.nick === m.creator)
                m.result1 = p.winner;
            if (it.nick === m.opponent)
                m.result2 = p.winner;
        }
    });
    var active = [], finished = [];
    Object.keys(map).forEach(function (k) {
        var m = map[k];
        if (m.result1 && m.result2 && m.result1 === m.result2) {
            m.winnerNick = m.result1 === '1' ? m.creator : m.opponent;
            m.loserNick = m.result1 === '1' ? m.opponent : m.creator;
            finished.push(m);
        }
        else {
            m.dispute = !!(m.result1 && m.result2 && m.result1 !== m.result2);
            m.live = !!(m.opponent && m.ready1 && m.ready2);
            if (m.live) {
                var t1 = Date.parse(m.ready1At), t2 = Date.parse(m.ready2At);
                var st = Math.max(isNaN(t1) ? 0 : t1, isNaN(t2) ? 0 : t2);
                m.startAt = st > 0 ? st : null;
            }
            active.push(m);
        }
    });
    function newestFirst(a, b) { return a.createdAt < b.createdAt ? 1 : -1; }
    active.sort(newestFirst);
    finished.sort(newestFirst);
    return { active: active, finished: finished };
}
function creditMyWins() {
    var me = getNick();
    if (!me)
        return false;
    var credited = false;
    finishedMatches.forEach(function (m) {
        if (m.winnerNick === me && getCredited().indexOf(m.id) === -1) {
            setBalance(getBalance() + m.win);
            addCredited(m.id);
            credited = true;
        }
    });
    return credited;
}
function refreshFromDB() {
    fetch(DB_URL + '?limit=500&order=desc')
        .then(function (r) { return r.json(); })
        .then(function (d) {
        var folded = foldEvents(d.items || []);
        activeMatches = folded.active;
        finishedMatches = folded.finished;
        if (creditMyWins())
            renderProfile();
        renderMatches();
        renderFeed();
        var arr = aggregate();
        renderLeaderboard(arr);
        renderAwards(arr);
    })
        .catch(function () {
        document.getElementById('feed').innerHTML = "<div class=\"empty\">Database unavailable — check your connection</div>";
    });
}
function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls)
        e.className = cls;
    if (text !== undefined)
        e.textContent = text;
    return e;
}
function renderMatch(m) {
    var me = getNick();
    var iAmCreator = me && me === m.creator;
    var iAmOpponent = me && me === m.opponent;
    var sideName = m.players === 2 ? "Player" : "Team";
    var card = el('div', 'match');
    var top = el('div', 'match-top');
    var left = el('div');
    left.appendChild(el('div', 'match-mode', m.mode));
    left.appendChild(el('div', 'match-info', "stake " + m.stake + " 🪙 · players " + m.players));
    var bank = el('div', 'match-bank');
    bank.appendChild(el('div', 'b', m.bank + ' 🪙'));
    bank.appendChild(el('div', 'w', "to the winner " + m.win + ' 🪙'));
    top.appendChild(left);
    top.appendChild(bank);
    card.appendChild(top);
    var vs = el('div', 'vs-row');
    vs.appendChild(el('span', '', '🎮 ' + m.creator));
    vs.appendChild(el('span', 'vs', 'VS'));
    vs.appendChild(m.opponent
        ? el('span', '', m.opponent)
        : el('span', 'waiting', "waiting for an opponent…"));
    card.appendChild(vs);
    if (!m.opponent) {
        if (iAmCreator) {
            card.appendChild(el('div', 'wait-note', "Everyone in the league can see your challenge. Who will accept?"));
            var cancelBtn = el('button', 'cancel-btn', "✖ Cancel match");
            cancelBtn.addEventListener('click', function () { cancelMatch(m); });
            card.appendChild(cancelBtn);
        }
        else {
            var joinBtn = el('button', 'join-btn', "⚔️ Accept challenge — stake " + m.stake + ' 🪙');
            joinBtn.addEventListener('click', function () { joinMatch(m); });
            card.appendChild(joinBtn);
        }
        return card;
    }
    var pay = el('div', 'match-pay');
    pay.appendChild(el('div', 'req', "🪙 Stakes are in the pot. Mark who is ready to play:"));
    var btns = el('div', 'pay-btns');
    btns.appendChild(readyButton(m, '1', sideName + ' 1: ' + m.creator, m.ready1, iAmCreator));
    btns.appendChild(readyButton(m, '2', sideName + ' 2: ' + m.opponent, m.ready2, iAmOpponent));
    pay.appendChild(btns);
    card.appendChild(pay);
    if (m.live)
        card.appendChild(makeTimer(m));
    if (m.dispute) {
        card.appendChild(el('div', 'dispute', "⚠️ You chose different winners. Agree and choose again. Your latest choice counts."));
    }
    if (iAmCreator || iAmOpponent) {
        var myChoice = iAmCreator ? m.result1 : m.result2;
        var actions = el('div', 'match-actions');
        actions.appendChild(winButton(m, '1', "🏆 Winner: " + m.creator, myChoice === '1'));
        actions.appendChild(winButton(m, '2', "🏆 Winner: " + m.opponent, myChoice === '2'));
        card.appendChild(actions);
        card.appendChild(makeEvidence(m));
        if (myChoice && !m.dispute) {
            card.appendChild(el('div', 'wait-note', "Your choice is saved. Waiting for your opponent to confirm…"));
        }
    }
    else {
        card.appendChild(el('div', 'wait-note', "The match is in progress. The result will appear in the feed."));
    }
    return card;
}
function readyButton(m, side, label, done, isMine) {
    var b = el('button', 'paid-btn' + (done ? ' done' : ''), label + (done ? ' ✅' : done === false && isMine ? " — ready?" : ''));
    b.disabled = done || !isMine;
    if (isMine && !done) {
        b.addEventListener('click', function () { sendEvent({ type: 'ready', matchId: m.id }); });
    }
    return b;
}
function winButton(m, winner, label, chosen) {
    var b = el('button', 'win-btn' + (chosen ? ' done' : ''), label);
    b.addEventListener('click', function () {
        sendEvent({ type: 'result', matchId: m.id, winner: winner });
    });
    return b;
}
var RING_C = 157.08;
function makeTimer(m) {
    var startMs = m.startAt || (liveStartCache[m.id] || (liveStartCache[m.id] = Date.now()));
    var t = el('div', 'timer live');
    t.dataset.start = startMs;
    t.dataset.dur = m.duration;
    t.innerHTML =
        '<svg class="ring" viewBox="0 0 58 58" aria-hidden="true">' +
            '<circle class="track" cx="29" cy="29" r="25"></circle>' +
            '<circle class="prog" cx="29" cy="29" r="25" data-c="' + RING_C + '" stroke-dasharray="' + RING_C + '" stroke-dashoffset="0"></circle>' +
            '</svg>' +
            "<div class=\"timer-txt\"><div class=\"t-big\">--:--</div><div class=\"t-cap\">match in progress</div></div>";
    return t;
}
function tickTimers() {
    var now = Date.now();
    var nodes = document.querySelectorAll('.timer');
    for (var i = 0; i < nodes.length; i++) {
        var t = nodes[i];
        var start = Number(t.dataset.start), dur = Number(t.dataset.dur) * 1000;
        if (!start || !dur)
            continue;
        var remain = Math.max(0, start + dur - now);
        var frac = remain / dur;
        var prog = t.querySelector('.prog');
        prog.style.strokeDashoffset = (RING_C * (1 - frac)).toFixed(2);
        var big = t.querySelector('.t-big'), cap = t.querySelector('.t-cap');
        if (remain <= 0) {
            t.classList.remove('live');
            t.classList.add('over');
            big.textContent = '00:00';
            cap.textContent = "time is up — select the winner";
        }
        else {
            var s = Math.floor(remain / 1000), mm = Math.floor(s / 60), ss = s % 60;
            big.textContent = mm + ':' + (ss < 10 ? '0' : '') + ss;
        }
    }
}
function makeEvidence(m) {
    var box = el('div', 'evidence');
    function render() {
        box.innerHTML = '';
        if (shotCache[m.id]) {
            var pv = el('div', 'shot-preview');
            var img = el('img');
            img.src = shotCache[m.id];
            img.alt = "score screenshot";
            var tag = el('div', 'shot-tag', "EVIDENCE");
            var rm = el('button', 'shot-remove', '✕');
            rm.addEventListener('click', function () { delete shotCache[m.id]; render(); });
            pv.appendChild(img);
            pv.appendChild(tag);
            pv.appendChild(rm);
            box.appendChild(pv);
        }
        else {
            var drop = el('label', 'shot-drop');
            drop.innerHTML = "<span class=\"ic\">📸</span><span class=\"txt\"><b>Attach a score screenshot</b>optional proof of victory</span>";
            var fi = el('input');
            fi.type = 'file';
            fi.accept = 'image/*';
            fi.style.display = 'none';
            fi.addEventListener('change', function () {
                var f = fi.files && fi.files[0];
                if (!f)
                    return;
                var reader = new FileReader();
                reader.onload = function (ev) { shotCache[m.id] = ev.target.result; render(); };
                reader.readAsDataURL(f);
            });
            drop.appendChild(fi);
            box.appendChild(drop);
        }
    }
    render();
    return box;
}
function renderMatches() {
    var list = document.getElementById('matches');
    list.innerHTML = '';
    if (activeMatches.length === 0) {
        list.innerHTML = "<div class=\"empty\">No matches yet. Create the first one! 👆</div>";
        return;
    }
    activeMatches.forEach(function (m) { list.appendChild(renderMatch(m)); });
}
function joinMatch(m) {
    if (!getNick()) {
        alert("Save a nickname in your profile first!");
        return;
    }
    if (getBalance() < m.stake) {
        alert("Not enough coins! Get more in your profile.");
        return;
    }
    if (!confirm("Accept the challenge and stake " + m.stake + ' 🪙?'))
        return;
    setBalance(getBalance() - m.stake);
    renderProfile();
    sendEvent({ type: 'join', matchId: m.id });
}
function cancelMatch(m) {
    if (!confirm("Cancel the match and return " + m.stake + ' 🪙?'))
        return;
    setBalance(getBalance() + m.stake);
    renderProfile();
    sendEvent({ type: 'cancel', matchId: m.id });
}
var stakeEl = document.getElementById('stake');
var sliderEl = document.getElementById('stakeSlider');
function clampStake(v) { v = Math.round((Number(v) || 0) / 50) * 50; return Math.max(150, Math.min(5000, v)); }
function updateStakePreview() {
    var stake = Number(stakeEl.value) || 0;
    var bank = stake * players;
    document.getElementById('pvBank').textContent = bank.toLocaleString('en-US');
    document.getElementById('pvWin').textContent = Math.round(bank * 0.9).toLocaleString('en-US');
    var pct = Math.max(0, Math.min(100, (stake - 150) / (5000 - 150) * 100));
    sliderEl.style.setProperty('--fill', pct + '%');
}
sliderEl.addEventListener('input', function () { stakeEl.value = sliderEl.value; updateStakePreview(); });
stakeEl.addEventListener('input', function () { sliderEl.value = clampStake(stakeEl.value); updateStakePreview(); });
document.querySelectorAll('.mode-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
        document.querySelectorAll('.mode-btn').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        mode = btn.dataset.mode;
        players = Number(btn.dataset.players);
        updateStakePreview();
    });
});
document.querySelectorAll('.dur-chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
        document.querySelectorAll('.dur-chip').forEach(function (c) { c.classList.remove('active'); });
        chip.classList.add('active');
        matchDuration = Number(chip.dataset.dur);
    });
});
updateStakePreview();
document.getElementById('createBtn').addEventListener('click', function () {
    var stake = Number(document.getElementById('stake').value);
    var hint = document.getElementById('hint');
    function fail(msg) { hint.textContent = msg; hint.classList.add('err'); }
    if (!getNick()) {
        fail("Save a nickname in your profile first!");
        return;
    }
    if (!stake || stake < 150) {
        fail("The minimum stake is 150 🪙!");
        return;
    }
    if (!Number.isInteger(stake)) {
        fail("The stake must be a whole number of coins!");
        return;
    }
    if (stake > getBalance()) {
        fail("Not enough coins! Get more in your profile.");
        return;
    }
    hint.textContent = "Minimum 150 🪙. The winner takes 90% of the pot.";
    hint.classList.remove('err');
    setBalance(getBalance() - stake);
    renderProfile();
    var matchId = getNick() + '-' + Date.now();
    sendEvent({ type: 'create', matchId: matchId, mode: mode, players: players, stake: stake, duration: matchDuration });
});
function renderProfile() {
    var box = document.getElementById('profile');
    var nick = getNick();
    if (nick) {
        box.innerHTML =
            "<h2>👤 My profile</h2>" +
                '<div class="profile-view">' +
                '<div class="avatar"></div>' +
                "<div><div class=\"hi\">Hi,</div><div class=\"nick\"></div></div>" +
                "<button class=\"change-btn\" id=\"changeNick\">Edit</button>" +
                '</div>' +
                '<div class="balance-row">' +
                "<div class=\"bal-label\">🪙 My coins</div>" +
                '<div class="bal-amount">' + getBalance() + ' 🪙</div>' +
                '</div>' +
                '<div class="topup">' +
                "<input class=\"topup-input\" id=\"topupAmount\" type=\"number\" placeholder=\"How many coins?\" min=\"1\">" +
                "<button class=\"topup-btn\" id=\"topupBtn\">Get coins</button>" +
                '</div>';
        box.querySelector('.avatar').textContent = nick.slice(0, 2).toUpperCase();
        box.querySelector('.nick').textContent = nick;
        document.getElementById('topupBtn').addEventListener('click', function () {
            var add = Number(document.getElementById('topupAmount').value);
            if (!add || add < 1)
                return;
            if (add > 1000)
                add = 1000;
            setBalance(Math.min(getBalance() + add, 100000));
            renderProfile();
        });
        document.getElementById('changeNick').addEventListener('click', function () {
            box.innerHTML =
                "<h2>👤 My profile</h2>" +
                    '<div class="profile-edit">' +
                    '<input class="nick-input" id="nick" type="text" maxlength="20">' +
                    "<button class=\"save-btn\" id=\"saveNick\">Save</button>" +
                    '</div>';
            document.getElementById('nick').value = nick;
            bindSave();
        });
    }
    else {
        box.innerHTML =
            "<h2>👤 My profile</h2>" +
                '<div class="profile-edit">' +
                "<input class=\"nick-input\" id=\"nick\" type=\"text\" placeholder=\"Your in-game nickname\" maxlength=\"20\">" +
                "<button class=\"save-btn\" id=\"saveNick\">Save</button>" +
                '</div>';
        bindSave();
    }
}
function bindSave() {
    document.getElementById('saveNick').addEventListener('click', function () {
        var nick = document.getElementById('nick').value.trim();
        if (!nick)
            return;
        if (nick !== getNick() && knownNicks().indexOf(nick) !== -1) {
            if (!confirm("The nickname “" + nick + "” already appears in the league. If that is not you, the game may confuse your results. Save anyway?"))
                return;
        }
        localStorage.setItem('rifflegg_nick', nick);
        renderProfile();
        refreshFromDB();
    });
}
function knownNicks() {
    var set = {};
    activeMatches.concat(finishedMatches).forEach(function (m) {
        if (m.creator)
            set[m.creator] = true;
        if (m.opponent)
            set[m.opponent] = true;
    });
    return Object.keys(set);
}
function renderFeed() {
    var box = document.getElementById('feed');
    box.innerHTML = '';
    if (finishedMatches.length === 0) {
        box.innerHTML = "<div class=\"empty\">No one has played yet. Be the first! 🏆</div>";
        return;
    }
    finishedMatches.forEach(function (m) {
        var row = el('div', 'feed-item');
        row.appendChild(el('span', 'feed-nick', m.winnerNick));
        row.appendChild(el('span', 'feed-rest', " defeated "));
        row.appendChild(el('span', 'feed-nick', m.loserNick));
        row.appendChild(el('span', 'feed-rest', ' · ' + m.mode + " · stake " + m.stake + ' 🪙 · +' + m.win + ' 🪙'));
        box.appendChild(row);
    });
}
function aggregate() {
    var map = {};
    function row(nick) {
        if (!map[nick])
            map[nick] = { nick: nick, wins: 0, losses: 0, coins: 0 };
        return map[nick];
    }
    finishedMatches.forEach(function (m) {
        row(m.winnerNick).wins++;
        row(m.winnerNick).coins += m.win;
        row(m.loserNick).losses++;
    });
    var arr = Object.keys(map).map(function (k) {
        var r = map[k];
        r.points = r.wins * 3;
        return r;
    });
    arr.sort(function (a, b) { return b.points - a.points || b.coins - a.coins; });
    return arr;
}
function renderLeaderboard(arr) {
    var tb = document.getElementById('lb');
    tb.innerHTML = '';
    if (arr.length === 0) {
        var er = el('tr');
        var ec = el('td');
        ec.setAttribute('colspan', '5');
        ec.style.padding = '30px';
        ec.style.color = 'var(--muted)';
        ec.textContent = "No games yet. Play the first match!";
        er.appendChild(ec);
        tb.appendChild(er);
        return;
    }
    var medals = ['🥇', '🥈', '🥉'];
    arr.forEach(function (r, i) {
        var tr = el('tr', i === 0 ? 'top1' : '');
        var tdP = el('td');
        var cell = el('div', 'player-cell');
        cell.appendChild(el('span', 'rank', (i + 1)));
        if (medals[i])
            cell.appendChild(el('span', 'medal', medals[i]));
        cell.appendChild(el('div', 'avatar', r.nick.slice(0, 2).toUpperCase()));
        cell.appendChild(el('span', 'pname', r.nick));
        tdP.appendChild(cell);
        tr.appendChild(tdP);
        tr.appendChild(el('td', '', r.wins));
        tr.appendChild(el('td', '', r.losses));
        var tdC = el('td', 'hide-mob');
        tdC.appendChild(el('span', 'money', r.coins + ' 🪙'));
        tr.appendChild(tdC);
        var tdPts = el('td');
        tdPts.appendChild(el('span', 'pts', r.points));
        tr.appendChild(tdPts);
        tb.appendChild(tr);
    });
}
function renderAwards(arr) {
    var box = document.getElementById('awards');
    box.innerHTML = '';
    if (arr.length === 0)
        return;
    var mvp = arr.slice().sort(function (a, b) { return b.wins - a.wins; })[0];
    var shame = arr.slice().sort(function (a, b) { return b.losses - a.losses; })[0];
    var wrap = el('div', 'awards');
    if (mvp && mvp.wins > 0)
        wrap.appendChild(makeAward('mvp', "🏆 LEAGUE MVP", '🏆', mvp.nick, mvp.wins + " wins"));
    if (shame && shame.losses > 0)
        wrap.appendChild(makeAward('shame', "💀 BIGGEST LOSER OF THE WEEK", '💀', shame.nick, shame.losses + " losses"));
    if (wrap.children.length)
        box.appendChild(wrap);
}
function makeAward(cls, title, emoji, nick, sub) {
    var a = el('div', 'award ' + cls);
    a.appendChild(el('div', 'a-title', title));
    a.appendChild(el('div', 'a-emoji', emoji));
    a.appendChild(el('div', 'a-nick', nick));
    a.appendChild(el('div', 'a-sub', sub));
    return a;
}
renderProfile();
refreshFromDB();
setInterval(refreshFromDB, 10000);
tickTimers();
setInterval(tickTimers, 500);
