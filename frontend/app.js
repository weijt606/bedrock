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
  ['accepted', 'subject', 'plan', 'probe', 'layer', 'supply', 'statute', 'flag', 'gap', 'siblings', 'score', 'done']
    .forEach((type) => source.addEventListener(type, (event) => {
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
      if (type === 'done') source.close();
    }));
  source.addEventListener('error', (event) => {
    if (event.data) showJson('Bedrock error', JSON.parse(event.data));
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
