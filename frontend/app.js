const EXAMPLES = [
  "What is Dolo 650?",
  "Can I take warfarin with aspirin?",
  "What is hypothyroidism?",
  "I've had a sudden severe headache",
  "What happens if I take too much paracetamol?",
  "Haemoglobin 13.2 g/dL 13.0 - 17.0\nGlucose 104 mg/dL 70 - 100\nPotassium 6.9 mmol/L 3.5 - 5.1",
];

// Scheme allow-list. Setting .href is safe from markup injection but not
// from javascript: and data: URLs, which execute on click.
const SAFE_URL = /^https?:\/\//i;

const CONFIG = window.APP_CONFIG || {};

// One id per tab, kept only in memory -- lost on reload, which is fine:
// there is no auth left to make losing a thread costly. Long enough for
// AgentCore's runtimeSessionId (>= 33 chars).
const SESSION_ID = 's-' + crypto.randomUUID() + crypto.randomUUID();

async function callApi(path, body) {
  return fetch(CONFIG.apiEndpoint + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, session_id: SESSION_ID }),
  });
}

const thread = document.getElementById('thread');
const input = document.getElementById('input');
const send = document.getElementById('send');

EXAMPLES.forEach(text => {
  const b = document.createElement('button');
  b.textContent = text.split('\n')[0].slice(0, 38) + (text.length > 38 ? '…' : '');
  b.onclick = () => { input.value = text; ask(); };
  document.getElementById('examples').appendChild(b);
});

function el(cls, text) {
  const d = document.createElement('div');
  d.className = cls;
  if (text) d.textContent = text;
  return d;
}

// --------------------------------------------------------------------
// Markdown rendering
//
// The model answers in markdown -- bold, headings, bullet lists, code
// fences -- and the bubble used textContent, so readers saw literal
// asterisks and backticks.
//
// Built entirely from DOM nodes. Every value lands via .textContent or
// .href, never innerHTML, so nothing in a model answer or a label quote
// can be parsed as markup. Link hrefs are checked against a scheme
// allow-list, because assigning .href is safe from markup injection but
// not from javascript: URLs.
// --------------------------------------------------------------------

function inline(target, text) {
  // Order matters: code spans are taken first so their contents are not
  // re-interpreted as bold or as a link.
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0, m;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) target.appendChild(document.createTextNode(text.slice(last, m.index)));
    const token = m[0];
    if (token.startsWith('`')) {
      const code = document.createElement('code');
      code.textContent = token.slice(1, -1);
      target.appendChild(code);
    } else if (token.startsWith('**')) {
      const b = document.createElement('strong');
      b.textContent = token.slice(2, -2);
      target.appendChild(b);
    } else {
      const split = token.indexOf('](');
      const label = token.slice(1, split);
      const href = token.slice(split + 2, -1);
      if (SAFE_URL.test(href)) {
        const a = document.createElement('a');
        a.href = href;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = label;
        target.appendChild(a);
      } else {
        target.appendChild(document.createTextNode(label));
      }
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) target.appendChild(document.createTextNode(text.slice(last)));
}

function markdown(text) {
  const root = el('bubble');
  const lines = (text || '').split('\n');
  let list = null, fence = null;

  const closeList = () => { list = null; };

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (fence) { fence = null; } else {
        closeList();
        fence = document.createElement('pre');
        root.appendChild(fence);
      }
      continue;
    }
    if (fence) {
      fence.textContent += (fence.textContent ? '\n' : '') + line;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);

    if (heading) {
      closeList();
      const h = document.createElement('h4');
      inline(h, heading[2]);
      root.appendChild(h);
    } else if (bullet || numbered) {
      const tag = bullet ? 'ul' : 'ol';
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = document.createElement(tag);
        root.appendChild(list);
      }
      const li = document.createElement('li');
      inline(li, (bullet || numbered)[1]);
      list.appendChild(li);
    } else if (line.trim() === '') {
      closeList();
    } else {
      closeList();
      const para = document.createElement('p');
      inline(para, line);
      root.appendChild(para);
    }
  }
  return root;
}

function addMessage(who, build) {
  const msg = el('msg ' + who.toLowerCase());
  msg.appendChild(el('who', who));
  build(msg);
  thread.appendChild(msg);
  window.scrollTo(0, document.body.scrollHeight);
  return msg;
}

function resetInput() {
  input.value = '';
  // Height is reset explicitly. The textarea grows on input and nothing
  // shrank it on send, so the composer stayed tall after a long question.
  input.style.height = 'auto';
}

async function ask() {
  const prompt = input.value.trim();
  if (!prompt) return;
  resetInput();
  send.disabled = true;

  addMessage('You', m => m.appendChild(el('bubble', prompt)));
  const pending = addMessage('Assistant', m =>
    m.appendChild(el('bubble pending', 'Looking this up')));

  try {
    const res = await callApi('/chat', {prompt});
    const data = await res.json();
    pending.remove();

    addMessage('Assistant', m => {
      // Emergency guidance goes ABOVE the answer. Someone reading urgent
      // advice below three paragraphs of drug information may not reach it.
      if (data.escalation && data.severity === 'emergency') {
        m.appendChild(el('escalation emergency', data.escalation));
      }

      if (data.severity && data.severity !== 'informational') {
        m.querySelector('.who').appendChild(el('badge ' + data.severity, data.severity));
      }
      m.appendChild(markdown(data.answer));

      if (data.escalation && data.severity !== 'emergency') {
        m.appendChild(el('escalation ' + data.severity, data.escalation));
      }
      (data.caveats || []).forEach(c => m.appendChild(el('caveat', c)));

      // Citations are third-party data -- MedlinePlus topic titles,
      // openFDA set_ids -- and a title also embeds the drug name the
      // USER typed. All of it goes in as text and attribute nodes.
      const cites = (data.citations || []).filter(c => SAFE_URL.test(c.url || ''));
      if (cites.length) {
        const s = el('sources');
        s.appendChild(el('sources-label', 'Sources'));
        cites.forEach(c => {
          const a = document.createElement('a');
          a.href = c.url;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.textContent = c.title || c.url;
          s.appendChild(a);
        });
        m.appendChild(s);
      }
    });
  } catch (err) {
    pending.remove();
    addMessage('Assistant', m => {
      const b = el('bubble error', 'Could not reach the agent: ' + err.message);
      m.appendChild(b);
    });
  } finally {
    send.disabled = false;
    input.focus();
  }
}

input.focus();
send.onclick = ask;
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
});
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 190) + 'px';
});
