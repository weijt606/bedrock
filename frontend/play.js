/* The reveal.
 *
 * `renderResult` used to print the finished sample as a list. A list is read
 * top to bottom in four seconds and forgotten; the point of this product is
 * that the reader is wrong about what they eat, and being wrong needs a bet
 * and a pause.
 *
 * So the same CoreSample is dealt as a deck: bet, then one finding per card,
 * then a verdict built from what the reader actually answered. Nothing here
 * invents a fact — every card is a `story[]` beat, a `gaps[]` entry, a
 * `guesses[]` prompt or a `score` field, and each carries the source the
 * agent attached.
 */
(function (global) {
  'use strict';

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const PUBLISHER = {
    'theguardian.com': 'The Guardian', 'businessinsider.com': 'Business Insider',
    'business-humanrights.org': 'Business & Human Rights Resource Centre',
    'ilo.org': 'International Labour Organization', 'sec.gov': 'SEC',
    'gleif.org': 'GLEIF', 'reuters.com': 'Reuters', 'ft.com': 'Financial Times',
    'bbc.com': 'BBC', 'nytimes.com': 'The New York Times', 'indiacsr.in': 'India CSR',
  };
  // Cala's own `source.name` is sometimes an editorial slug rather than a
  // masthead — it returns "Middle East crisis" for a Guardian article.
  const publisherOf = (url) => {
    try { const h = new URL(url).hostname.replace(/^www\./, ''); return PUBLISHER[h] || h; }
    catch { return url; }
  };

  const citeHtml = (source) => {
    const docs = (source && source.documents ? source.documents : []).slice(0, 3);
    if (docs.length) {
      return '<p class="pc-cite">' + docs.map((u) => (
        '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">'
        + esc(publisherOf(u)) + '</a>'
      )).join('') + '</p>';
    }
    // No document means no citation. Showing the query we asked is more
    // truthful than showing nothing, and it is what the reader can check.
    return source && source.query
      ? '<p class="pc-cite"><span>' + esc(source.query) + '</span></p>' : '';
  };

  /* A headline like "94 brands end in the same place." carries its own focal
   * point. Pull the figure out so the eye lands on it, and leave the rest as
   * the sentence — without rewriting a single word. */
  const splitFigure = (headline) => {
    const m = String(headline || '').match(/^([^\d]*?)(\d[\d.,]*\s*%?)(.*)$/);
    if (!m) return null;
    if (m[2].replace(/\D/g, '').length > 9) return null;
    const rest = (m[1] + ' ' + m[3]).replace(/\s+/g, ' ').trim();
    return rest ? { figure: m[2].trim(), rest } : null;
  };

  const KIND_LABEL = {
    origin: 'Where it starts', handover: 'It answers to somebody else',
    border: 'It left home', terminus: 'The chain stops here',
    convergence: 'You were choosing between them', concern: 'On the public record',
    silence: 'Nobody has written this down', scale: 'A number worth feeling',
  };

  function build(sample) {
    const cards = [];
    const guesses = (sample.guesses || []).filter(
      (g) => g.question && (g.options || []).length);
    // Two kinds of wager. The chain ones open the deck — they are a puzzle, and
    // being wrong about them is a surprise. The concern ones are not a puzzle:
    // they are asked one card before the record answers them, so the reader has
    // to say what they think before being shown what is filed.
    const chainBets = guesses.filter((g) => !g.concern).slice(0, 2);
    const concernBets = guesses.filter((g) => g.concern);

    chainBets.forEach((g, n) => cards.push({
      kind: 'bet', id: g.id,
      html: '<p class="pc-eyebrow">'
        + (n === 0 ? 'Before we show you anything' : 'One more') + '</p>'
        + '<h2 class="pc-head">' + esc(g.question) + '</h2>'
        + '<div class="pc-chips" role="group" aria-label="Your answer">'
        + g.options.map((o) => '<button class="pc-chip" type="button" data-pick="'
            + esc(o) + '">' + esc(o) + '</button>').join('')
        + '</div><p class="pc-say">Pick one. We will hold you to it.</p>',
    }));

    let concernBetsDealt = false;
    (sample.story || []).forEach((beat) => {
      // The questions land immediately before the first finding, so the answer is
      // the very next card. Asked at the top of the deck they would be trivia;
      // asked here they are a position the reader took a moment ago.
      if (beat.kind === 'concern' && !concernBetsDealt) {
        concernBetsDealt = true;
        concernBets.forEach((g, n) => cards.push({
          kind: 'bet', id: g.id,
          html: '<p class="pc-eyebrow pc-eyebrow--warn">'
            + (n === 0 ? 'Something you should know' : 'And this one') + '</p>'
            + '<h2 class="pc-head">' + esc(g.question) + '</h2>'
            + '<div class="pc-chips" role="group" aria-label="Your answer">'
            + g.options.map((o) => '<button class="pc-chip" type="button" data-pick="'
                + esc(o) + '">' + esc(o) + '</button>').join('')
            + '</div><p class="pc-say">Answer, then read what is on file.</p>',
        }));
      }
      const fig = splitFigure(beat.headline);
      const head = fig
        ? '<p class="pc-figure">' + esc(fig.figure) + '</p>'
          + '<h2 class="pc-head pc-head--under">' + esc(fig.rest) + '</h2>'
        : '<h2 class="pc-head">' + esc(beat.headline) + '</h2>';
      // On a `concern` the subject of the sentence is the finding: somebody has
      // a record. That it is filed a few steps above the packet is the turn, so
      // it lands a beat later as a chip rather than arriving inside the headline
      // — the reader reads the claim, then sees whose it is.
      const above = beat.kind === 'concern'
        && /(\d+)\s+steps? above the label/.exec(beat.headline);
      const headline = above ? beat.headline.replace(/\s*—[^—]*above the label\s*—/, ' ') : null;
      const shown = headline
        ? '<h2 class="pc-head">' + esc(headline) + '</h2>'
          + '<p class="pc-above pc-late">' + esc(above[1])
          + (above[1] === '1' ? ' step' : ' steps') + ' above the label</p>'
        : head;
      cards.push({
        kind: 'beat', beat: beat.kind, at: beat.at_step, late: !!headline,
        html: '<p class="pc-eyebrow">' + esc(KIND_LABEL[beat.kind] || beat.kind) + '</p>'
          + shown
          + (beat.detail ? '<p class="pc-say">' + esc(beat.detail) + '</p>' : '')
          + citeHtml(beat.source),
      });
    });

    // Siblings become a wager on scale, then a staggered reveal. We do not ask
    // the reader to pick this owner's brands out of a line-up, because the
    // decoys would be claims about other companies that Cala never verified.
    const kin = (sample.siblings || []).filter(Boolean);
    if (kin.length >= 6) {
      const company = [...(sample.layers || [])].reverse().find((l) => l.kind === 'company');
      const owner = (company && company.name)
        || (sample.subject && sample.subject.resolved_name) || 'the same owner';
      cards.push({
        kind: 'wager', id: 'siblings_count',
        html: '<p class="pc-eyebrow">Last one</p>'
          + '<h2 class="pc-head">How many brands answer to ' + esc(owner) + '?</h2>'
          + '<div class="pc-chips" role="group" aria-label="Your answer">'
          + ['under 10', '10 to 40', 'more than 40'].map((o) => (
              '<button class="pc-chip" type="button" data-pick="' + esc(o) + '">'
              + esc(o) + '</button>')).join('')
          + '</div>',
      });
      cards.push({
        kind: 'kin', items: kin.slice(0, 40),
        html: '<p class="pc-eyebrow">You have been choosing between them</p>'
          + '<p class="pc-figure" data-count="' + kin.length + '">0</p>'
          + '<h2 class="pc-head pc-head--under">brands, one owner.</h2>'
          + '<ul class="pc-kin" id="pcKin"></ul>',
      });
    }

    (sample.gaps || []).filter((g) => g.reason === 'no_rows').slice(0, 1).forEach((gap) => {
      const tries = (gap.attempts && gap.attempts.length ? gap.attempts : [gap.query])
        .filter(Boolean);
      cards.push({
        kind: 'silence', tries: tries,
        html: '<p class="pc-eyebrow">And what nobody has written down</p>'
          + '<ul class="pc-qs" id="pcTries"></ul>'
          + '<p class="pc-figure pc-figure--late" id="pcZero">0</p>'
          + '<h2 class="pc-head pc-head--under pc-late" id="pcZeroHead">rows, however we asked.</h2>'
          + '<p class="pc-say pc-late" id="pcZeroSay">Asked '
          + (tries.length === 1 ? 'once' : tries.length + ' ways')
          + ', all empty. A question with no answer is a finding, not an error.</p>',
      });
    });

    cards.push({ kind: 'verdict', html: '' });
    return cards;
  }

  /* The loop is illustrative and carries no facts, so it is appended rather
   * than built in: if fal is slow, unconfigured or fails, the deck is simply
   * one card shorter and nothing else changes. */
  function pollMedia(sampleId, onReady, tries) {
    if (!sampleId || tries <= 0) return;
    fetch('/v1/samples/' + encodeURIComponent(sampleId) + '/media')
      .then((r) => r.json())
      .then((m) => {
        if (m.status === 'ready' && m.url) { onReady(m.url); return; }
        if (m.status === 'pending') window.setTimeout(
          () => pollMedia(sampleId, onReady, tries - 1), 4000);
      })
      .catch(() => {});
  }

  function mount(root, sample) {
    const cards = build(sample);
    const picks = {};
    let i = 0;

    root.innerHTML = '<div class="pc" id="pcStage"></div>'
      + '<p class="pc-trail" id="pcTrail" aria-hidden="true"></p>'
      + '<div class="pc-spine" id="pcSpine">'
      + cards.map(() => '<i></i>').join('') + '</div>';
    const stage = root.querySelector('#pcStage');
    const trail = root.querySelector('#pcTrail');
    const pips = [].slice.call(root.querySelector('#pcSpine').children);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // The trail is the one number the reader is meant to feel: every border the
    // thing crossed on its way to an owner. It is built from score.countries, so
    // it only ever shows borders the chain actually crossed.
    const borders = ((sample.score || {}).countries || []);
    const showTrail = (upto) => {
      trail.innerHTML = borders.slice(0, upto).map((c, k) => (
        (k ? '<i>→</i>' : '') + '<b>' + esc(c) + '</b>'
      )).join('');
      trail.hidden = upto < 2;
    };

    const countUp = (el, to) => {
      const t0 = performance.now();
      const step = (t) => {
        const p = Math.min(1, (t - t0) / 900);
        el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))).toLocaleString('en-US');
        if (p < 1) requestAnimationFrame(step);
        else el.textContent = to.toLocaleString('en-US');
      };
      requestAnimationFrame(step);
    };

    const verdictHtml = () => {
      const rows = [];
      let missed = 0;
      // Same split build() used to deal them: the first two chain wagers plus
      // every concern the record answered. Recomputed rather than shared because
      // this runs in mount(), not build().
      const wagers = (sample.guesses || []).filter(
        (g) => g.question && (g.options || []).length);
      [...wagers.filter((g) => !g.concern).slice(0, 2),
       ...wagers.filter((g) => g.concern)].forEach((g) => {
        if (!g.answer) return;
        const mine = picks[g.id];
        if (mine && mine !== g.answer) missed += 1;
        rows.push('<div><b>' + esc(mine || '—') + '</b><span>you said</span></div>'
          + '<div><b>' + esc(g.answer) + '</b><span>it is</span></div>');
      });
      const kin = (sample.siblings || []).length;
      if (picks.siblings_count) {
        const band = kin < 10 ? 'under 10' : (kin <= 40 ? '10 to 40' : 'more than 40');
        if (picks.siblings_count !== band) missed += 1;
        rows.push('<div><b>' + esc(picks.siblings_count) + '</b><span>you guessed</span></div>'
          + '<div><b>' + kin + '</b><span>there are</span></div>');
      }
      const asked = rows.length / 2;
      return '<p class="pc-eyebrow">What you said, and what is filed</p>'
        + '<p class="pc-figure" data-count="' + missed + '">0</p>'
        + '<h2 class="pc-head pc-head--under">'
        + (missed === 0 ? 'of ' + asked + '. Nobody gets them all.'
                        : 'of ' + asked + ', you got wrong.') + '</h2>'
        + '<div class="pc-tally">' + rows.join('') + '</div>'
        + '<p class="pc-say">Every figure here came back from a verified-data API with '
        + 'the document behind it. None of it was written by a model.</p>'
        // The verdict gates the click-anywhere advance, so without these it is a
        // dead end: a reader who wants to re-read the step that caught them out
        // has no way back to it.
        + '<div class="pc-nav">'
        + '<button class="pc-nav__b" type="button" data-nav="-1">&larr; Back</button>'
        + '<button class="pc-nav__b" type="button" data-nav="first">Start over</button>'
        + '</div>';
    };

    let depth = 0;
    const timers = [];
    const later = (fn, ms) => timers.push(window.setTimeout(fn, reduced ? 0 : ms));

    function show(n) {
      const back = n < i;
      i = Math.max(0, Math.min(cards.length - 1, n));
      const card = cards[i];
      timers.splice(0).forEach(window.clearTimeout);

      stage.innerHTML = '<section class="pc-card" data-kind="' + esc(card.kind) + '"'
        + (back ? ' data-back="1"' : '') + '>'
        + (card.kind === 'verdict' ? verdictHtml() : card.html) + '</section>';
      pips.forEach((p, k) => p.classList.toggle('on', k <= i));

      // Going down. The ground cools by one step per ownership card, so the
      // reader feels the descent rather than being told about it — the same
      // move the original piece made with a scroll.
      if (card.kind === 'beat' && (card.beat === 'handover' || card.beat === 'border'
          || card.beat === 'terminus')) depth += 1;
      root.style.setProperty('--pc-depth', Math.min(depth, 5));
      showTrail(card.kind === 'verdict' ? borders.length
                : Math.min(depth + 1, borders.length));

      const fig = stage.querySelector('[data-count]');
      if (fig) countUp(fig, parseInt(fig.dataset.count, 10));

      stage.querySelectorAll('[data-nav]').forEach((b) => b.addEventListener('click', (e) => {
        e.stopPropagation();
        show(b.dataset.nav === 'first' ? 0 : i + parseInt(b.dataset.nav, 10));
      }));

      stage.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', (e) => {
        e.stopPropagation();
        picks[card.id] = b.dataset.pick;
        show(i + 1);
      }));

      // Four phrasings, typed one at a time, and only then the zero. The point
      // of this card is that we asked repeatedly — printing the list all at once
      // reads as "not found", which is the opposite of what it means.
      if (card.kind === 'silence') {
        const ul = stage.querySelector('#pcTries');
        card.tries.forEach((q, n2) => later(() => {
          const li = document.createElement('li');
          li.textContent = q;
          ul.appendChild(li);
          requestAnimationFrame(() => li.classList.add('in'));
          later(() => li.classList.add('empty'), 420);
        }, 200 + n2 * 620));
        later(() => {
          stage.querySelectorAll('.pc-late, .pc-figure--late')
            .forEach((el) => el.classList.add('in'));
          const z = stage.querySelector('#pcZero');
          if (z) z.classList.add('in');
        }, 300 + card.tries.length * 620);
      }

      if (card.late) {
        later(() => stage.querySelectorAll('.pc-late')
          .forEach((el) => el.classList.add('in')), 900);
      }

      if (card.kind === 'kin') {
        const ul = stage.querySelector('#pcKin');
        card.items.forEach((name, n2) => window.setTimeout(() => {
          const li = document.createElement('li');
          li.textContent = name;
          ul.appendChild(li);
          requestAnimationFrame(() => li.classList.add('in'));
        }, 120 + n2 * 55));
      }

      root.dataset.gate = (card.kind === 'bet' || card.kind === 'wager'
        || card.kind === 'verdict') ? 'true' : 'false';
    }

    root.addEventListener('click', (e) => {
      if (e.target.closest('a,button')) return;
      if (root.dataset.gate === 'true') return;
      show(i + 1);
    });
    document.addEventListener('keydown', (e) => {
      if (root.hidden) return;
      if ((e.key === ' ' || e.key === 'ArrowRight') && root.dataset.gate !== 'true') {
        e.preventDefault(); show(i + 1);
      }
      if (e.key === 'ArrowLeft') { e.preventDefault(); show(i - 1); }
    });

    const sid = (sample.meta || {}).sample_id;
    pollMedia(sid, (url) => {
      if (cards.some((c) => c.kind === 'media')) return;
      cards.splice(cards.length - 1, 0, {
        kind: 'media',
        html: '<p class="pc-eyebrow">Illustrative only. No fact was given to the model.</p>'
          + '<video class="pc-video" src="' + esc(url) + '" autoplay loop muted playsinline></video>',
      });
      const pip = document.createElement('i');
      root.querySelector('#pcSpine').appendChild(pip);
      pips.push(pip);
    }, 40);

    show(0);
  }

  global.BedrockPlay = { mount: mount, build: build };
}(window));
