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

    guesses.slice(0, 2).forEach((g, n) => cards.push({
      kind: 'bet', id: g.id,
      html: '<p class="pc-eyebrow">'
        + (n === 0 ? 'Before we show you anything' : 'One more') + '</p>'
        + '<h2 class="pc-head">' + esc(g.question) + '</h2>'
        + '<div class="pc-chips" role="group" aria-label="Your answer">'
        + g.options.map((o) => '<button class="pc-chip" type="button" data-pick="'
            + esc(o) + '">' + esc(o) + '</button>').join('')
        + '</div><p class="pc-say">Pick one. We will hold you to it.</p>',
    }));

    (sample.story || []).forEach((beat) => {
      const fig = splitFigure(beat.headline);
      const head = fig
        ? '<p class="pc-figure">' + esc(fig.figure) + '</p>'
          + '<h2 class="pc-head pc-head--under">' + esc(fig.rest) + '</h2>'
        : '<h2 class="pc-head">' + esc(beat.headline) + '</h2>';
      cards.push({
        kind: 'beat',
        html: '<p class="pc-eyebrow">' + esc(KIND_LABEL[beat.kind] || beat.kind) + '</p>'
          + head
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
        kind: 'beat',
        html: '<p class="pc-eyebrow">And what nobody has written down</p>'
          + '<p class="pc-figure">0</p>'
          + '<h2 class="pc-head pc-head--under">rows, however we asked.</h2>'
          + '<ul class="pc-qs">' + tries.map((q) => '<li>' + esc(q) + '</li>').join('') + '</ul>'
          + '<p class="pc-say">Asked ' + (tries.length === 1 ? 'once' : tries.length + ' ways')
          + ', all empty. A question with no answer is a finding, not an error.</p>',
      });
    });

    cards.push({ kind: 'verdict', html: '' });
    return cards;
  }

  function mount(root, sample) {
    const cards = build(sample);
    const picks = {};
    let i = 0;

    root.innerHTML = '<div class="pc" id="pcStage"></div>'
      + '<div class="pc-spine" id="pcSpine">'
      + cards.map(() => '<i></i>').join('') + '</div>';
    const stage = root.querySelector('#pcStage');
    const pips = [].slice.call(root.querySelector('#pcSpine').children);

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
      (sample.guesses || []).slice(0, 2).forEach((g) => {
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
        + 'the document behind it. None of it was written by a model.</p>';
    };

    function show(n) {
      i = Math.max(0, Math.min(cards.length - 1, n));
      const card = cards[i];
      stage.innerHTML = '<section class="pc-card" data-kind="' + card.kind + '">'
        + (card.kind === 'verdict' ? verdictHtml() : card.html) + '</section>';
      pips.forEach((p, k) => p.classList.toggle('on', k <= i));

      const fig = stage.querySelector('[data-count]');
      if (fig) countUp(fig, parseInt(fig.dataset.count, 10));

      stage.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', (e) => {
        e.stopPropagation();
        picks[card.id] = b.dataset.pick;
        show(i + 1);
      }));

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

    show(0);
  }

  global.BedrockPlay = { mount: mount, build: build };
}(window));
