// Local development talks to the local API; production uses the same Vercel
// deployment through /api, so browsers never need access to a developer's Mac.
const API_URL = window.BEDROCK_API_URL || (
  ['127.0.0.1', 'localhost'].includes(window.location.hostname)
    ? 'http://127.0.0.1:8000'
    : '/api'
);
const subject = document.querySelector('#subject');
const form = document.querySelector('#intake-form');
const helper = document.querySelector('#helper');
const photoButton = document.querySelector('#photo-button');
const photoInput = document.querySelector('#photo-input');
const mediaPreview = document.querySelector('#media-preview');
const photoPreview = document.querySelector('#photo-preview');
const removePhoto = document.querySelector('#remove-photo');
const voiceButton = document.querySelector('#voice-button');
const attachmentLabel = document.querySelector('#attachment-label');
const defaultControls = document.querySelector('.default-controls');
const recordingControls = document.querySelector('.recording-controls');
const cancelRecording = document.querySelector('#cancel-recording');
const stopRecordingButton = document.querySelector('#stop-recording');
const waveformBars = [...document.querySelectorAll('.waveform span')];
const responsePanel = document.querySelector('#response-panel');
const responseOutput = document.querySelector('#response-output');
const notice = document.querySelector('#notice');

const examples = ['Starbucks Macchiato', 'Oreo Original', 'Nutella', 'Coca-Cola Zero'];
let exampleIndex = 0;
let demoStopped = false;
let isRecording = false;
let mediaRecorder;
let microphoneStream;
let audioContext;
let analyser;
let animationFrame;
let audioChunks = [];
let selectedPhoto = null;
let discardRecording = false;
let noticeTimer;
let responseEntries = [];

const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
const showNotice = (message) => {
  notice.textContent = message;
  notice.classList.add('show');
  window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => notice.classList.remove('show'), 2600);
};
const showJson = (label, value) => {
  console.info(`[Bedrock] ${label}`, value);
  responseEntries.push({ label, value });
  responsePanel.hidden = false;
  responseOutput.textContent = responseEntries.map((entry) => (
    `${entry.label}\n${JSON.stringify(entry.value, null, 2)}`
  )).join('\n\n');
};
const resetResponse = () => {
  responseEntries = [];
  responsePanel.hidden = true;
  responseOutput.textContent = '';
};
const summarizePayload = (payload) => ({
  ...payload,
  ...(payload.image_b64 ? { image_b64: `[base64 image: ${payload.image_b64.length} chars]` } : {}),
  ...(payload.audio_b64 ? { audio_b64: `[base64 audio: ${payload.audio_b64.length} chars]` } : {}),
});
const resize = () => {
  subject.style.height = 'auto';
  subject.style.height = `${Math.min(128, Math.max(28, subject.scrollHeight))}px`;
};
const clearDemo = () => {
  if (!demoStopped) {
    demoStopped = true;
    subject.value = '';
    document.body.classList.remove('is-demo');
    helper.textContent = 'Type a food, product or brand';
    resize();
  }
};
const toBase64 = (blob) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(',')[1]);
  reader.onerror = reject;
  reader.readAsDataURL(blob);
});
const stopWaveform = () => {
  window.cancelAnimationFrame(animationFrame);
  waveformBars.forEach((bar) => { bar.style.height = ''; });
};
const drawWaveform = () => {
  if (!analyser) return;
  const levels = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(levels);
  waveformBars.forEach((bar, index) => {
    const value = levels[Math.min(levels.length - 1, index * 4 + 2)] || 0;
    bar.style.height = `${4 + Math.round((value / 255) * 23)}px`;
  });
  animationFrame = window.requestAnimationFrame(drawWaveform);
};
const closeMicrophone = () => {
  stopWaveform();
  microphoneStream?.getTracks().forEach((track) => track.stop());
  audioContext?.close();
  microphoneStream = null;
  audioContext = null;
  analyser = null;
};
const setRecording = (active) => {
  isRecording = active;
  defaultControls.hidden = active;
  recordingControls.hidden = !active;
  subject.disabled = active;
  if (active) {
    clearDemo();
    subject.value = '';
    helper.textContent = 'Listening…';
  } else {
    helper.textContent = 'Type a food, product or brand';
  }
  resize();
};
const removeSelectedPhoto = () => {
  selectedPhoto = null;
  photoInput.value = '';
  photoPreview.removeAttribute('src');
  mediaPreview.hidden = true;
  subject.hidden = false;
  attachmentLabel.textContent = '';
  photoButton.classList.remove('active');
  resize();
};

async function typeExample(text) {
  subject.value = '';
  resize();
  for (const character of text) {
    if (demoStopped) return;
    subject.value += character;
    helper.textContent = `For example: ${text}`;
    resize();
    await wait(90);
  }
  await wait(1550);
  while (subject.value && !demoStopped) {
    subject.value = subject.value.slice(0, -1);
    resize();
    await wait(38);
  }
  await wait(330);
}
async function playExamples() {
  await wait(1150);
  while (!demoStopped) {
    await typeExample(examples[exampleIndex]);
    exampleIndex = (exampleIndex + 1) % examples.length;
  }
}
async function startRecording() {
  clearDemo();
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    showNotice('Voice input is not supported in this browser.');
    return;
  }
  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    discardRecording = false;
    mediaRecorder = new MediaRecorder(microphoneStream, { mimeType: 'audio/webm' });
    mediaRecorder.addEventListener('dataavailable', (event) => {
      if (event.data.size) audioChunks.push(event.data);
    });
    mediaRecorder.addEventListener('stop', async () => {
      const audio = audioChunks.length && !discardRecording
        ? new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' })
        : null;
      closeMicrophone();
      if (audio) await transcribeVoice(audio);
    });
    audioContext = new AudioContext();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 64;
    audioContext.createMediaStreamSource(microphoneStream).connect(analyser);
    mediaRecorder.start(120);
    setRecording(true);
    drawWaveform();
  } catch (error) {
    closeMicrophone();
    showNotice('Microphone access is needed to record a voice note.');
    showJson('Microphone error', { message: error.message });
  }
}
const stopRecording = (save) => {
  if (!isRecording) return;
  setRecording(false);
  if (mediaRecorder?.state === 'recording') mediaRecorder.stop();
  if (!save) {
    discardRecording = true;
    audioChunks = [];
    closeMicrophone();
    helper.textContent = 'Voice note cancelled';
  }
};
async function transcribeVoice(audio) {
  try {
    helper.textContent = 'Turning voice into text…';
    const payload = { audio_b64: await toBase64(audio), mime: audio.type || 'audio/webm' };
    showJson('Sending audio to fal', summarizePayload(payload));
    const response = await fetch(`${API_URL}/v1/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    showJson('fal transcription response', data);
    if (!response.ok) throw new Error(data.detail || 'fal could not transcribe this voice note.');
    subject.hidden = false;
    subject.disabled = false;
    subject.value = data.text;
    resize();
    helper.textContent = 'Transcribed with fal — press Enter to trace it';
    attachmentLabel.textContent = '';
    showJson('fal transcription', data);
  } catch (error) {
    helper.textContent = 'Voice could not be transcribed';
    showNotice('Voice could not be transcribed. Check microphone permission and try again.');
    showJson('fal transcription issue', {
      message: error.message || 'Voice transcription was not available.',
      hint: 'Allow microphone access, record a short clear phrase, then press Stop.',
    });
  }
}
async function describePhoto(photo) {
  try {
    helper.textContent = 'Reading the label…';
    const payload = { image_b64: await toBase64(photo), mime: photo.type || 'image/jpeg' };
    showJson('Sending image to OpenAI', summarizePayload(payload));
    const response = await fetch(`${API_URL}/v1/describe-image`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    showJson('OpenAI image response', data);
    if (!response.ok) throw new Error(data.detail || 'OpenAI could not read this image.');
    subject.disabled = false;
    subject.value = data.text;
    resize();
    helper.textContent = 'Label read by OpenAI — press Enter to trace it';
    showJson('OpenAI image description', data);
  } catch (error) {
    helper.textContent = 'Photo attached — try a closer view of the product label';
    showNotice('OpenAI could not read the label. Try a sharper, closer photo.');
    showJson('OpenAI image description issue', {
      message: error.message || 'OpenAI could not read this image.',
      hint: 'Make the brand name large, well lit and fully visible.',
    });
  }
}
// ---------------------------------------------------------------------------
//  the seam between intake and the output layer
// ---------------------------------------------------------------------------
//
// This file owns *input*: text, a photograph, a voice note, and the stream that
// comes back. It does not own what the findings look like. Everything the output
// layer needs arrives on two DOM events, so a renderer can be swapped in without
// touching a line of intake code:
//
//   document.addEventListener('bedrock:frame',  e => e.detail)  // every SSE frame
//   document.addEventListener('bedrock:result', e => e.detail)  // the CoreSample
//
// `bedrock:frame` detail is {type, payload, at, agent, sample_id} — the frame as
// the API sent it. `bedrock:result` detail is the finished CoreSample.
// `window.BEDROCK_ONRESULT` is called with the same object, for anyone who would
// rather have a callback.
//
// The renderer at the bottom of this file listens on exactly these two events and
// nothing else. It is a reference implementation, not a dependency — delete it and
// the seam still works.

const FRAME_TYPES = [
  'accepted', 'subject', 'plan', 'probe', 'layer', 'supply', 'statute',
  'flag', 'concern', 'siblings', 'score', 'gap', 'done', 'error',
];

const emitFrame = (frame) => document.dispatchEvent(
  new CustomEvent('bedrock:frame', { detail: frame }));

const emitResult = (sample) => {
  document.dispatchEvent(new CustomEvent('bedrock:result', { detail: sample }));
  if (typeof window.BEDROCK_ONRESULT === 'function') {
    try { window.BEDROCK_ONRESULT(sample); } catch (error) { console.error(error); }
  }
};

async function submitToBedrock(payload) {
  showJson('Sending to Bedrock', summarizePayload(payload));
  const response = await fetch(`${API_URL}/v1/samples`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Bedrock could not accept this input.');
  showJson('Bedrock accepted', data);

  const source = new EventSource(`${API_URL}${data.events}`);
  FRAME_TYPES.forEach((type) => source.addEventListener(type, (event) => {
    const frame = JSON.parse(event.data);
    if (type === 'subject' && payload.kind === 'audio') {
      const transcript = frame.payload.raw_input || frame.payload.resolved_name;
      if (transcript) {
        subject.hidden = false;
        subject.disabled = false;
        subject.value = transcript;
        resize();
        helper.textContent = 'Transcribed by fal';
      }
    }
    showJson(`Bedrock event: ${type}`, frame);
    emitFrame(frame);
    if (type === 'done') {
      emitResult(frame.payload);
      source.close();
    }
  }));

  // EventSource fires `error` for transport blips too, where the browser would
  // reconnect on its own. Only a frame the server actually sent carries `data`,
  // and only that should end the stream — a cold dig runs 30-90s and a dropped
  // connection mid-way is normal.
  source.addEventListener('error', (event) => {
    if (!event.data) return;
    showJson('Bedrock error', JSON.parse(event.data));
    source.close();
  });
}

window.addEventListener('load', () => {
  window.setTimeout(() => {
    document.body.classList.remove('is-loading');
    document.querySelector('#app').setAttribute('aria-busy', 'false');
    playExamples();
  }, 750);
});
subject.addEventListener('focus', clearDemo);
subject.addEventListener('input', () => { clearDemo(); resize(); });
subject.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
photoButton.addEventListener('click', () => { clearDemo(); photoInput.click(); });
photoInput.addEventListener('change', () => {
  const [photo] = photoInput.files;
  if (!photo) return;
  clearDemo();
  selectedPhoto = photo;
  photoPreview.src = URL.createObjectURL(photo);
  mediaPreview.hidden = false;
  subject.hidden = false;
  photoButton.classList.add('active');
  helper.textContent = 'Photo attached — reading the label…';
  showJson('Photo ready for Bedrock', { kind: 'image', mime: photo.type, bytes: photo.size });
  void describePhoto(photo);
});
removePhoto.addEventListener('click', removeSelectedPhoto);
voiceButton.addEventListener('click', startRecording);
cancelRecording.addEventListener('click', () => stopRecording(false));
stopRecordingButton.addEventListener('click', () => stopRecording(true));
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (isRecording) { showNotice('Stop recording when you are ready.'); return; }
  try {
    resetResponse();
    let payload;
    if (subject.value.trim()) {
      payload = { kind: 'text', text: subject.value.trim(), depth: 4 };
    } else if (selectedPhoto) {
      payload = { kind: 'image', image_b64: await toBase64(selectedPhoto), mime: selectedPhoto.type, depth: 4 };
    } else {
      subject.focus();
      showNotice('Start with a food, product, brand, voice note or photo.');
      return;
    }
    await submitToBedrock(payload);
    showNotice('Bedrock has started your trace.');
  } catch (error) {
    console.error('[Bedrock] request failed', error);
    showNotice('Bedrock is not reachable. Check that the local server is running.');
    showJson('Connection issue', {
      message: 'Bedrock is not reachable. Check that the local server is running.',
    });
  }
});

// ===========================================================================
//  Reference renderer
// ===========================================================================
//
//  Listens on `bedrock:frame` and `bedrock:result` and nothing else. It exists
//  so the pipe can be seen working end to end, and so the output layer has a
//  worked example of what arrives and when. Replacing it means deleting from
//  here down and listening on the same two events.
//
//  Three things it is careful about, because each one is a way to mislead:
//
//   * a `provisional` layer is the reader's fast sketch, superseded by the
//     ladder's — it is replaced, never appended to;
//   * `status: "clear"` on a concern is rendered as "nothing filed", never as a
//     clean bill of health;
//   * a gap shows the ladder of phrasings that came back empty, so the silence
//     proves itself rather than being asserted.

const digView = document.querySelector('#dig');
const chainList = document.querySelector('#chain');
const digSubject = document.querySelector('#dig-subject');
const probeLine = document.querySelector('#probe');
const probeQuery = document.querySelector('#probe-q');
const probeTimer = document.querySelector('#probe-t');
const resultView = document.querySelector('#result');
const scoreBox = document.querySelector('#score');
const concernsBox = document.querySelector('#concerns');
const storyList = document.querySelector('#story');
const sourcesWrap = document.querySelector('#sources-wrap');
const sourcesList = document.querySelector('#sources');
const sourcesCount = document.querySelector('#sources-count');
const againButton = document.querySelector('#again');

const COUNTRY = {
  ES: 'Spain', NL: 'Netherlands', LU: 'Luxembourg', DE: 'Germany', IT: 'Italy',
  FR: 'France', GB: 'United Kingdom', US: 'United States', CH: 'Switzerland',
  BE: 'Belgium', IE: 'Ireland', PT: 'Portugal', SE: 'Sweden', DK: 'Denmark',
  AT: 'Austria', TR: 'Türkiye',
};
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let probeTicker = null;
const stopProbe = () => {
  window.clearInterval(probeTicker);
  probeTicker = null;
  probeLine.hidden = true;
};
const startProbe = (query) => {
  probeQuery.textContent = query;
  probeLine.hidden = false;
  const started = Date.now();
  window.clearInterval(probeTicker);
  probeTicker = window.setInterval(() => {
    probeTimer.textContent = `${Math.round((Date.now() - started) / 1000)}s`;
  }, 500);
};

const layerHtml = (layer) => {
  const human = layer.kind === 'person' || layer.kind === 'family';
  const where = layer.country ? (COUNTRY[layer.country] || layer.country) : null;
  const step = layer.provisional
    ? 'read from the prose'
    : `Step ${layer.index + 1}${where ? ` · ${where}` : ''}`;
  const meta = (layer.detail || []).slice(0, 4).map(escapeHtml).join('<br>');
  return `
    <p class="chain__step">${escapeHtml(step)}</p>
    <p class="chain__name" data-human="${human}">${escapeHtml(layer.name)}</p>
    ${meta ? `<p class="chain__meta">${meta}</p>` : ''}
    ${layer.address ? `<p class="chain__addr">${escapeHtml(layer.address)}</p>` : ''}`;
};

const addLayer = (layer) => {
  stopProbe();
  // The ladder supersedes the reader's sketch rather than stacking on top of it.
  if (!layer.provisional) {
    chainList.querySelectorAll('li[data-provisional="true"]').forEach((n) => n.remove());
  }
  const item = document.createElement('li');
  item.dataset.provisional = String(Boolean(layer.provisional));
  item.dataset.terminal = String(Boolean(layer.terminal));
  item.innerHTML = layerHtml(layer);
  chainList.appendChild(item);
  item.scrollIntoView({ behavior: 'smooth', block: 'center' });
};

const addGap = (gap) => {
  stopProbe();
  const attempts = (gap.attempts || []).length
    ? `<ul>${gap.attempts.map((q) => `<li>${escapeHtml(q)}</li>`).join('')}</ul>`
    : '';
  const item = document.createElement('li');
  item.innerHTML = `
    <p class="chain__step">Nothing on the record</p>
    <div class="gap">
      ${escapeHtml(gap.query)} → rows = <b>0</b>
      ${attempts ? `<p style="margin:.7rem 0 0;opacity:.7">Asked ${gap.attempts.length} ways:</p>${attempts}` : ''}
    </div>`;
  chainList.appendChild(item);
};

const concernHtml = (report) => {
  const label = report.concern.replace(/_/g, ' ');
  const checked = (report.entities_checked || []).length;
  if (report.status !== 'found') {
    return `
      <div class="concern" data-status="clear">
        <div class="concern__head"><span>${escapeHtml(label)}</span><span>nothing filed</span></div>
        <p class="concern__note">Asked about ${checked} ${checked === 1 ? 'company' : 'companies'}
        in this chain and found no public record. An empty record is not a clean record.</p>
      </div>`;
  }
  const flags = (report.flags || []).map((flag) => `
    <div class="concern__flag">
      ${flag.about ? `<span class="concern__about">${escapeHtml(flag.about)}</span>` : ''}
      <p class="concern__title">${escapeHtml(flag.title)}</p>
      ${flag.summary ? `<p class="concern__sum">${escapeHtml(flag.summary)}</p>` : ''}
    </div>`).join('');
  return `
    <div class="concern" data-status="found">
      <div class="concern__head"><span>${escapeHtml(label)}</span><span>on the record</span></div>
      ${flags}
      <p class="concern__note">Checked ${checked} ${checked === 1 ? 'company' : 'companies'}
      in this chain. Bedrock reports what is filed; the judgement is yours.</p>
    </div>`;
};

const renderResult = (sample) => {
  const score = sample.score || {};
  const trail = (score.countries || []).join(' → ');
  scoreBox.innerHTML = `
    <div><b>${score.hops_to_human ?? 0}</b><span>steps to<br>a person</span></div>
    <div><b>${(score.countries || []).length}</b><span>countries<br>crossed</span></div>
    <div class="${score.left_home ? 'hot' : ''}">
      <b>${score.ends_in ? escapeHtml(COUNTRY[score.ends_in] || score.ends_in) : '—'}</b>
      <span>${trail ? escapeHtml(trail) : 'ends in'}</span></div>`;

  concernsBox.innerHTML = (sample.concerns || []).map(concernHtml).join('');

  storyList.innerHTML = (sample.story || []).map((beat) => `
    <li data-kind="${escapeHtml(beat.kind)}" data-weight="${beat.weight >= 0.7 ? 'high' : 'normal'}">
      <p class="story__kind">${escapeHtml(beat.kind)}</p>
      <p class="story__head">${escapeHtml(beat.headline)}</p>
      ${beat.detail ? `<p class="story__detail">${escapeHtml(beat.detail)}</p>` : ''}
    </li>`).join('');

  // Every document behind every claim, deduplicated. These are real URLs from
  // Cala's `context`, which is the difference between a citation and a footnote.
  const urls = new Set();
  const collect = (item) => (item?.source?.documents || []).forEach((u) => urls.add(u));
  (sample.layers || []).forEach(collect);
  (sample.supply || []).forEach(collect);
  (sample.statutes || []).forEach(collect);
  (sample.flags || []).forEach(collect);
  (sample.concerns || []).forEach((c) => (c.flags || []).forEach(collect));
  sourcesCount.textContent = `(${urls.size})`;
  sourcesList.innerHTML = [...urls].map((u) => (
    `<li><a href="${escapeHtml(u)}" target="_blank" rel="noopener noreferrer">${escapeHtml(u)}</a></li>`
  )).join('');
  sourcesWrap.hidden = urls.size === 0;

  resultView.hidden = false;
  resultView.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

document.addEventListener('bedrock:frame', (event) => {
  const { type, payload } = event.detail;
  if (type === 'accepted') {
    chainList.innerHTML = '';
    concernsBox.innerHTML = '';
    storyList.innerHTML = '';
    resultView.hidden = true;
    digView.hidden = false;
  } else if (type === 'subject') {
    digSubject.textContent = payload.resolved_name || '';
  } else if (type === 'probe') {
    startProbe(payload.query);
  } else if (type === 'layer') {
    addLayer(payload);
  } else if (type === 'gap') {
    addGap(payload);
  } else if (type === 'concern') {
    concernsBox.insertAdjacentHTML('beforeend', concernHtml(payload));
  } else if (type === 'done' || type === 'error') {
    stopProbe();
  }
});

document.addEventListener('bedrock:result', (event) => renderResult(event.detail));

againButton?.addEventListener('click', () => {
  resultView.hidden = true;
  digView.hidden = true;
  subject.value = '';
  resize();
  subject.focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});
